"""用 matplotlib 绘制三张程序流程图。

为什么不用 Graphviz：Graphviz 需要单独安装二进制并配置 PATH，
换一台机器就可能跑不起来；而本项目的要求是"克隆下来就能跑"。
这里用 ``FancyBboxPatch`` 画节点、``FancyArrowPatch`` 画箭头，
纯 Python 依赖，导出 200dpi PNG 插进 Word 完全够用。

三张图分别是：
1. 主循环流程图（``flowcharts/01_主循环.png``）
2. 地图生成流程图（``flowcharts/02_地图生成.png``）
3. 战斗结算流程图（``flowcharts/03_战斗结算.png``）
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon  # noqa: E402

from ui.charts import setup_font  # noqa: E402

OUT_DIR = ROOT / "docs" / "flowcharts"

# 配色与界面图表保持一致
C_START = "#2f7f74"
C_PROCESS = "#3f5f8a"
C_DECISION = "#b5763f"
C_END = "#8a4b4b"
C_EDGE = "#4a5262"
C_TEXT = "#1f2430"
C_FILL_START = "#e7f2f0"
C_FILL_PROCESS = "#eaf0f7"
C_FILL_DECISION = "#fbf1e4"
C_FILL_END = "#f7eaea"

NODE_W = 5.0
NODE_H = 1.0
DEC_W = 3.4
DEC_H = 1.5


@dataclass
class Node:
    key: str
    text: str
    kind: str          # start / process / decision / end
    x: float
    y: float           # 行号，向下为正
    width: float = NODE_W
    height: float = NODE_H
    center: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        self.center = (self.x, -self.y)


class FlowRenderer:
    """极简流程图渲染器：节点 + 直箭头 + 折线箭头。"""

    def __init__(self, figsize: tuple[float, float] = (8.4, 12.6)) -> None:
        self.fig, self.ax = plt.subplots(figsize=figsize, dpi=200)
        self.fig.subplots_adjust(left=0.02, right=0.98, top=0.99, bottom=0.01)
        self.ax.axis("off")
        self.ax.set_aspect("equal")
        self.nodes: dict[str, Node] = {}

    # ------------------------------------------------------------ 节点
    def add(self, key: str, text: str, kind: str, x: float, y: float,
            width: float | None = None, height: float | None = None) -> Node:
        if kind == "decision":
            width = width or DEC_W
            height = height or DEC_H
        node = Node(key, text, kind, x, y, width or NODE_W, height or NODE_H)
        self.nodes[key] = node
        self._draw_node(node)
        return node

    def _draw_node(self, node: Node) -> None:
        cx, cy = node.center
        w, h = node.width, node.height
        if node.kind == "decision":
            points = [(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)]
            patch = Polygon(points, closed=True, facecolor=C_FILL_DECISION,
                            edgecolor=C_DECISION, linewidth=1.4, zorder=3)
        else:
            face = {"start": C_FILL_START, "end": C_FILL_END}.get(node.kind, C_FILL_PROCESS)
            edge = {"start": C_START, "end": C_END}.get(node.kind, C_PROCESS)
            boxstyle = "round,pad=0.02,rounding_size=0.45" if node.kind in ("start", "end") \
                else "round,pad=0.02,rounding_size=0.12"
            patch = FancyBboxPatch(
                (cx - w / 2, cy - h / 2), w, h, boxstyle=boxstyle,
                facecolor=face, edgecolor=edge, linewidth=1.4, zorder=3,
            )
        self.ax.add_patch(patch)
        self.ax.text(
            cx, cy, node.text, ha="center", va="center",
            fontsize=9.0, color=C_TEXT, zorder=4, linespacing=1.5,
        )

    # ------------------------------------------------------------ 连线
    def _anchor(self, node: Node, toward: tuple[float, float]) -> tuple[float, float]:
        """求从节点中心射向 toward 的射线与节点边框的交点。"""
        cx, cy = node.center
        dx, dy = toward[0] - cx, toward[1] - cy
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return cx, cy
        half_w, half_h = node.width / 2, node.height / 2
        scale_x = half_w / abs(dx) if abs(dx) > 1e-9 else float("inf")
        scale_y = half_h / abs(dy) if abs(dy) > 1e-9 else float("inf")
        scale = min(scale_x, scale_y)
        return cx + dx * scale, cy + dy * scale

    def edge(self, a: str, b: str, label: str = "", rad: float = 0.0,
             label_offset: tuple[float, float] = (0.0, 0.0)) -> None:
        """两个节点之间的直箭头 / 弧线箭头。"""
        node_a, node_b = self.nodes[a], self.nodes[b]
        start = self._anchor(node_a, node_b.center)
        end = self._anchor(node_b, node_a.center)
        arrow = FancyArrowPatch(
            posA=start, posB=end,
            arrowstyle="-|>", mutation_scale=13, linewidth=1.4,
            color=C_EDGE, shrinkA=1, shrinkB=1,
            connectionstyle=f"arc3,rad={rad}", zorder=2,
        )
        self.ax.add_patch(arrow)
        if label:
            mx = (start[0] + end[0]) / 2 + label_offset[0]
            my = (start[1] + end[1]) / 2 + label_offset[1]
            self.ax.text(mx, my, label, ha="center", va="center", fontsize=8.6,
                         color=C_DECISION, zorder=5,
                         bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                                   edgecolor="none", alpha=0.9))

    def edge_path(self, points: list[tuple[float, float]], label: str = "",
                  label_at: tuple[float, float] | None = None) -> None:
        """折线箭头，用于回环等需要绕行的连线。"""
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self.ax.plot(xs, ys, color=C_EDGE, linewidth=1.4, zorder=2,
                     solid_capstyle="round", solid_joinstyle="round")
        self.ax.annotate(
            "", xy=points[-1], xytext=points[-2],
            arrowprops=dict(arrowstyle="-|>", color=C_EDGE, linewidth=1.4,
                            mutation_scale=13, shrinkA=0, shrinkB=0),
            zorder=2,
        )
        if label and label_at is not None:
            self.ax.text(*label_at, label, ha="center", va="center", fontsize=8.6,
                         color=C_DECISION, zorder=5,
                         bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                                   edgecolor="none", alpha=0.9))

    def port(self, key: str, side: str, offset: float = 0.0) -> tuple[float, float]:
        """取节点某条边上的连接点，用于手工布线。"""
        node = self.nodes[key]
        cx, cy = node.center
        if side == "left":
            return cx - node.width / 2, cy + offset
        if side == "right":
            return cx + node.width / 2, cy + offset
        if side == "top":
            return cx + offset, cy + node.height / 2
        return cx + offset, cy - node.height / 2

    def save(self, path: Path, title: str = "") -> None:
        if title:
            self.ax.set_title(title, fontsize=13, color=C_TEXT, fontweight="bold", pad=10)
        bounds = [n for n in self.nodes.values()]
        min_x = min(n.center[0] - n.width / 2 for n in bounds) - 2.6
        max_x = max(n.center[0] + n.width / 2 for n in bounds) + 2.6
        min_y = min(n.center[1] - n.height / 2 for n in bounds) - 1.2
        max_y = max(n.center[1] + n.height / 2 for n in bounds) + 1.2
        self.ax.set_xlim(min_x, max_x)
        self.ax.set_ylim(min_y, max_y)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fig.savefig(path, dpi=200, facecolor="white", bbox_inches="tight", pad_inches=0.2)
        plt.close(self.fig)
        print(f"已生成 {path.relative_to(ROOT)}")


# ====================================================================== 图 1
def draw_main_loop(path: Path) -> None:
    r = FlowRenderer(figsize=(7.6, 12.2))
    x = 3.0
    r.add("s", "开始", "start", x, 0)
    r.add("p1", "初始化配置、字体与数据目录", "process", x, 1.2)
    r.add("p2", "创建新游戏 / 读取存档\n（还原 RNG 状态与地图）", "process", x, 2.5)
    r.add("p3", "生成当前层地牢\n（房间→走廊→楼梯→怪物→道具）", "process", x, 3.9)
    r.add("p4", "计算视野 FOV 并渲染界面", "process", x, 5.2)
    r.add("p5", "等待玩家键鼠输入", "process", x, 6.4)
    r.add("p6", "执行玩家行动\n（移动 / 攻击 / 拾取 / 使用道具 / 下楼）", "process", x, 7.7)
    r.add("p7", "怪物回合：逐个 AI 决策与伤害结算", "process", x, 9.0)
    r.add("d1", "玩家阵亡或\n已击败 BOSS？", "decision", x, 10.4)
    r.add("p8", "更新视野、日志与状态面板\n回合数 +1", "process", x, 11.8)
    r.add("p9", "生成本局记录\n写入 records.json", "process", x + 5.8, 10.4)
    r.add("e1", "结束", "end", x + 5.8, 11.8)

    for a, b in [("s", "p1"), ("p1", "p2"), ("p2", "p3"), ("p3", "p4"),
                 ("p4", "p5"), ("p5", "p6"), ("p6", "p7"), ("p7", "d1")]:
        r.edge(a, b)
    r.edge("d1", "p9", label="是", label_offset=(0, 0.3))
    r.edge("p9", "e1")
    r.edge("d1", "p8", label="否", label_offset=(0.42, 0.05))

    # 回环：从 p8 右侧绕回 p5 右侧（布线走两条分支框之间的空隙）
    start = r.port("p8", "right", 0.1)
    mid_y = r.port("p5", "right", 0)[1]
    loop_x = x + 3.0
    r.edge_path([start, (loop_x, start[1]), (loop_x, mid_y), r.port("p5", "right", 0)])

    r.save(path)


# ====================================================================== 图 2
def draw_map_generation(path: Path) -> None:
    """主线竖直向下，两个"重试"分支分别从左、右两条侧通道回到"随机生成"。"""
    r = FlowRenderer(figsize=(8.0, 11.6))
    x = 3.0
    r.add("s", "开始", "start", x, 0)
    r.add("p1", "初始化 40 × 25 地图，全部填为墙", "process", x, 1.2)
    r.add("p2", "随机生成房间的尺寸与位置", "process", x, 2.4)
    r.add("d1", "与已有房间\n外扩 1 格后重叠？", "decision", x, 3.8)
    r.add("p3", "把房间内部挖成地板", "process", x, 5.3)
    r.add("d2", "房间数量达到\n目标值？", "decision", x, 6.8)
    r.add("p4", "按中心横坐标排序\n相邻房间之间挖 L 型走廊", "process", x, 8.3)
    r.add("p5", "走廊与房间外框的交界处放置门", "process", x, 9.6)
    r.add("p6", "BFS 求最远可走格，放置下行楼梯", "process", x, 10.8)
    r.add("p7", "按层数配额放置怪物与道具\n（第一件固定为治疗药水）", "process", x, 12.0)
    r.add("e1", "结束", "end", x, 13.2)

    r.edge("s", "p1")
    r.edge("p1", "p2")
    r.edge("p2", "d1")
    r.edge("d1", "p3", label="否", label_offset=(-0.35, 0))
    r.edge("d2", "p4", label="是", label_offset=(0.45, 0.1))
    for a, b in [("p3", "d2"), ("p4", "p5"), ("p5", "p6"), ("p6", "p7"), ("p7", "e1")]:
        r.edge(a, b)

    # 右侧重试通道：d1「是」→ 回到 p2
    right_x = x + 3.4
    mid_right = (r.port("d1", "right")[1] + r.port("p2", "right")[1]) / 2
    r.edge_path(
        [r.port("d1", "right"), (right_x, r.port("d1", "right")[1]),
         (right_x, r.port("p2", "right")[1]), r.port("p2", "right")],
        label="是（重试）", label_at=(right_x + 0.55, mid_right),
    )

    # 左侧重试通道：d2「否」→ 回到 p2
    left_x = x - 3.4
    mid_left = (r.port("d2", "left")[1] + r.port("p2", "left")[1]) / 2
    r.edge_path(
        [r.port("d2", "left"), (left_x, r.port("d2", "left")[1]),
         (left_x, r.port("p2", "left")[1]), r.port("p2", "left")],
        label="否（继续）", label_at=(left_x - 0.55, mid_left),
    )

    r.save(path)


# ====================================================================== 图 3
def draw_combat(path: Path) -> None:
    """主线居中；"落空"走左侧通道直达终点，"未死亡"走右侧通道回到终点。"""
    r = FlowRenderer(figsize=(9.0, 10.4))
    x = 3.4
    r.add("s", "开始一次攻击结算", "start", x, 0)
    r.add("p1", "读取攻击方总攻击力\n与防御方总防御力", "process", x, 1.3)
    r.add("d1", "命中判定\nrandom() < 8% ？", "decision", x, 2.8)
    r.add("p3", "基础伤害 = max(1, 攻击 − 防御)", "process", x, 4.4)
    r.add("d2", "暴击判定\nrandom() < 15% ？", "decision", x, 5.9)
    r.add("p5", "扣除目标生命值\n并累计伤害统计", "process", x, 7.5)
    r.add("d3", "目标生命 ≤ 0 ？", "decision", x, 8.9)
    r.add("p6", "标记死亡\n结算经验值与金币", "process", x, 10.3)
    r.add("e1", "返回结算结果", "end", x, 11.6)

    # 两条分支框：落空在左，暴击在右
    r.add("p2", "本次攻击落空\n伤害记为 0", "process", x - 4.7, 2.8, width=3.8)
    r.add("p4", "伤害 = round(基础伤害 × 1.8)", "process", x + 5.1, 5.9, width=4.2)

    # 主线
    r.edge("s", "p1")
    r.edge("p1", "d1")
    r.edge("d1", "p3", label="否", label_offset=(-0.34, 0))
    r.edge("d1", "p2", label="是", label_offset=(-0.55, 0.34))
    r.edge("p3", "d2")
    r.edge("d2", "p5", label="否", label_offset=(-0.34, 0))
    r.edge("d2", "p4", label="是", label_offset=(0.5, 0.3))
    r.edge("p5", "d3")
    r.edge("d3", "p6", label="是", label_offset=(-0.52, 0.1))
    r.edge("p6", "e1")

    # 落空 → 左侧通道 → 终点
    left_x = x - 3.0
    r.edge_path([
        r.port("p2", "bottom", -1.2), (r.port("p2", "bottom", -1.2)[0], -11.6),
        r.port("e1", "left"),
    ])
    # 暴击 → 下折 → 汇入"扣除生命"
    r.edge_path([
        r.port("p4", "bottom", 0.6), (r.port("p4", "bottom", 0.6)[0], -7.5),
        r.port("p5", "right"),
    ])
    # 未死亡 → 右侧通道 → 终点
    right_x = x + 3.0
    r.edge_path(
        [r.port("d3", "right"), (right_x, r.port("d3", "right")[1]),
         (right_x, -11.6), r.port("e1", "right")],
        label="否", label_at=(right_x + 0.34, -9.9),
    )

    r.save(path)


def main() -> int:
    setup_font()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    draw_main_loop(OUT_DIR / "01_主循环.png")
    draw_map_generation(OUT_DIR / "02_地图生成.png")
    draw_combat(OUT_DIR / "03_战斗结算.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
