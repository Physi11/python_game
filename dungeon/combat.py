"""战斗结算模块。

本模块只包含**纯函数**，不修改任何对象状态，因此可以用固定种子
写出完全确定的单元测试。真正"扣血"的动作由 ``GameState`` 负责。

伤害公式
--------
``基础伤害 = max(MIN_DAMAGE, 攻击力 - 防御力)``
先判定落空，再判定暴击；暴击时伤害乘以倍率并四舍五入。
设置 1 点伤害下限，是为了避免"高防怪打不动"造成的死循环。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config
from .entity import Entity
from .rng import Rng


@dataclass(frozen=True)
class AttackResult:
    """一次攻击的结算结果。"""

    hit: bool          # 是否命中
    crit: bool         # 是否暴击
    damage: int        # 实际伤害（落空时为 0）

    @property
    def summary(self) -> str:
        """给日志用的简短描述。"""
        if not self.hit:
            return "落空"
        return f"暴击 {self.damage}" if self.crit else f"{self.damage}"


def base_damage(atk: int, defense: int) -> int:
    """计算未考虑暴击的基础伤害，保证至少为 ``MIN_DAMAGE``。"""
    if atk < 0 or defense < 0:
        raise ValueError("攻击力与防御力都不能为负")
    return max(config.MIN_DAMAGE, atk - defense)


def resolve_attack(
    atk: int,
    defense: int,
    rng: Rng,
    crit_rate: float = config.CRIT_RATE,
    crit_multiplier: float = config.CRIT_MULTIPLIER,
    miss_rate: float = config.MISS_RATE,
) -> AttackResult:
    """完整结算一次攻击：落空判定 → 伤害计算 → 暴击判定。"""
    if rng.chance(miss_rate):
        return AttackResult(hit=False, crit=False, damage=0)
    damage = base_damage(atk, defense)
    crit = rng.chance(crit_rate)
    if crit:
        damage = max(config.MIN_DAMAGE, round(damage * crit_multiplier))
    return AttackResult(hit=True, crit=crit, damage=damage)


def strike(attacker: Entity, defender: Entity, rng: Rng) -> AttackResult:
    """执行一次攻击并直接扣血，返回结算结果。"""
    result = resolve_attack(attacker.total_atk(), defender.total_def(), rng)
    if result.hit:
        defender.take_damage(result.damage)
    return result
