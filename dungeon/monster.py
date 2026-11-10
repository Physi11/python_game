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
    """怪物物种的静态数值。"""

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


# ------------------------------------------------------------------ 物种表
MONSTER_TABLE: list[MonsterProto] = [
    MonsterProto("slime", "史莱姆", "s", hp=8, atk=3, defense=0, exp=8, gold=3,
                 ai="wander", aggro=3, min_floor=1, weight=3.0),
    MonsterProto("rat", "巨鼠", "r", hp=6, atk=4, defense=0, exp=7, gold=2,
                 ai="chase", aggro=5, min_floor=1, weight=3.0),
    MonsterProto("goblin", "哥布林", "g", hp=12, atk=5, defense=1, exp=14, gold=6,
                 ai="chase", aggro=6, min_floor=1, weight=2.4),
    MonsterProto("bat", "吸血蝙蝠", "b", hp=9, atk=6, defense=0, exp=12, gold=4,
                 ai="chase", aggro=8, min_floor=2, weight=2.0),
    MonsterProto("skeleton", "骷髅兵", "k", hp=18, atk=7, defense=3, exp=22, gold=10,
                 ai="chase", aggro=6, min_floor=3, weight=1.8),
    MonsterProto("gargoyle", "石像鬼", "G", hp=28, atk=9, defense=6, exp=34, gold=16,
                 ai="guard", aggro=5, min_floor=6, weight=1.2),
    MonsterProto("demon_lord", "深渊领主", "L", hp=340, atk=23, defense=6, exp=200, gold=200,
                 ai="chase", aggro=12, min_floor=config.BOSS_FLOOR, weight=0.0, is_boss=True),
]

MONSTER_BY_KIND: dict[str, MonsterProto] = {proto.kind: proto for proto in MONSTER_TABLE}


@dataclass(frozen=True)
class MonsterAction:
    """怪物一次决策的结果。"""

    kind: str                        # attack / move / wait
    target: tuple[int, int] | None = None


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

    # ------------------------------------------------------------ AI
    def decide(self, dungeon: Any, player: "Entity", rng: Rng) -> MonsterAction:
        """根据与玩家的相对位置决定本回合行动。

        规则（简单但有效）：
        1. 相邻 → 直接攻击；
        2. 守卫型 → 永不移动；
        3. 在察觉半径内 → 贪心靠近（先走差值大的那个轴，被墙挡住再换另一个轴）；
        4. 否则游荡型有 35% 概率随机走一步，其余原地待命。

        随机源由外部注入，保证同一存档读回后怪物行为完全一致。
        """
        if self.is_adjacent(player):
            return MonsterAction("attack")

        if self.ai == "guard":
            return MonsterAction("wait")

        if self.distance_to(player) <= self.aggro:
            step = self._greedy_step(dungeon, player)
            if step is not None:
                return MonsterAction("move", step)

        if self.ai == "wander" and rng.chance(0.35):
            options = [
                (self.x + dx, self.y + dy)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if dungeon.is_walkable(self.x + dx, self.y + dy)
            ]
            if options:
                return MonsterAction("move", rng.choice(options))
        return MonsterAction("wait")

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

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict[str, Any]:
        data = self._base_dict()
        data.update({"kind": self.kind, "floor": self.floor})
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
        return monster


def roll_monster(rng: Rng, floor: int) -> MonsterProto:
    """按当前楼层加权抽取一个怪物物种。"""
    pool = [p for p in MONSTER_TABLE if p.min_floor <= floor and not p.is_boss]
    if not pool:  # pragma: no cover - 第 1 层必然有可用怪物
        pool = [MONSTER_TABLE[0]]
    weights = [p.weight for p in pool]
    return rng.choices(pool, weights=weights, k=1)[0]
