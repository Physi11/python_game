"""地牢地图模块。

职责
----
1. 定义地形枚举 ``Tile`` 与房间 ``Room``；
2. ``Dungeon`` 负责程序化生成（随机房间 + L 型走廊）、
   视野计算（Bresenham 射线）、BFS 测距、随机落点、序列化。

地图生成算法选择"随机房间 + L 型走廊"而不是 BSP：
核心逻辑只有二十来行、连通性天然成立、伪代码好写进实验报告。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterator

from . import config
from .rng import Rng


class Tile(IntEnum):
    """地形类型。用整数枚举便于直接序列化成字符行。"""

    WALL = 0
    FLOOR = 1
    DOOR = 2
    STAIRS = 3

    @property
    def char(self) -> str:
        """地形在存档字符串中的表示。"""
        return {Tile.WALL: "#", Tile.FLOOR: ".", Tile.DOOR: "+", Tile.STAIRS: ">"}[self]

    @property
    def walkable(self) -> bool:
        """是否可通行。墙不可通行，其余均可。"""
        return self is not Tile.WALL


_CHAR_TO_TILE = {"#": Tile.WALL, ".": Tile.FLOOR, "+": Tile.DOOR, ">": Tile.STAIRS}


@dataclass
class Room:
    """矩形房间，用左上角坐标加宽高表示。"""

    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        """房间中心格，用于放置玩家与连接走廊。"""
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def area(self) -> int:
        return self.w * self.h

    def inner_cells(self) -> Iterator[tuple[int, int]]:
        """遍历房间内部所有格子。"""
        for yy in range(self.y, self.y + self.h):
            for xx in range(self.x, self.x + self.w):
                yield xx, yy

    def ring_cells(self) -> Iterator[tuple[int, int]]:
        """遍历房间外扩一圈的边框格子（不含内部）。"""
        for xx in range(self.x - 1, self.x + self.w + 1):
            yield xx, self.y - 1
            yield xx, self.y + self.h
        for yy in range(self.y, self.y + self.h):
            yield self.x - 1, yy
            yield self.x + self.w, yy

    def intersects(self, other: "Room", pad: int = 1) -> bool:
        """判断两个房间（各自外扩 pad 格后）是否相交。

        pad=1 保证两个房间之间至少隔一堵墙，不会连成一个大开间。
        """
        return not (
            self.x + self.w + pad <= other.x
            or other.x + other.w + pad <= self.x
            or self.y + self.h + pad <= other.y
            or other.y + other.h + pad <= self.y
        )


class Dungeon:
    """一层地牢。"""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        # tiles[y][x]，行优先，便于直接切成字符串存档
        self.tiles: list[list[Tile]] = [
            [Tile.WALL for _ in range(width)] for _ in range(height)
        ]
        self.rooms: list[Room] = []
        self.stairs: tuple[int, int] | None = None
        self.visible: set[tuple[int, int]] = set()      # 当前视野内
        self.explored: set[tuple[int, int]] = set()     # 曾经看到过
        self.floor_cells: list[tuple[int, int]] = []    # 所有可走格，缓存随机落点用

    # ------------------------------------------------------------ 查询
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def tile_at(self, x: int, y: int) -> Tile:
        """取地形；越界时视为墙（这样碰撞判断天然安全）。"""
        if not self.in_bounds(x, y):
            return Tile.WALL
        return self.tiles[y][x]

    def is_walkable(self, x: int, y: int) -> bool:
        return self.tile_at(x, y).walkable

    @staticmethod
    def neighbors4(x: int, y: int) -> Iterator[tuple[int, int]]:
        """四方向邻居。本项目只允许上下左右移动，不走斜线。"""
        yield x + 1, y
        yield x - 1, y
        yield x, y + 1
        yield x, y - 1

    # ------------------------------------------------------------ 生成
    @classmethod
    def generate(cls, rng: Rng, floor: int = 1) -> "Dungeon":
        """随机生成第 ``floor`` 层地牢。

        步骤：全墙起步 → 随机投放不重叠的房间 → 链式连接保证连通 →
        由调用方再放置玩家、楼梯、怪物与道具。
        """
        dungeon = cls(config.MAP_W, config.MAP_H)
        target_rooms = min(config.ROOM_MIN_COUNT + (floor - 1), config.ROOM_MAX_COUNT)

        # 1) 随机投放房间，外扩 1 格检测不重叠
        attempts = 0
        while len(dungeon.rooms) < target_rooms and attempts < config.ROOM_PLACE_ATTEMPTS:
            attempts += 1
            w = rng.randint(config.ROOM_MIN_SIZE, config.ROOM_MAX_SIZE)
            h = rng.randint(config.ROOM_MIN_SIZE, config.ROOM_MAX_SIZE)
            # 留出 1 格外墙，房间不会贴边
            x = rng.randint(1, max(1, dungeon.width - w - 2))
            y = rng.randint(1, max(1, dungeon.height - h - 2))
            candidate = Room(x, y, w, h)
            if any(candidate.intersects(other) for other in dungeon.rooms):
                continue
            dungeon.rooms.append(candidate)

        # 2) 挖空房间内部
        for room in dungeon.rooms:
            for xx, yy in room.inner_cells():
                dungeon.tiles[yy][xx] = Tile.FLOOR

        # 3) 按中心横坐标排序后链式连接，保证所有房间互通
        ordered = sorted(dungeon.rooms, key=lambda r: r.center[0])
        for prev, cur in zip(ordered, ordered[1:]):
            dungeon._carve_corridor(rng, prev.center, cur.center)

        # 4) 走廊穿过房间外框的格子改成门（纯装饰，可通行）
        dungeon._decorate_doors()

        dungeon._rebuild_floor_cache()
        return dungeon

    def _carve_corridor(self, rng: Rng, start: tuple[int, int], end: tuple[int, int]) -> None:
        """挖一条 L 型走廊，随机决定先横后竖还是先竖后横。"""
        (x0, y0), (x1, y1) = start, end
        if rng.chance(0.5):
            self._carve_h(x0, x1, y0)
            self._carve_v(y0, y1, x1)
        else:
            self._carve_v(y0, y1, x0)
            self._carve_h(x0, x1, y1)

    def _carve_h(self, x0: int, x1: int, y: int) -> None:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            if self.tile_at(x, y) is Tile.WALL:
                self.tiles[y][x] = Tile.FLOOR

    def _carve_v(self, y0: int, y1: int, x: int) -> None:
        for y in range(min(y0, y1), max(y0, y1) + 1):
            if self.tile_at(x, y) is Tile.WALL:
                self.tiles[y][x] = Tile.FLOOR

    def _decorate_doors(self) -> None:
        """把走廊与房间外框交界处的空格换成门。"""
        for room in self.rooms:
            for xx, yy in room.ring_cells():
                if self.in_bounds(xx, yy) and self.tiles[yy][xx] is Tile.FLOOR:
                    self.tiles[yy][xx] = Tile.DOOR

    def _rebuild_floor_cache(self) -> None:
        self.floor_cells = [
            (xx, yy)
            for yy in range(self.height)
            for xx in range(self.width)
            if self.tiles[yy][xx].walkable
        ]

    # ------------------------------------------------------------ 放置
    def place_stairs(self, from_pos: tuple[int, int]) -> tuple[int, int]:
        """把楼梯放在距离玩家 BFS 步数最远的可走格。

        保证玩家必须探索一段距离才能下楼，而不是"出门就下一层"。
        """
        distances = self.bfs_distances(from_pos)
        if not distances:
            # 极端兜底：没有任何可达格时随便放一个可走格
            target = self.floor_cells[0]
        else:
            target = max(distances.items(), key=lambda kv: kv[1])[0]
            if target == from_pos:
                candidates = [c for c in self.floor_cells if c != from_pos]
                target = candidates[0] if candidates else from_pos
        self.stairs = target
        self.tiles[target[1]][target[0]] = Tile.STAIRS
        return target

    def random_floor(self, rng: Rng, exclude: set[tuple[int, int]] | None = None) -> tuple[int, int]:
        """在可走格中随机取一个，可排除指定坐标集合。"""
        blocked = exclude or set()
        candidates = [c for c in self.floor_cells if c not in blocked]
        if not candidates:
            return self.floor_cells[0]
        return rng.choice(candidates)

    # ------------------------------------------------------------ 视野
    def compute_fov(self, px: int, py: int, radius: int = config.FOV_RADIUS) -> None:
        """以玩家为中心计算当前视野。

        对半径内的每个格子做一次 Bresenham 连线，若中途被墙挡住则不可见。
        半径 7 时约需 150 次连线判断，单帧耗时不足 1 毫秒。
        """
        self.visible.clear()
        self.visible.add((px, py))
        self.explored.add((px, py))
        radius_sq = radius * radius
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy > radius_sq:
                    continue
                x, y = px + dx, py + dy
                if (x, y) == (px, py) or not self.in_bounds(x, y):
                    continue
                if self._has_line_of_sight(px, py, x, y):
                    self.visible.add((x, y))
                    self.explored.add((x, y))

    def _has_line_of_sight(self, x0: int, y0: int, x1: int, y1: int) -> bool:
        """起点到终点之间若存在墙则视线被阻挡。终点本身即使是墙也可见。"""
        path = self._bresenham(x0, y0, x1, y1)
        for xx, yy in path[:-1]:
            if self.tile_at(xx, yy) is Tile.WALL:
                return False
        return True

    @staticmethod
    def _bresenham(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
        """标准 Bresenham 直线算法，返回不含起点、含终点的格子序列。"""
        cells: list[tuple[int, int]] = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y = x0, y0
        while True:
            if (x, y) != (x0, y0):
                cells.append((x, y))
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        return cells

    # ------------------------------------------------------------ BFS
    def bfs_distances(self, start: tuple[int, int]) -> dict[tuple[int, int], int]:
        """从起点出发的四方向 BFS，返回每个可达格的步数。"""
        if not self.is_walkable(*start):
            return {}
        distances: dict[tuple[int, int], int] = {start: 0}
        queue: list[tuple[int, int]] = [start]
        head = 0
        while head < len(queue):
            cur = queue[head]
            head += 1
            for nxt in self.neighbors4(*cur):
                if nxt in distances or not self.is_walkable(*nxt):
                    continue
                distances[nxt] = distances[cur] + 1
                queue.append(nxt)
        return distances

    # ------------------------------------------------------------ 序列化
    def to_rows(self) -> list[str]:
        """导出为 25 行、每行 40 个字符的地图字符串，人眼可读、便于报告展示。"""
        return ["".join(tile.char for tile in row) for row in self.tiles]

    @classmethod
    def from_rows(
        cls,
        rows: list[str],
        stairs: tuple[int, int] | None,
        explored: set[tuple[int, int]] | None = None,
    ) -> "Dungeon":
        """从字符串行还原地图。行数/列数不一致时抛 ``ValueError``。"""
        if not rows:
            raise ValueError("地图行为空")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("地图各行长度不一致")
        dungeon = cls(width, len(rows))
        for y, row in enumerate(rows):
            line: list[Tile] = []
            for ch in row:
                if ch not in _CHAR_TO_TILE:
                    raise ValueError(f"无法识别的地图字符：{ch!r}")
                line.append(_CHAR_TO_TILE[ch])
            dungeon.tiles[y] = line
        dungeon.stairs = tuple(stairs) if stairs else None  # type: ignore[assignment]
        dungeon.explored = set(explored or set())
        dungeon._rebuild_floor_cache()
        return dungeon

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<Dungeon {self.width}x{self.height} rooms={len(self.rooms)}>"
