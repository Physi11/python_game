"""怪物模块。

设计上把"数值原型"与"运行时行为"分开：
``MonsterProto`` 只描述一个物种的静态数值（生命、攻击、经验、AI 类型），
``Monster`` 才是地图上真实存在的个体，持有当前血量与坐标。

好处是调整平衡只需要改 ``MONSTER_TABLE`` 一张表，
不用碰任何逻辑代码；新增怪物也只是往表里加一行。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import config
from .entity import Entity
from .rng import Rng


@dataclass(frozen=True)
class MonsterProto:
    """怪物物种的静态数值。

    ``pattern`` / ``reach`` / ``charge`` 三项描述"它怎么打、打多远、打之前要举多久"。
    全局遵守一条规则：**伤害越高，蓄力回合越长**（同档可以并列，见
    ``tests/test_patterns.py::test_charge_grows_with_damage``）。
    """

    kind: str            # 内部标识
    name: str            # 显示名
    glyph: str           # 地图字符
    hp: int
    atk: int
    defense: int
    exp: int             # 击杀奖励经验
    gold: int            # 击杀掉落金币
    ai: str = "chase"    # chase 追击 / wander 游荡 / guard 守卫
    aggro: int = 6       # 察觉半径
    min_floor: int = 1   # 从第几层开始出现
    weight: float = 1.0  # 加权抽取权重
    is_boss: bool = False
    # ---- 攻击形态 ----
    pattern: str = "melee"   # melee / line / arc / ranged
    reach: int = 1           # 最大射程（格）
    min_reach: int = 1       # 最小射程，远程兵种用来避免贴脸射击
    charge: int = 1          # 起手到命中的回合数


# ------------------------------------------------------------------ 物种表
# 蓄力档位按攻击力分：<=7 →2，8~11 →3，>=12 →4
# 下限取 2 而不是 1：蓄力 1 回合的敌人会逼玩家每回合都在躲，永远轮不到出手
MONSTER_TABLE: list[MonsterProto] = [
    MonsterProto("slime", "史莱姆", "s", hp=8, atk=3, defense=0, exp=8, gold=3,
                 ai="wander", aggro=3, min_floor=1, weight=2.4,
                 pattern="melee", reach=1, charge=2),
    MonsterProto("rat", "巨鼠", "r", hp=6, atk=4, defense=0, exp=7, gold=2,
                 ai="chase", aggro=5, min_floor=1, weight=2.4,
                 pattern="melee", reach=1, charge=2),
    MonsterProto("goblin", "哥布林", "g", hp=12, atk=5, defense=1, exp=14, gold=6,
                 ai="chase", aggro=6, min_floor=1, weight=2.0,
                 pattern="melee", reach=1, charge=2),
    MonsterProto("bat", "吸血蝙蝠", "b", hp=9, atk=6, defense=0, exp=12, gold=4,
                 ai="chase", aggro=8, min_floor=2, weight=1.4,
                 pattern="melee", reach=2, charge=2),
    # 弓兵：远程点名，射程远但伤害低，蓄力短
    MonsterProto("archer", "弓兵", "A", hp=12, atk=6, defense=1, exp=20, gold=9,
                 ai="chase", aggro=7, min_floor=2, weight=1.8,
                 pattern="ranged", reach=5, min_reach=2, charge=2),
    MonsterProto("skeleton", "骷髅兵", "k", hp=18, atk=7, defense=3, exp=22, gold=10,
                 ai="chase", aggro=6, min_floor=3, weight=1.4,
                 pattern="melee", reach=1, charge=2),
    # 长矛兵：又长又窄，一条直线贯穿
    MonsterProto("spearman", "长矛兵", "P", hp=16, atk=9, defense=2, exp=26, gold=12,
                 ai="chase", aggro=6, min_floor=3, weight=1.6,
                 pattern="line", reach=3, charge=3),
    MonsterProto("gargoyle", "石像鬼", "G", hp=28, atk=9, defense=6, exp=34, gold=16,
                 ai="guard", aggro=5, min_floor=6, weight=1.0,
                 pattern="melee", reach=1, charge=3),
    # 大刀兵：范围最大、伤害最高，代价是蓄力最久
    MonsterProto("swordsman", "大刀兵", "W", hp=24, atk=14, defense=3, exp=38, gold=18,
                 ai="chase", aggro=6, min_floor=4, weight=1.2,
                 pattern="arc", reach=2, charge=4),
    MonsterProto("demon_lord", "深渊领主", "L", hp=340, atk=23, defense=6, exp=200, gold=200,
                 ai="chase", aggro=12, min_floor=config.BOSS_FLOOR, weight=0.0, is_boss=True,
                 pattern="arc", reach=2, charge=4),
]

MONSTER_BY_KIND: dict[str, MonsterProto] = {proto.kind: proto for proto in MONSTER_TABLE}


class Monster(Entity):
    """地图上的一只怪物。"""

    def __init__(self, proto: MonsterProto, x: int, y: int, floor: int = 1) -> None:
        # BOSS 使用固定数值，不随层数缩放：它就是第 10 层的最终考验
        if proto.is_boss:
            hp, atk = proto.hp, proto.atk
        else:
            hp = max(1, round(proto.hp * (1 + config.MONSTER_HP_SCALE * (floor - 1))))
            atk = max(1, round(proto.atk * (1 + config.MONSTER_ATK_SCALE * (floor - 1))))
        super().__init__(proto.name, proto.glyph, x, y, hp, atk, proto.defense)
        self.kind: str = proto.kind
        self.exp_reward: int = proto.exp
        self.gold_reward: int = proto.gold
        self.ai: str = proto.ai
        self.aggro: int = proto.aggro
        self.is_boss: bool = proto.is_boss
        self.floor: int = floor

        # ---- 攻击形态 ----
        self.pattern: str = proto.pattern
        self.reach: int = proto.reach
        self.min_reach: int = proto.min_reach
        self.charge_turns: int = max(1, proto.charge)

        # ---- 蓄力运行时状态 ----
        self.charge_left: int = 0                    # 还要几回合出手，0 表示没在蓄力
        self.telegraph: set[tuple[int, int]] = set() # 已经锁定、即将落下的打击区域

    # ------------------------------------------------------------ 查询
    @property
    def is_charging(self) -> bool:
        return self.charge_left > 0

    @property
    def range_text(self) -> str:
        if self.pattern == "ranged":
            return f"射程 {self.min_reach}~{self.reach} 格"
        if self.pattern == "line":
            return f"直线 {self.reach} 格"
        if self.pattern == "arc":
            return "身前横扫"
        return "贴身 1 格"

    def begin_charge(self, tiles: frozenset[tuple[int, int]]) -> None:
        """锁定一片区域并进入蓄力。

        区域一旦锁定就不再跟随玩家移动——这是"看红框、走出去"能奏效的前提。
        """
        self.telegraph = set(tiles)
        self.charge_left = self.charge_turns

    def cancel_charge(self) -> None:
        self.charge_left = 0
        self.telegraph = set()

    # ------------------------------------------------------------ AI
    def _greedy_step(self, dungeon: Any, player: "Entity") -> tuple[int, int] | None:
        """贪心向玩家靠近一步，返回目标坐标；无路可走时返回 None。"""
        dx = player.x - self.x
        dy = player.y - self.y
        # 先处理位移更大的轴，走位更自然
        axes = [(dx, 0), (0, dy)] if abs(dx) >= abs(dy) else [(0, dy), (dx, 0)]
        for mx, my in axes:
            if mx == 0 and my == 0:
                continue
            step_x = self.x + (1 if mx > 0 else -1 if mx < 0 else 0)
            step_y = self.y + (1 if my > 0 else -1 if my < 0 else 0)
            if dungeon.is_walkable(step_x, step_y):
                return step_x, step_y
        return None

    def wander_step(self, dungeon: Any, rng: Rng) -> tuple[int, int] | None:
        """游荡型怪物的随机一步。"""
        options = [
            (self.x + dx, self.y + dy)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if dungeon.is_walkable(self.x + dx, self.y + dy)
        ]
        return rng.choice(options) if options else None

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict[str, Any]:
        data = self._base_dict()
        data.update(
            {
                "kind": self.kind,
                "floor": self.floor,
                "charge_left": self.charge_left,
                "telegraph": [list(cell) for cell in sorted(self.telegraph)],
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Monster":
        kind = data.get("kind")
        if kind not in MONSTER_BY_KIND:
            raise ValueError(f"未知的怪物种类：{kind}")
        monster = cls(
            MONSTER_BY_KIND[kind],
            int(data["x"]),
            int(data["y"]),
            int(data.get("floor", 1)),
        )
        monster.hp = int(data["hp"])
        monster.max_hp = int(data.get("max_hp", monster.max_hp))
        monster.alive = monster.hp > 0
        # 旧存档没有这两个字段，读回来就是"没在蓄力"，行为可预期
        monster.charge_left = int(data.get("charge_left", 0))
        monster.telegraph = {
            (int(cell[0]), int(cell[1])) for cell in data.get("telegraph", [])
        }
        return monster


def roll_monster(rng: Rng, floor: int) -> MonsterProto:
    """按当前楼层加权抽取一个怪物物种。"""
    pool = [p for p in MONSTER_TABLE if p.min_floor <= floor and not p.is_boss]
    if not pool:  # pragma: no cover - 第 1 层必然有可用怪物
        pool = [MONSTER_TABLE[0]]
    weights = [p.weight for p in pool]
    return rng.choices(pool, weights=weights, k=1)[0]
