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
        self.equipment: dict[str, Item | None] = {"weapon": None, "armor": None}

        # 本局统计计数器
        self.turns: int = 0
        self.kills: int = 0
        self.steps: int = 0
        self.damage_dealt: int = 0
        self.damage_taken: int = 0
        self.items_used: int = 0

    # ------------------------------------------------------------ 属性加成
    def total_atk(self) -> int:
        """基础攻击 + 武器加成。"""
        weapon = self.equipment.get("weapon")
        bonus = getattr(weapon, "atk_bonus", 0) or 0
        return self.atk + bonus

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
        """拾取道具。背包满时返回失败原因，不抛异常。"""
        if len(self.inventory) >= config.INVENTORY_CAPACITY:
            return False, f"背包已满（{config.INVENTORY_CAPACITY} 格），无法拾取"
        self.inventory.append(item)
        return True, f"拾取了{item.name}"

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
        """装到对应装备槽。"""
        slot = "weapon" if item.kind == "weapon" else "armor"
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
            }
        )
        return data

    @classmethod
    def create_new(cls, name: str = "冒险者") -> "Player":
        """开新档：从配置读取初始属性并赠送两瓶小药水。"""
        player = cls(name=name, hp=config.PLAYER_START_HP)
        from .item import make_item

        for _ in range(config.PLAYER_START_POTION):
            player.inventory.append(make_item("potion_small"))
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
        player.equipment = {
            "weapon": item_from_dict(equipment["weapon"]) if equipment.get("weapon") else None,
            "armor": item_from_dict(equipment["armor"]) if equipment.get("armor") else None,
        }
        return player
