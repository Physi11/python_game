"""同名装备合成的单元测试。

覆盖合成的触发条件、升级上限、满包仍可合成、存档往返与伪造等级截断。
全部不依赖 tkinter，用 ``Player`` + ``make_item`` 直接驱动。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon import config
from dungeon.item import item_from_dict, make_item
from dungeon.player import Player


def fresh_player() -> Player:
    """开一个不带初始武器的新档，避免初始铁剑干扰断言。"""
    player = Player(name="测试", hp=30)
    player.equipment["weapon"] = None
    player.equipment["ranged"] = None
    player.equipment["armor"] = None
    return player


class TestCraftTrigger(unittest.TestCase):
    """合成只在"同名装备"且"未满级"时触发。"""

    def test_same_weapon_merges_into_equipped(self) -> None:
        player = fresh_player()
        player.equipment["weapon"] = make_item("sword_iron")
        ok, msg = player.pick_up(make_item("sword_iron"))
        self.assertTrue(ok)
        self.assertIn("合成升级", msg)
        weapon = player.equipment["weapon"]
        self.assertEqual(weapon.upgrade_level, 1)
        self.assertEqual(weapon.atk_bonus, 3)   # 基础 2 + 1 级加成

    def test_different_weapon_does_not_merge(self) -> None:
        player = fresh_player()
        player.equipment["weapon"] = make_item("sword_iron")
        ok, msg = player.pick_up(make_item("spear_bone"))
        self.assertTrue(ok)
        self.assertIn("拾取", msg)              # 不是合成
        self.assertEqual(player.equipment["weapon"].upgrade_level, 0)
        self.assertEqual(len(player.inventory), 1)

    def test_potion_does_not_merge(self) -> None:
        player = fresh_player()
        before = len(player.inventory)
        player.pick_up(make_item("potion_small"))
        player.pick_up(make_item("potion_small"))
        # 药水是消耗品，各占一格，不合成
        self.assertEqual(len(player.inventory), before + 2)

    def test_armor_merges(self) -> None:
        player = fresh_player()
        player.equipment["armor"] = make_item("armor_leather")
        player.pick_up(make_item("armor_leather"))
        self.assertEqual(player.equipment["armor"].upgrade_level, 1)
        self.assertEqual(player.equipment["armor"].def_bonus, 2)

    def test_ranged_weapon_merges_into_ranged_slot(self) -> None:
        player = fresh_player()
        player.equipment["ranged"] = make_item("bow_short")
        player.pick_up(make_item("bow_short"))
        self.assertEqual(player.equipment["ranged"].upgrade_level, 1)
        # 近战槽不受影响
        self.assertIsNone(player.equipment["weapon"])


class TestCraftCap(unittest.TestCase):
    """升级有上限，满级后不再合成。"""

    def test_stops_at_max_level(self) -> None:
        player = fresh_player()
        player.equipment["weapon"] = make_item("sword_iron")
        for _ in range(config.UPGRADE_MAX_LEVEL):
            player.pick_up(make_item("sword_iron"))
        self.assertEqual(
            player.equipment["weapon"].upgrade_level, config.UPGRADE_MAX_LEVEL
        )
        expected_atk = 2 + config.UPGRADE_MAX_LEVEL * config.UPGRADE_ATK_PER_LEVEL
        self.assertEqual(player.equipment["weapon"].atk_bonus, expected_atk)
        # 满级后再捡同款，落入背包而不是继续合成
        ok, msg = player.pick_up(make_item("sword_iron"))
        self.assertTrue(ok)
        self.assertIn("拾取", msg)
        self.assertEqual(player.equipment["weapon"].upgrade_level, config.UPGRADE_MAX_LEVEL)
        self.assertEqual(len(player.inventory), 1)


class TestCraftFullInventory(unittest.TestCase):
    """背包满时仍能合成，不会因为容量检查而卡住。"""

    def test_merge_when_inventory_full(self) -> None:
        player = fresh_player()
        player.equipment["weapon"] = None
        for _ in range(config.INVENTORY_CAPACITY):
            player.inventory.append(make_item("potion_small"))
        # 背包里放一把 +1 的铁剑
        sword = make_item("sword_iron")
        sword.restore_upgrade(1)
        player.inventory.append(sword)

        ok, msg = player.pick_up(make_item("sword_iron"))
        self.assertTrue(ok)
        self.assertIn("合成升级", msg)
        # 合成发生在背包容量检查之前，所以仍成功
        self.assertEqual(player.inventory[-1].upgrade_level, 2)


class TestCraftSerialization(unittest.TestCase):
    """强化等级能正确往返存档，且伪造等级被截断。"""

    def test_roundtrip_preserves_upgrade(self) -> None:
        import json

        player = fresh_player()
        player.equipment["weapon"] = make_item("sword_iron")
        player.pick_up(make_item("sword_iron"))
        player.pick_up(make_item("sword_iron"))   # +2

        clone = Player.from_dict(json.loads(json.dumps(player.to_dict())))
        self.assertEqual(clone.equipment["weapon"].upgrade_level, 2)
        self.assertEqual(clone.equipment["weapon"].atk_bonus, 4)

    def test_forged_level_is_clamped(self) -> None:
        item = item_from_dict({"key": "sword_iron", "upgrade": 99})
        self.assertEqual(item.upgrade_level, config.UPGRADE_MAX_LEVEL)
        self.assertEqual(
            item.atk_bonus, 2 + config.UPGRADE_MAX_LEVEL * config.UPGRADE_ATK_PER_LEVEL
        )

    def test_legacy_item_without_upgrade(self) -> None:
        item = item_from_dict({"key": "sword_rune"})
        self.assertEqual(item.upgrade_level, 0)
        self.assertEqual(item.title, "符文长剑")


if __name__ == "__main__":
    unittest.main()
