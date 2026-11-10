"""玩家角色模块。

``Player`` 在 ``Entity`` 的基础上增加了等级经验、金币、背包、装备槽，
以及一整局的行为计数器（步数、击杀、总输出/承受伤害），
这些计数器最后会写进 ``records.json`` 供统计分析使用。
"""

from __future__ import annotations

from typing import Any

from . import config
from .entity import Entity
from .item import Item, item_from_dict


class Player(Entity):
    """玩家角色。"""

    def __init__(
        self,
        name: str = "冒险者",
        x: int = 1,
        y: int = 1,
        hp: int = config.PLAYER_START_HP,
        atk: int = config.PLAYER_START_ATK,
        defense: int = config.PLAYER_START_DEF,
    ) -> None:
        super().__init__(name, "@", x, y, hp, atk, defense)
        self.level: int = 1
        self.exp: int = 0
        self.gold: int = 0
        self.floor: int = 1
        self.inventory: list[Item] = []
        # 三个装备槽：兵刃 / 弓 / 护甲。旧存档只有 weapon+armor，读档时补默认值
        self.equipment: dict[str, Item | None] = {"weapon": None, "ranged": None, "armor": None}

        # 蓄力状态：重武器出手前要花若干回合抬起，期间脚下会显示黄色预警
        self.charge_left: int = 0
        self.charge_weapon: str = ""
        self.charge_tiles: set[tuple[int, int]] = set()

        # 本局统计计数器
        self.turns: int = 0
        self.kills: int = 0
        self.steps: int = 0
        self.damage_dealt: int = 0
        self.damage_taken: int = 0
        self.items_used: int = 0

    # ------------------------------------------------------------ 属性加成
    def weapon_in(self, slot: str) -> "Item | None":
        """取某个槽位上的武器（``weapon`` 近战 / ``ranged`` 远程）。"""
        return self.equipment.get(slot)

    def attack_power(self, weapon: "Item | None") -> int:
        """用指定武器出手时的攻击力 = 基础攻击 + 该武器加成。

        注意只算**这一把**武器的加成：双槽并存时不能把两把武器的加成叠加，
        否则"切换武器"就没有取舍了。
        """
        bonus = getattr(weapon, "atk_bonus", 0) or 0
        return self.atk + bonus

    def total_atk(self) -> int:
        """面板展示用的攻击力：基础攻击 + 近战武器加成。"""
        return self.attack_power(self.equipment.get("weapon"))

    def total_def(self) -> int:
        """基础防御 + 护甲加成。"""
        armor = self.equipment.get("armor")
        bonus = getattr(armor, "def_bonus", 0) or 0
        return self.defense + bonus

    @property
    def exp_to_next(self) -> int:
        """升到下一级所需经验。等级越高需求越大。"""
        return max(1, int(config.EXP_BASE * (config.EXP_GROWTH ** (self.level - 1))))

    @property
    def kd_ratio(self) -> float:
        """输出伤害与承受伤害之比，用于结算面板与统计图表。"""
        if self.damage_taken <= 0:
            return float(self.damage_dealt)
        return self.damage_dealt / self.damage_taken

    # ------------------------------------------------------------ 成长
    def gain_exp(self, amount: int) -> list[str]:
        """获得经验，可能连续升多级。

        返回升级提示文本列表，由界面层决定怎么展示。
        一次给十万经验也能在一轮里连升多级，不会漏升级。
        """
        if amount <= 0:
            return []
        self.exp += amount
        messages: list[str] = []
        # 用 for 循环兜底，避免数值异常时死循环
        for _ in range(200):
            need = self.exp_to_next
            if need <= 0 or self.exp < need:
                break
            self.exp -= need
            self.level += 1
            self.max_hp += config.LEVEL_UP_HP
            self.hp = self.max_hp                      # 升级回满血
            self.atk += config.LEVEL_UP_ATK
            self.defense += config.LEVEL_UP_DEF
            messages.append(f"升级！你已达到 {self.level} 级（生命回满，攻防提升）")
        return messages

    # ------------------------------------------------------------ 背包
    def pick_up(self, item: Item) -> tuple[bool, str]:
        """拾取道具。同名装备会自动合成升级，背包满时返回失败原因，不抛异常。

        合成放在"背包容量检查"之前：背包满时若不合成，玩家会既捡不起又
        用不上，两套规则互相打架。合成规则：同名武器/护甲且未满级，等级 +1、
        攻击（或防御）+1，优先合身上穿着的，再合背包里等级更高的那件。
        """
        from .item import Armor, Weapon

        merged = self._try_merge_equipment(item, Weapon, Armor)
        if merged is not None:
            return True, merged

        if len(self.inventory) >= config.INVENTORY_CAPACITY:
            return False, f"背包已满（{config.INVENTORY_CAPACITY} 格），无法拾取"
        self.inventory.append(item)
        return True, f"拾取了{item.name}"

    def _try_merge_equipment(self, item: Item, weapon_cls: type, armor_cls: type) -> str | None:
        """尝试把同名装备合进已有的一件；成功返回提示文本，否则返回 None。

        只处理武器与护甲，药水和卷轴直接跳过。候选顺序：身上穿着的优先
        （让"第二把铁剑"立刻变成攻击力），再挑背包里等级最高的那件。
        """
        if not isinstance(item, (weapon_cls, armor_cls)):
            return None
        if item.upgrade_level >= config.UPGRADE_MAX_LEVEL:
            return None

        if isinstance(item, weapon_cls):
            # 武器 slot 是 "melee"/"ranged"，但装备槽的键是 "weapon"/"ranged"，
            # 需要映射：melee 武器挂在 equipment["weapon"] 上
            equip_slot = "weapon" if item.slot == "melee" else item.slot
            candidates = [
                self.equipment.get(equip_slot),
                *(i for i in self.inventory if isinstance(i, weapon_cls) and i.slot == item.slot),
            ]
        else:
            candidates = [
                self.equipment.get("armor"),
                *(i for i in self.inventory if isinstance(i, armor_cls)),
            ]
        candidates = [c for c in candidates if c is not None and c.key == item.key]
        if not candidates:
            return None
        # 等级取较高者 +1，再截断到上限
        target = max(candidates, key=lambda c: c.upgrade_level)
        if target.upgrade_level >= config.UPGRADE_MAX_LEVEL:
            return None
        # 用 restore_upgrade 统一重放加成，保证合成与读档两条路径数值一致
        target.restore_upgrade(target.upgrade_level + 1)
        return f"捡到同款{target.name}，自动合成升级为 {target.title}"

    def use_item(self, index: int, state: Any = None) -> tuple[bool, str]:
        """使用背包第 ``index`` 格的道具。

        索引非法、背包为空等情况下返回 ``(False, 原因)`` 而不是抛 ``IndexError``，
        这样界面层不必写 try/except 就能安全提示。
        ``state`` 会透传给卷轴类道具（传送、烈焰需要访问地图信息）。
        """
        if not isinstance(index, int):
            return False, "道具栏位无效"
        if index < 0 or index >= len(self.inventory):
            return False, "这个格子里没有道具"
        if not self.alive:
            return False, "你已经倒下了"
        item = self.inventory[index]
        ok, message = item.apply(self, state)
        if ok:
            # 使用成功即从背包移除（武器护甲已转存到装备槽）
            self.inventory.pop(index)
        return ok, message

    def equip(self, item: Item) -> None:
        """装到对应装备槽。武器按 ``slot`` 分流到近战或远程槽。"""
        if item.kind == "weapon":
            slot = getattr(item, "slot", "melee")
        elif item.kind == "armor":
            slot = "armor"
        else:
            slot = "weapon"
        self.equipment[slot] = item

    def inventory_brief(self) -> list[str]:
        """背包简述，供界面与报告展示。"""
        return [f"{item.glyph} {item.name}" for item in self.inventory]

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict[str, Any]:
        data = self._base_dict()
        data.update(
            {
                "level": self.level,
                "exp": self.exp,
                "gold": self.gold,
                "floor": self.floor,
                "turns": self.turns,
                "kills": self.kills,
                "steps": self.steps,
                "damage_dealt": self.damage_dealt,
                "damage_taken": self.damage_taken,
                "items_used": self.items_used,
                "inventory": [item.to_dict() for item in self.inventory],
                "equipment": {
                    slot: (item.to_dict() if item is not None else None)
                    for slot, item in self.equipment.items()
                },
                "charge_left": self.charge_left,
                "charge_weapon": self.charge_weapon,
                "charge_tiles": [list(cell) for cell in sorted(self.charge_tiles)],
            }
        )
        return data

    @classmethod
    def create_new(cls, name: str = "冒险者") -> "Player":
        """开新档：从配置读取初始属性，赠送两瓶药水和一把旧剑。

        新战斗系统要求"必须装备武器才能攻击"，所以初始必须给一把最基础的近战
        武器，否则玩家在第 1 层连史莱姆都打不了。
        """
        player = cls(name=name, hp=config.PLAYER_START_HP)
        from .item import make_item

        for _ in range(config.PLAYER_START_POTION):
            player.inventory.append(make_item("potion_small"))
        player.equipment["weapon"] = make_item("sword_iron")
        return player

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Player":
        player = cls(
            name=data.get("name", "冒险者"),
            x=int(data["x"]),
            y=int(data["y"]),
            hp=int(data["max_hp"]),          # 先按满血构造，再覆盖当前血量
            atk=int(data["atk"]),
            defense=int(data["defense"]),
        )
        player.hp = int(data["hp"])
        player.alive = player.hp > 0
        player.level = int(data.get("level", 1))
        player.exp = int(data.get("exp", 0))
        player.gold = int(data.get("gold", 0))
        player.floor = int(data.get("floor", 1))
        player.turns = int(data.get("turns", 0))
        player.kills = int(data.get("kills", 0))
        player.steps = int(data.get("steps", 0))
        player.damage_dealt = int(data.get("damage_dealt", 0))
        player.damage_taken = int(data.get("damage_taken", 0))
        player.items_used = int(data.get("items_used", 0))
        player.inventory = [item_from_dict(d) for d in data.get("inventory", [])]
        equipment = data.get("equipment") or {}
        # 旧存档（v1）只有 weapon/armor，缺 ranged 时补 None，保证向后兼容
        player.equipment = {
            slot: (item_from_dict(equipment[slot]) if equipment.get(slot) else None)
            for slot in ("weapon", "ranged", "armor")
        }
        player.charge_left = int(data.get("charge_left", 0))
        player.charge_weapon = str(data.get("charge_weapon", ""))
        player.charge_tiles = {
            (int(pair[0]), int(pair[1])) for pair in data.get("charge_tiles", [])
        }
        return player
