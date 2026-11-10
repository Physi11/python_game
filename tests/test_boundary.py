"""输入验证与边界情况测试。

对应评分标准中"程序能处理非法输入、边界情况"一项。
本文件所有用例都在验证：**错误输入不会让程序崩溃，而是返回可预期的结果**。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon import config
from dungeon.dungeon import Dungeon, Tile
from dungeon.game_state import GameState, GameStatus
from dungeon.item import make_item
from dungeon.monster import MONSTER_BY_KIND, Monster
from dungeon.player import Player
from dungeon.rng import Rng

# 一个 5×5 的封闭房间，用于构造完全可控的测试局面
ROOM_ROWS = [
    "#####",
    "#...#",
    "#...#",
    "#...#",
    "#####",
]


def make_room_state() -> GameState:
    """构造一个只有一间小屋、没有怪物和道具的干净局面。"""
    dungeon = Dungeon.from_rows(ROOM_ROWS, None, set())
    player = Player.create_new()
    player.move_to(1, 1)
    state = GameState(
        rng=Rng(1),
        player=player,
        dungeon=dungeon,
        monsters=[],
        items_on_floor={},
    )
    dungeon.compute_fov(player.x, player.y)
    return state


class TestMovementValidation(unittest.TestCase):
    """移动相关的非法输入。"""

    def setUp(self) -> None:
        self.state = make_room_state()

    def test_move_into_wall_does_not_consume_turn(self) -> None:
        """撞墙时返回 False，回合数与坐标都不变。"""
        before_turn = self.state.turn
        before_pos = self.state.player.pos
        self.assertFalse(self.state.try_move(0, -1))
        self.assertEqual(self.state.turn, before_turn)
        self.assertEqual(self.state.player.pos, before_pos)

    def test_invalid_direction_rejected(self) -> None:
        """斜向移动和零位移都属于非法输入。"""
        for dx, dy in [(1, 1), (0, 0), (2, 0), (0, -5)]:
            self.assertFalse(self.state.try_move(dx, dy), f"({dx},{dy}) 应被拒绝")
        self.assertEqual(self.state.turn, 0)

    def test_out_of_bounds_is_safe(self) -> None:
        """越界坐标查询不会抛异常，一律视为不可通行。"""
        for x, y in [(-1, 0), (0, -1), (999, 999), (-999, 5)]:
            self.assertFalse(self.state.dungeon.is_walkable(x, y))
            self.assertFalse(self.state.dungeon.in_bounds(x, y))

    def test_normal_move_consumes_turn(self) -> None:
        """合法移动应推进回合数并记录步数。"""
        self.assertTrue(self.state.try_move(1, 0))
        self.assertEqual(self.state.turn, 1)
        self.assertEqual(self.state.player.steps, 1)
        self.assertEqual(self.state.player.pos, (2, 1))


class TestItemValidation(unittest.TestCase):
    """道具使用的非法输入。"""

    def setUp(self) -> None:
        self.player = Player.create_new()
        self.state = make_room_state()

    def test_use_item_on_empty_inventory(self) -> None:
        """空背包取用道具不能抛 IndexError。"""
        self.player.inventory.clear()
        ok, message = self.player.use_item(0)
        self.assertFalse(ok)
        self.assertIn("没有道具", message)

    def test_use_item_with_bad_index(self) -> None:
        """负数索引、超出范围的索引、非整数索引都要被拦下。"""
        for index in (-1, 999, "0", None):
            ok, _ = self.player.use_item(index)  # type: ignore[arg-type]
            self.assertFalse(ok, f"索引 {index!r} 应被拒绝")

    def test_potion_at_full_hp_rejected(self) -> None:
        """满血喝药返回失败原因，且道具不会被消耗。"""
        self.player.hp = self.player.max_hp
        count = len(self.player.inventory)
        ok, message = self.player.use_item(0)
        self.assertFalse(ok)
        self.assertIn("不需要", message)
        self.assertEqual(len(self.player.inventory), count)

    def test_unknown_item_key_in_save(self) -> None:
        """存档里出现未知道具时抛 ValueError，由存档层转成可读提示。"""
        from dungeon.item import item_from_dict

        with self.assertRaises(ValueError):
            item_from_dict({"key": "sword_of_cheating"})
        with self.assertRaises(ValueError):
            item_from_dict({})


class TestCombatBoundary(unittest.TestCase):
    """战斗与死亡的边界情况。"""

    def test_player_death_sets_status(self) -> None:
        """玩家血量被打空后，状态机应切到 dead 并记录死因。"""
        state = make_room_state()
        state.player.hp = 1
        brute = Monster(MONSTER_BY_KIND["goblin"], 2, 1, floor=1)
        brute.atk = 999
        state.monsters = [brute]

        for _ in range(50):
            if state.is_finished:
                break
            state.wait()

        self.assertEqual(state.status, GameStatus.DEAD)
        self.assertEqual(state.player.hp, 0)
        self.assertTrue(state.death_cause)

    def test_turn_limit_triggers_timeout(self) -> None:
        """回合数超过上限时自动结算，避免玩家无限挂机。"""
        state = make_room_state()
        state.turn = config.FLOOR_TURN_LIMIT + 1
        state._check_status()
        self.assertEqual(state.status, GameStatus.TIMEOUT)

    def test_descend_without_stairs(self) -> None:
        """没有楼梯 / 不在楼梯上时下楼请求应被拒绝。"""
        state = make_room_state()
        self.assertFalse(state.descend())
        self.assertEqual(state.floor, 1)


class TestStairsInteraction(unittest.TestCase):
    """楼梯交互的回归测试。

    对应场景：鼠标点过背包、用过道具之后，玩家站在楼梯上却下不去。
    这里锁住两条契约：``interact()`` 本身不消耗回合（所以"下楼"的分流
    必须留在界面层），而 ``descend()`` 在楼梯上确实能换层。
    """

    @staticmethod
    def _state_on_stairs() -> GameState:
        state = make_room_state()
        state.dungeon.tiles[2][2] = Tile.STAIRS
        state.dungeon.stairs = (2, 2)
        state.player.move_to(2, 2)
        state.dungeon.compute_fov(2, 2)
        return state

    def test_interact_on_stairs_does_not_consume_turn(self) -> None:
        """interact() 只提示、不推进回合——这是"下楼分流放在界面层"的依据。"""
        state = self._state_on_stairs()
        before = (state.turn, state.floor)
        self.assertFalse(state.interact())
        self.assertEqual((state.turn, state.floor), before)

    def test_descend_from_stairs_goes_down(self) -> None:
        """站在楼梯上 descend() 应当换层，且玩家落在新地图的可走格上。"""
        state = self._state_on_stairs()
        self.assertTrue(state.descend())
        self.assertEqual(state.floor, 2)
        self.assertTrue(state.dungeon.in_bounds(*state.player.pos))
        self.assertTrue(state.dungeon.is_walkable(*state.player.pos))

    def test_descend_after_using_item(self) -> None:
        """用过道具后仍能正常下楼（原本被键盘焦点问题挡住的路径）。"""
        state = self._state_on_stairs()
        state.player.hp = 1
        state.player.inventory = [make_item("potion_small")]

        self.assertTrue(state.use_item(0))
        self.assertTrue(state.stairs_here)
        self.assertTrue(state.descend())
        self.assertEqual(state.floor, 2)


class TestFloorScaling(unittest.TestCase):
    """难度随层数递增。"""

    def test_deeper_floor_monsters_are_stronger(self) -> None:
        """第 10 层的小怪必须明显强于第 1 层的同类。"""
        proto = MONSTER_BY_KIND["goblin"]
        shallow = Monster(proto, 0, 0, floor=1)
        deep = Monster(proto, 0, 0, floor=config.BOSS_FLOOR)
        self.assertGreater(deep.max_hp, shallow.max_hp)
        self.assertGreater(deep.atk, shallow.atk)

    def test_boss_floor_has_boss_and_no_stairs(self) -> None:
        """BOSS 层必须有深渊领主，且不设下行楼梯（否则可以绕过 BOSS）。"""
        state = GameState.new_game(seed=88)
        state._build_floor(config.BOSS_FLOOR)
        self.assertIsNone(state.dungeon.stairs)
        self.assertTrue(any(m.is_boss for m in state.monsters))

    def test_boss_stats_are_fixed(self) -> None:
        """BOSS 数值不随层数缩放，保证最终战斗强度可预期。"""
        proto = MONSTER_BY_KIND["demon_lord"]
        self.assertEqual(Monster(proto, 0, 0, floor=10).max_hp, proto.hp)
        self.assertEqual(Monster(proto, 0, 0, floor=1).max_hp, proto.hp)


class TestInventoryLimit(unittest.TestCase):
    """背包容量边界。"""

    def test_inventory_full_rejects_pickup(self) -> None:
        player = Player.create_new()
        player.inventory = [make_item("potion_small") for _ in range(config.INVENTORY_CAPACITY)]
        ok, message = player.pick_up(make_item("potion_small"))
        self.assertFalse(ok)
        self.assertIn("背包已满", message)
        self.assertEqual(len(player.inventory), config.INVENTORY_CAPACITY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
