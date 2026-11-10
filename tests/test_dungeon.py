"""地图生成相关的单元测试。

核心关注三件事：
1. 房间互不重叠（否则会连成一个大开间，失去地牢感）；
2. 地图全连通（否则楼梯可能永远走不到）；
3. 玩家、楼梯、怪物、道具的落点都合法。
"""

from __future__ import annotations

import unittest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon import config
from dungeon.dungeon import Dungeon, Tile
from dungeon.rng import Rng


class TestDungeonGeneration(unittest.TestCase):
    """地图生成测试。"""

    def test_rooms_no_overlap(self) -> None:
        """100 个随机种子下，任意两个房间外扩 1 格后都不相交。"""
        for seed in range(100):
            dungeon = Dungeon.generate(Rng(seed), floor=1)
            rooms = dungeon.rooms
            self.assertGreaterEqual(len(rooms), 5, f"种子 {seed} 房间太少")
            for i in range(len(rooms)):
                for j in range(i + 1, len(rooms)):
                    self.assertFalse(
                        rooms[i].intersects(rooms[j]),
                        f"种子 {seed} 的房间 {i} 与 {j} 重叠",
                    )

    def test_map_fully_connected(self) -> None:
        """从玩家出生点出发，必须能走到楼梯和每个房间中心。"""
        for seed in range(100):
            dungeon = Dungeon.generate(Rng(seed), floor=1)
            start = dungeon.rooms[0].center
            stairs = dungeon.place_stairs(start)
            reachable = dungeon.bfs_distances(start)

            self.assertIn(stairs, reachable, f"种子 {seed} 的楼梯不可达")
            for index, room in enumerate(dungeon.rooms):
                self.assertIn(
                    room.center, reachable, f"种子 {seed} 的房间 {index} 不可达"
                )

    def test_stairs_not_at_spawn(self) -> None:
        """楼梯不应该贴脸生成，至少离出生点 10 步以上。"""
        for seed in range(50):
            dungeon = Dungeon.generate(Rng(seed), floor=1)
            start = dungeon.rooms[0].center
            stairs = dungeon.place_stairs(start)
            distance = dungeon.bfs_distances(start)[stairs]
            self.assertGreater(distance, 10, f"种子 {seed} 楼梯太近：{distance} 步")

    def test_stairs_tile_is_walkable(self) -> None:
        """楼梯格本身必须是可通行的地形。"""
        dungeon = Dungeon.generate(Rng(7), floor=1)
        stairs = dungeon.place_stairs(dungeon.rooms[0].center)
        self.assertIs(dungeon.tile_at(*stairs), Tile.STAIRS)
        self.assertTrue(dungeon.is_walkable(*stairs))

    def test_spawn_positions_valid(self) -> None:
        """游戏开局时，玩家/怪物/道具都落在可走格上，且互不重叠。"""
        from dungeon.game_state import GameState

        state = GameState.new_game(seed=2024)
        self.assertTrue(state.dungeon.is_walkable(*state.player.pos))

        positions = [m.pos for m in state.monsters]
        self.assertEqual(len(positions), len(set(positions)), "怪物位置重复")

        for pos in positions:
            self.assertTrue(state.dungeon.is_walkable(*pos))
            self.assertNotEqual(pos, state.player.pos)

        for pos in state.items_on_floor:
            self.assertTrue(state.dungeon.is_walkable(*pos))

        # 首层至少有一瓶药，避免开局无补给
        self.assertTrue(
            any(item.key.startswith("potion") for item in state.items_on_floor.values())
        )

    def test_serialization_roundtrip(self) -> None:
        """地图导出成字符串后再解析回来，必须完全一致。"""
        dungeon = Dungeon.generate(Rng(11), floor=1)
        stairs = dungeon.place_stairs(dungeon.rooms[0].center)
        dungeon.compute_fov(*dungeon.rooms[0].center)

        rows = dungeon.to_rows()
        self.assertEqual(len(rows), config.MAP_H)
        self.assertTrue(all(len(row) == config.MAP_W for row in rows))

        restored = Dungeon.from_rows(rows, stairs, dungeon.explored)
        self.assertEqual(restored.to_rows(), rows)
        self.assertEqual(restored.stairs, stairs)


class TestFieldOfView(unittest.TestCase):
    """视野计算测试。"""

    def test_fov_blocked_by_wall(self) -> None:
        """墙后面的格子不应该进入视野。"""
        dungeon = Dungeon(10, 10)
        # 造一条竖直走廊，中间放一堵墙
        for y in range(10):
            dungeon.tiles[y][5] = Tile.FLOOR
        dungeon.tiles[5][5] = Tile.WALL   # 玩家正上方一格的墙
        dungeon.tiles[3][5] = Tile.FLOOR
        dungeon.compute_fov(5, 6, radius=7)

        self.assertIn((5, 5), dungeon.visible, "墙本身应该可见")
        self.assertNotIn((5, 3), dungeon.visible, "墙后的格子不应该可见")

    def test_explored_accumulates(self) -> None:
        """走过的区域会进入 explored，即使离开视野也不会消失。"""
        dungeon = Dungeon.generate(Rng(3), floor=1)
        start = dungeon.rooms[0].center
        dungeon.compute_fov(*start)
        first = set(dungeon.explored)

        other = dungeon.rooms[-1].center
        dungeon.compute_fov(*other)
        self.assertTrue(first.issubset(dungeon.explored))


if __name__ == "__main__":
    unittest.main(verbosity=2)
