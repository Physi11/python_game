"""装备系统的单元测试：槽位映射与"只许更强"替换规则。

这两条都是实际踩过的 bug：
1. ``equip()`` 把武器分类 ``melee`` 当成了装备字典的键，导致近战武器
   写进 ``equipment["melee"]``，右侧面板与战斗都读 ``weapon``，表现为
   "换了剑却没反应"；
2. 换装没有门槛，一把白板铁剑就能把 +3 的剑顶掉。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon.item import make_item
from dungeon.player import Player


def fresh_player() -> Player:
    """开一个空装备的新档，避免初始铁剑干扰断言。"""
    player = Player(name="测试", hp=30)
    player.equipment = {"weapon": None, "ranged": None, "armor": None}
    return player


class TestEquipSlot(unittest.TestCase):
    """武器分类与装备槽必须映射正确。"""

    def test_melee_weapon_goes_to_weapon_slot(self) -> None:
        player = fresh_player()
        player.inventory.append(make_item("sword_rune"))
        ok, _ = player.use_item(0)
        self.assertTrue(ok)
        self.assertEqual(player.equipment["weapon"].key, "sword_rune")
        # 关键回归：绝不能凭空多出一个 "melee" 键
        self.assertNotIn("melee", player.equipment)
        self.assertEqual(set(player.equipment), {"weapon", "ranged", "armor"})

    def test_ranged_weapon_goes_to_ranged_slot(self) -> None:
        player = fresh_player()
        player.inventory.append(make_item("bow_short"))
        player.use_item(0)
        self.assertEqual(player.equipment["ranged"].key, "bow_short")
        self.assertIsNone(player.equipment["weapon"])

    def test_panel_and_combat_read_the_same_slot(self) -> None:
        """面板读 ``equipment["weapon"]``，战斗也读它——两者必须是同一把。"""
        player = fresh_player()
        player.equipment["weapon"] = make_item("sword_iron")     # atk +2
        player.inventory.append(make_item("sword_rune"))          # atk +5
        player.use_item(0)
        equipped = player.equipment["weapon"]
        self.assertEqual(equipped.key, "sword_rune")
        self.assertEqual(player.attack_power(equipped), player.atk + 5)
        self.assertEqual(player.total_atk(), player.atk + 5)


class TestUpgradeGate(unittest.TestCase):
    """只允许更强的武器替换，同级与更弱一律拒绝。"""

    def test_stronger_weapon_replaces(self) -> None:
        player = fresh_player()
        player.equipment["weapon"] = make_item("sword_iron")      # +2
        player.inventory.append(make_item("sword_rune"))          # +5
        ok, _ = player.use_item(0)
        self.assertTrue(ok)
        self.assertEqual(player.equipment["weapon"].key, "sword_rune")

    def test_weaker_weapon_is_rejected(self) -> None:
        player = fresh_player()
        player.equipment["weapon"] = make_item("sword_rune")      # +5
        player.inventory.append(make_item("sword_iron"))          # +2
        ok, msg = player.use_item(0)
        self.assertFalse(ok)
        self.assertIn("保留现有武器", msg)
        self.assertEqual(player.equipment["weapon"].key, "sword_rune")
        # 被拒绝的道具要留在背包里，不能凭空消失
        self.assertEqual(len(player.inventory), 1)

    def test_same_power_weapon_is_rejected(self) -> None:
        player = fresh_player()
        player.equipment["weapon"] = make_item("sword_iron")
        other = make_item("sword_iron")
        # 用另一把"同名但不同对象"模拟：先改名避开同名合并的逻辑
        other.key = "sword_iron_clone"
        player.inventory.append(other)
        ok, _ = player.use_item(0)
        self.assertFalse(ok)

    def test_equal_attack_but_longer_reach_wins(self) -> None:
        """攻击相同时比射程：骨矛（3 格）应当能替换同攻击力的短兵器。"""
        player = fresh_player()
        iron = make_item("sword_iron")
        iron.atk_bonus = 3                    # 人为拉到与骨矛同攻击
        player.equipment["weapon"] = iron
        spear = make_item("spear_bone")        # atk 3，reach 3
        self.assertTrue(spear.is_stronger_than(iron))
        player.inventory.append(spear)
        ok, _ = player.use_item(0)
        self.assertTrue(ok)
        self.assertEqual(player.equipment["weapon"].key, "spear_bone")

    def test_upgraded_weapon_cannot_be_replaced_by_base_version(self) -> None:
        """+3 的铁剑（+5）不该被白板符文长剑（+5）顶掉：攻击相同再看别的。"""
        player = fresh_player()
        upgraded = make_item("sword_iron")
        upgraded.restore_upgrade(3)           # atk 2+3=5
        player.equipment["weapon"] = upgraded
        newcomer = make_item("sword_rune")     # atk 5，reach 1，charge 0
        # 攻击与蓄力都相同，射程也相同 → 不算更强
        self.assertFalse(newcomer.is_stronger_than(upgraded))

    def test_armor_downgrade_is_rejected(self) -> None:
        player = fresh_player()
        player.equipment["armor"] = make_item("armor_chain")      # def +3
        player.inventory.append(make_item("armor_leather"))       # def +1
        ok, msg = player.use_item(0)
        self.assertFalse(ok)
        self.assertIn("保留现有护甲", msg)
        self.assertEqual(player.equipment["armor"].key, "armor_chain")

    def test_armor_upgrade_is_allowed(self) -> None:
        player = fresh_player()
        player.equipment["armor"] = make_item("armor_leather")
        player.inventory.append(make_item("armor_chain"))
        ok, _ = player.use_item(0)
        self.assertTrue(ok)
        self.assertEqual(player.equipment["armor"].key, "armor_chain")

    def test_weapon_table_is_monotonic_in_floor(self) -> None:
        """越深层的近战武器必须越强，否则"只许更强"会把好武器锁死。"""
        melee = [
            ("sword_iron", 1),
            ("spear_bone", 2),
            ("sword_rune", 4),
            ("blade_abyss", 7),
            ("greatsword", 8),
        ]
        powers = [(make_item(key).atk_bonus, floor) for key, floor in melee]
        for (weaker_atk, weaker_floor), (stronger_atk, stronger_floor) in zip(
            powers, powers[1:]
        ):
            self.assertLess(weaker_floor, stronger_floor)
            self.assertLess(
                weaker_atk,
                stronger_atk,
                f"{weaker_floor} 层的武器攻击 {weaker_atk} 不低于 "
                f"{stronger_floor} 层的 {stronger_atk}",
            )


if __name__ == "__main__":
    unittest.main()
