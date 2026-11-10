"""战斗结算与实体行为的单元测试。

战斗公式是纯函数，用"脚本化的假随机源"就能写出百分之百确定的用例，
不依赖任何全局随机状态。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon import config
from dungeon.combat import base_damage, resolve_attack
from dungeon.entity import Entity
from dungeon.player import Player


class ScriptedRng:
    """按预设脚本依次返回随机值的假随机源。"""

    def __init__(self, values: list[bool]) -> None:
        self.values = list(values)

    def chance(self, probability: float) -> bool:
        if not self.values:
            return False
        return self.values.pop(0)


class DummyEntity(Entity):
    """可实例化的最小实体，用于测试基类逻辑。"""

    def to_dict(self) -> dict:
        return self._base_dict()

    @classmethod
    def from_dict(cls, data: dict) -> "DummyEntity":
        entity = cls(
            data["name"], data["glyph"], data["x"], data["y"],
            data["max_hp"], data["atk"], data["defense"],
        )
        entity.hp = data["hp"]
        return entity


class TestDamageFormula(unittest.TestCase):
    """伤害公式测试。"""

    def test_damage_floor_is_one(self) -> None:
        """高防打低攻时，伤害必须保底为 1 点，不能出现 0 或负数。"""
        self.assertEqual(base_damage(3, 99), config.MIN_DAMAGE)
        self.assertEqual(base_damage(0, 10), config.MIN_DAMAGE)
        self.assertEqual(base_damage(10, 10), config.MIN_DAMAGE)

    def test_normal_damage(self) -> None:
        self.assertEqual(base_damage(10, 3), 7)

    def test_negative_parameters_rejected(self) -> None:
        """攻击力/防御力为负属于非法输入，必须抛异常而不是算出怪结果。"""
        with self.assertRaises(ValueError):
            base_damage(-1, 5)
        with self.assertRaises(ValueError):
            base_damage(5, -1)

    def test_miss_returns_zero_damage(self) -> None:
        """落空时伤害为 0 且标记 hit=False。"""
        rng = ScriptedRng([True])          # 第一次判定即落空
        result = resolve_attack(20, 0, rng)  # type: ignore[arg-type]
        self.assertFalse(result.hit)
        self.assertEqual(result.damage, 0)

    def test_critical_hit_multiplies_damage(self) -> None:
        """命中且暴击时，伤害 = 基础伤害 × 暴击倍率（四舍五入）。"""
        rng = ScriptedRng([False, True])   # 未落空、暴击
        result = resolve_attack(20, 10, rng)  # type: ignore[arg-type]
        self.assertTrue(result.hit and result.crit)
        expected = round(base_damage(20, 10) * config.CRIT_MULTIPLIER)
        self.assertEqual(result.damage, expected)


class TestEntityBehavior(unittest.TestCase):
    """实体血量与成长测试。"""

    def test_take_damage_and_death(self) -> None:
        """扣血到 0 时血量钳制在 0，并标记为死亡。"""
        entity = DummyEntity("测试", "x", 0, 0, hp=10, atk=1, defense=0)
        actual = entity.take_damage(4)
        self.assertEqual(actual, 4)
        self.assertEqual(entity.hp, 6)
        self.assertTrue(entity.alive)

        entity.take_damage(999)
        self.assertEqual(entity.hp, 0)
        self.assertFalse(entity.alive)

    def test_heal_capped_at_max_hp(self) -> None:
        """满血喝药不应溢出，实际回复量为 0。"""
        entity = DummyEntity("测试", "x", 0, 0, hp=10, atk=1, defense=0)
        self.assertEqual(entity.heal(50), 0)
        self.assertEqual(entity.hp, 10)

        entity.take_damage(4)
        self.assertEqual(entity.heal(100), 4)
        self.assertEqual(entity.hp, 10)

    def test_negative_amount_rejected(self) -> None:
        """负数伤害/治疗属于非法参数，必须抛 ValueError。"""
        entity = DummyEntity("测试", "x", 0, 0, hp=10, atk=1, defense=0)
        with self.assertRaises(ValueError):
            entity.take_damage(-5)
        with self.assertRaises(ValueError):
            entity.heal(-5)

    def test_multi_level_up(self) -> None:
        """一次给大量经验应该连续升级，且血量回满、等级不越界。"""
        player = Player.create_new()
        messages = player.gain_exp(1_000_000)
        self.assertGreater(player.level, 10)
        self.assertEqual(player.hp, player.max_hp)
        self.assertGreater(len(messages), 5)
        # 经验必须小于下一级需求，否则说明还有余量没升级
        self.assertLess(player.exp, player.exp_to_next)

    def test_equipment_affects_stats(self) -> None:
        """装备武器护甲后，总攻击与总防御应等于基础值加加成。"""
        from dungeon.item import make_item

        player = Player.create_new()
        base_atk, base_def = player.atk, player.defense
        player.equip(make_item("sword_iron"))
        player.equip(make_item("armor_leather"))
        self.assertEqual(player.total_atk(), base_atk + 2)
        self.assertEqual(player.total_def(), base_def + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
