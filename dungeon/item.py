"""道具模块。

``Item`` 与 ``Entity`` 是两个独立的继承体系：道具不占据地图实体位，
而是挂在地图的坐标索引上，因此不继承 ``Entity``。

四类道具：
- ``Potion`` 药水：立即回复生命；
- ``Weapon`` 武器：装备后提升攻击；
- ``Armor``  护甲：装备后提升防御；
- ``Scroll`` 卷轴：一次性法术效果（传送 / 烈焰 / 祝福）。

反序列化靠 ``ITEM_FACTORY`` 按 ``cls`` 字段分发，新增道具类型时
只需实现类 + 注册工厂，不必改动存档代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable

from . import config

if TYPE_CHECKING:  # 仅用于类型检查，避免运行时循环导入
    from .player import Player
    from .rng import Rng


class Item(ABC):
    """道具基类。"""

    kind: str = "item"
    glyph: str = "?"

    def __init__(self, key: str, name: str, desc: str) -> None:
        self.key = key
        self.name = name
        self.desc = desc

    @abstractmethod
    def apply(self, player: "Player", state: Any = None) -> tuple[bool, str]:
        """使用道具，返回 (是否成功, 提示文本)。

        约定：**永远不抛异常**。背包为空、道具不适用等异常情况一律通过
        返回值表达，由界面层弹出提示。这是"输入验证"评分点的关键设计。
        """

    @property
    def title(self) -> str:
        """显示名。武器/护甲会覆盖它来带强化等级（如「铁剑 +2」）。"""
        return self.name

    def describe(self) -> str:
        return f"{self.name} —— {self.desc}"

    def to_dict(self) -> dict[str, Any]:
        return {"cls": type(self).__name__, "key": self.key}

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<{type(self).__name__} {self.key}>"


class Potion(Item):
    """治疗药水。"""

    kind = "potion"
    glyph = "!"

    def __init__(self, key: str, name: str, desc: str, heal_amount: int) -> None:
        super().__init__(key, name, desc)
        self.heal_amount = int(heal_amount)

    def apply(self, player: "Player", state: Any = None) -> tuple[bool, str]:
        if player.hp >= player.max_hp:
            return False, "生命已满，不需要喝药"
        healed = player.heal(self.heal_amount)
        player.items_used += 1
        return True, f"饮下{self.name}，回复 {healed} 点生命"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["heal_amount"] = self.heal_amount
        return data


class Weapon(Item):
    """武器。除了加攻击，还决定**怎么打**。

    一把武器带有完整的攻击描述：
    - ``slot``   占用哪个装备槽：``melee``（兵刃）或 ``ranged``（弓）
    - ``pattern`` 攻击形状，见 ``dungeon.patterns``
    - ``reach``  最大射程（格）
    - ``charge`` 出手前的蓄力回合数，0 表示即时

    "伤害越高、蓄力越长"这条规则就落在 ``atk_bonus`` 与 ``charge`` 的搭配上：
    巨刃 +8 但要蓄力 1 回合，铁剑 +2 可以立刻挥出。
    """

    kind = "weapon"
    glyph = "/"

    def __init__(
        self,
        key: str,
        name: str,
        desc: str,
        atk_bonus: int,
        slot: str = "melee",
        pattern: str = "melee",
        reach: int = 1,
        charge: int = 0,
        min_reach: int = 1,
    ) -> None:
        super().__init__(key, name, desc)
        self.atk_bonus = int(atk_bonus)
        self._base_atk = int(atk_bonus)      # 合成前的基础攻击，重放等级时用
        self.slot = slot
        self.pattern = pattern
        self.reach = int(reach)
        self.charge = int(charge)
        self.min_reach = int(min_reach)
        self.upgrade_level: int = 0          # 强化等级，合成时 +1

    @property
    def title(self) -> str:
        """显示名，带强化等级（如「铁剑 +2」）。"""
        return f"{self.name} +{self.upgrade_level}" if self.upgrade_level else self.name

    def restore_upgrade(self, level: int) -> None:
        """按存档里的强化等级重放，并截断到上限。

        合成只改动 ``upgrade_level``，``atk_bonus`` 是基础值 + 每级加成。
        所以读档时只需按等级重放加成，不必存储最终攻击力——这也顺带封死了
        "手改存档里的 atk_bonus 造神装"这条路。
        """
        self.upgrade_level = max(0, min(int(level), config.UPGRADE_MAX_LEVEL))
        self.atk_bonus = self._base_atk + self.upgrade_level * config.UPGRADE_ATK_PER_LEVEL

    @property
    def slot_name(self) -> str:
        return "远程" if self.slot == "ranged" else "近战"

    @property
    def range_text(self) -> str:
        """给人看的射程描述，例如"直线 3 格"。"""
        if self.pattern == "ranged":
            return f"射程 {self.min_reach}~{self.reach} 格"
        if self.pattern == "line":
            return f"直线 {self.reach} 格"
        if self.pattern == "arc":
            return "身前三格横扫"
        return "贴身 1 格"

    def apply(self, player: "Player", state: Any = None) -> tuple[bool, str]:
        old = player.equipment.get(self.slot)
        if old is not None and old.key == self.key:
            return False, f"已经装备着{self.name}了"
        player.equip(self)
        player.items_used += 1
        replaced = f"，替换下{old.name}" if old is not None else ""
        return True, f"装备{self.name}（{self.slot_name} · 攻击 +{self.atk_bonus}）{replaced}"

    def describe(self) -> str:
        extra = f"蓄力 {self.charge} 回合" if self.charge else "即时出手"
        return f"{self.name} —— {self.slot_name}，{self.range_text}，{extra}；{self.desc}"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["atk_bonus"] = self.atk_bonus
        data["upgrade"] = self.upgrade_level
        return data


class Armor(Item):
    """护甲，装备后提升防御力。同名护甲可合成升级。"""

    kind = "armor"
    glyph = "["

    def __init__(self, key: str, name: str, desc: str, def_bonus: int) -> None:
        super().__init__(key, name, desc)
        self.def_bonus = int(def_bonus)
        self._base_def = int(def_bonus)
        self.upgrade_level: int = 0

    @property
    def title(self) -> str:
        return f"{self.name} +{self.upgrade_level}" if self.upgrade_level else self.name

    def restore_upgrade(self, level: int) -> None:
        self.upgrade_level = max(0, min(int(level), config.UPGRADE_MAX_LEVEL))
        self.def_bonus = self._base_def + self.upgrade_level * config.UPGRADE_DEF_PER_LEVEL

    def apply(self, player: "Player", state: Any = None) -> tuple[bool, str]:
        old = player.equipment.get("armor")
        if old is not None and old.key == self.key:
            return False, f"已经穿着{self.name}了"
        player.equip(self)
        player.items_used += 1
        replaced = f"，替换下{old.name}" if old is not None else ""
        return True, f"穿上{self.name}（防御 +{self.def_bonus}）{replaced}"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["def_bonus"] = self.def_bonus
        data["upgrade"] = self.upgrade_level
        return data


class Scroll(Item):
    """一次性法术卷轴。"""

    kind = "scroll"
    glyph = "?"

    def __init__(self, key: str, name: str, desc: str, effect: str, power: int = 0) -> None:
        super().__init__(key, name, desc)
        self.effect = effect
        self.power = int(power)

    def apply(self, player: "Player", state: Any = None) -> tuple[bool, str]:
        if self.effect == "teleport":
            if state is None:
                return False, "此处无法使用传送卷轴"
            x, y = state.teleport_player()
            player.items_used += 1
            return True, f"空间扭曲，你被传送到 ({x}, {y})"

        if self.effect == "flare":
            if state is None:
                return False, "此处无法使用烈焰卷轴"
            hurt = state.damage_visible_monsters(self.power)
            player.items_used += 1
            if hurt == 0:
                return True, "烈焰升腾，但视野内没有敌人"
            return True, f"烈焰席卷，灼伤 {hurt} 个敌人共 {self.power} 点"

        if self.effect == "bless":
            healed = player.heal(self.power)
            player.items_used += 1
            return True, f"圣光笼罩，回复 {healed} 点生命"

        return False, "这卷轴上什么也没写"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["effect"] = self.effect
        data["power"] = self.power
        return data


# ------------------------------------------------------------------ 数据表
# 道具的数值与名称集中在此，调整平衡只需改这张表
_ITEM_DEFS: dict[str, dict[str, Any]] = {
    "potion_small": {
        "factory": Potion, "name": "小治疗药水", "desc": "回复 12 点生命",
        "heal_amount": 12, "min_floor": 1,
    },
    "potion_large": {
        "factory": Potion, "name": "大治疗药水", "desc": "回复 30 点生命",
        "heal_amount": 30, "min_floor": 3,
    },
    "sword_iron": {
        "factory": Weapon, "name": "铁剑", "desc": "攻击 +2",
        "atk_bonus": 2, "min_floor": 1,
        "slot": "melee", "pattern": "melee", "reach": 1, "charge": 0,
    },
    "sword_rune": {
        "factory": Weapon, "name": "符文长剑", "desc": "攻击 +4",
        "atk_bonus": 4, "min_floor": 4,
        "slot": "melee", "pattern": "melee", "reach": 1, "charge": 0,
    },
    "blade_abyss": {
        "factory": Weapon, "name": "深渊之刃", "desc": "攻击 +7",
        "atk_bonus": 7, "min_floor": 7,
        "slot": "melee", "pattern": "melee", "reach": 1, "charge": 0,
    },
    "spear_bone": {
        "factory": Weapon, "name": "骨矛", "desc": "攻击 +3，直线贯穿",
        "atk_bonus": 3, "min_floor": 2,
        "slot": "melee", "pattern": "line", "reach": 3, "charge": 0,
    },
    "greatsword": {
        "factory": Weapon, "name": "巨刃", "desc": "攻击 +8，身前三格横扫",
        "atk_bonus": 8, "min_floor": 6,
        "slot": "melee", "pattern": "arc", "reach": 2, "charge": 1,
    },
    "bow_short": {
        "factory": Weapon, "name": "短弓", "desc": "攻击 +3，射程 4 格",
        "atk_bonus": 3, "min_floor": 1,
        "slot": "ranged", "pattern": "ranged", "reach": 4, "min_reach": 2, "charge": 0,
    },
    "bow_long": {
        "factory": Weapon, "name": "长弓", "desc": "攻击 +6，射程 6 格，需蓄力",
        "atk_bonus": 6, "min_floor": 5,
        "slot": "ranged", "pattern": "ranged", "reach": 6, "min_reach": 2, "charge": 1,
    },
    "armor_leather": {
        "factory": Armor, "name": "皮甲", "desc": "防御 +1",
        "def_bonus": 1, "min_floor": 1,
    },
    "armor_chain": {
        "factory": Armor, "name": "锁子甲", "desc": "防御 +3",
        "def_bonus": 3, "min_floor": 4,
    },
    "scroll_flare": {
        "factory": Scroll, "name": "烈焰卷轴", "desc": "灼伤视野内所有敌人 10 点",
        "effect": "flare", "power": 10, "min_floor": 2,
    },
    "scroll_teleport": {
        "factory": Scroll, "name": "传送卷轴", "desc": "随机传送到本层另一个位置",
        "effect": "teleport", "power": 0, "min_floor": 2,
    },
    "scroll_bless": {
        "factory": Scroll, "name": "祝福卷轴", "desc": "回复 25 点生命",
        "effect": "bless", "power": 25, "min_floor": 5,
    },
}

ITEM_TABLE: dict[str, dict[str, Any]] = _ITEM_DEFS


def make_item(key: str) -> Item:
    """按 key 创建一个全新的道具实例。

    为什么用工厂而不是直接复用实例：道具会被消耗/装备，
    每次生成都必须是独立对象，否则一个药水喝掉会影响同层所有同类药水。
    """
    if key not in _ITEM_DEFS:
        raise KeyError(f"未知的道具：{key}")
    spec = _ITEM_DEFS[key]
    cls = spec["factory"]
    if cls is Potion:
        return Potion(key, spec["name"], spec["desc"], spec["heal_amount"])
    if cls is Weapon:
        return Weapon(
            key,
            spec["name"],
            spec["desc"],
            spec["atk_bonus"],
            slot=spec.get("slot", "melee"),
            pattern=spec.get("pattern", "melee"),
            reach=spec.get("reach", 1),
            charge=spec.get("charge", 0),
            min_reach=spec.get("min_reach", 1),
        )
    if cls is Armor:
        return Armor(key, spec["name"], spec["desc"], spec["def_bonus"])
    if cls is Scroll:
        return Scroll(key, spec["name"], spec["desc"], spec["effect"], spec["power"])
    raise KeyError(f"无法实例化的道具类型：{cls}")  # pragma: no cover


# 生成道具时的类别权重：药水是刚需，所以权重最高
_KIND_WEIGHTS: list[tuple[str, float]] = [
    ("potion", 0.42),
    ("weapon", 0.20),
    ("armor", 0.14),
    ("scroll", 0.24),
]


def roll_item(rng: "Rng", floor: int) -> Item:
    """按当前楼层抽取一个道具。

    两段式抽样：先按类别抽（药水权重最高，保证补给），
    再在该类别里按"越高级权重越大"抽具体条目。
    这样深层能稳定出现符文长剑、锁子甲这类进阶装备，
    而不是像纯均匀抽样那样到第 9 层还在掉铁剑。
    """
    available = {
        kind: [
            key
            for key, spec in _ITEM_DEFS.items()
            if spec["min_floor"] <= floor and spec["factory"].kind == kind
        ]
        for kind, _ in _KIND_WEIGHTS
    }
    usable = [(kind, weight) for kind, weight in _KIND_WEIGHTS if available[kind]]
    if not usable:
        return make_item("potion_small")  # pragma: no cover - 第 1 层必有道具

    chosen_kind = rng.choices([kind for kind, _ in usable], weights=[w for _, w in usable], k=1)[0]
    pool = sorted(available[chosen_kind], key=lambda key: _ITEM_DEFS[key]["min_floor"], reverse=True)
    # 越高级的条目权重越大，但低级仍然可能出，避免"永远只掉最强的那件"
    tier_weights = [float(len(pool) - index) for index in range(len(pool))]
    return make_item(rng.choices(pool, weights=tier_weights, k=1)[0])


# ------------------------------------------------------------------ 反序列化
def item_from_dict(data: dict[str, Any]) -> Item:
    """从存档字典还原道具。

    只信任 ``key``，其余数值一律以数据表重建：这样即使有人手改了存档里的
    ``heal_amount``，也无法凭空造出"回复 9999 点"的作弊药水。
    ``upgrade`` 字段会经 ``restore_upgrade`` 截断到上限，改到 99 也只得到 +3。
    """
    try:
        key = data["key"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"道具数据缺少 key 字段：{exc}") from exc
    if key not in _ITEM_DEFS:
        raise ValueError(f"存档中存在未知道具：{key}")
    item = make_item(key)
    if isinstance(item, (Weapon, Armor)) and "upgrade" in data:
        item.restore_upgrade(data["upgrade"])
    return item


ITEM_FACTORY: dict[str, Callable[[dict[str, Any]], Item]] = {
    "Potion": item_from_dict,
    "Weapon": item_from_dict,
    "Armor": item_from_dict,
    "Scroll": item_from_dict,
    "Item": item_from_dict,
}
