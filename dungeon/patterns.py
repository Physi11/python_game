"""攻击范围（形状）计算。

本模块是**纯函数**：不持有地图对象，只通过回调询问"这一格能不能站人"，
因此可以脱离 ``Dungeon`` 与 tkinter 单独测试，测试里传一个 lambda 就够了。

坐标约定
--------
格子坐标 ``(x, y)``，``y`` 向下增大。攻击朝向是**八方向**：
移动仍然只走四方向，但攻击允许斜着打，否则"长而窄"的长矛在走廊里会很难用。

四种形状
--------
``melee``   近战：正前方 1 格
``line``    穿刺：正前方一条直线，遇墙停下（长矛）
``arc``     横扫：正前方 1 格 + 左右斜前各 1 格 + 正前方第 2 格（大刀）
``ranged``  远程：点哪打哪，只要求距离在射程内（弓）
"""

from __future__ import annotations

from typing import Callable

Cell = tuple[int, int]

PATTERNS = ("melee", "line", "arc", "ranged")

Blocked = Callable[[int, int], bool]


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def facing(origin: Cell, target: Cell) -> Cell:
    """从 origin 指向 target 的单位方向（八方向）。同格返回 (0, 0)。"""
    dx = _sign(target[0] - origin[0])
    dy = _sign(target[1] - origin[1])
    return dx, dy


def chebyshev(a: Cell, b: Cell) -> int:
    """切比雪夫距离：斜向移动算 1 步，与八方向攻击一致。"""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _clockwise(direction: Cell) -> Cell:
    """方向顺时针转 45°，用来取横扫的左右两翼。"""
    dx, dy = direction
    return -dy, dx


def pattern_tiles(
    origin: Cell,
    target: Cell,
    pattern: str,
    reach: int,
    min_reach: int = 1,
    blocked: Blocked | None = None,
) -> frozenset[Cell]:
    """算出一次攻击覆盖的所有格子。

    参数
    ----
    origin  攻击者所在格
    target  玩家点击（或 AI 选定）的目标格，只用来确定**朝向**与距离
    pattern 形状，见模块文档
    reach   最大射程（格）
    min_reach 最小射程，远程武器用来防止"贴脸射箭"
    blocked 回调：某格是否阻挡（墙）。阻挡的格子本身不会出现在结果里

    ``blocked`` 传 ``None`` 表示不做遮挡判断（测试与预览用）。
    """
    if pattern not in PATTERNS:
        raise ValueError(f"未知的攻击形状：{pattern}")
    if reach < 1:
        raise ValueError("射程至少为 1")
    if min_reach < 0 or min_reach > reach:
        raise ValueError("最小射程必须落在 0 与最大射程之间")

    direction = facing(origin, target)
    if direction == (0, 0):
        return frozenset()          # 点自己身上：不产生攻击范围

    def free(cell: Cell) -> bool:
        return not (blocked and blocked(*cell))

    def step(dx: int, dy: int) -> Cell:
        return origin[0] + dx, origin[1] + dy

    if pattern == "ranged":
        distance = chebyshev(origin, target)
        if distance < min_reach or distance > reach:
            return frozenset()
        return frozenset({target}) if free(target) else frozenset()

    if pattern == "melee":
        cell = step(*direction)
        return frozenset({cell}) if free(cell) else frozenset()

    if pattern == "line":
        tiles: list[Cell] = []
        for index in range(1, reach + 1):
            cell = step(direction[0] * index, direction[1] * index)
            if not free(cell):
                break               # 长矛会被墙挡住，不会穿墙
            tiles.append(cell)
        return frozenset(tiles)

    # arc：横扫。正前方 1 格 + 两翼 + 正前方第 2 格
    side = _clockwise(direction)
    front = step(*direction)
    wings = {
        (front[0] + side[0], front[1] + side[1]),
        (front[0] - side[0], front[1] - side[1]),
    }
    if reach >= 2:
        wings.add(step(direction[0] * 2, direction[1] * 2))
    return frozenset({front, *wings} if free(front) else wings)


def is_adjacent(a: Cell, b: Cell) -> bool:
    """八方向相邻（含斜角）。"""
    return chebyshev(a, b) == 1
