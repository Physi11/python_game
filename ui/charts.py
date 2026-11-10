"""统计图表构建模块。

把 ``records.json`` 里的对局数据交给 pandas 做聚合，再用 matplotlib
画成 5 张图。图表既可以在程序里（菜单「查看 → 统计图表」）实时预览，
也可以由 ``tools/make_charts.py`` 批量导出 300dpi PNG 插进实验报告。

之所以单独抽出这个模块，是因为 ``dungeon/`` 逻辑层不允许依赖绘图库，
而界面层又不能塞业务规则——图表属于"纯表现"，放在 ui 下最合适。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.figure import Figure

from dungeon.stats import PANDAS_OK, StatsAnalyzer

# 与界面一致的深色配色，保证报告里图表和截图风格统一
BG = "#ffffff"
FG = "#1f2430"
GRID = "#dfe3ea"
ACCENT = "#2f7f74"
ACCENT2 = "#c0714f"
ACCENT3 = "#4a6fa5"

_CJK_CANDIDATES = ("Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "Arial Unicode MS")


@dataclass
class ChartSpec:
    """一张图的描述：标题、文件名、Figure 对象。"""

    key: str
    title: str
    filename: str
    figure: Figure
    note: str = ""


def setup_font() -> str:
    """配置 matplotlib 中文字体，返回实际使用的字体名。

    找不到中文字体时不做任何设置并给出警告，此时图上中文会变成方框——
    这是最后一级降级，正常运行环境中不会发生（Windows 自带雅黑）。
    """
    available = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in _CJK_CANDIDATES:
        if candidate in available:
            plt.rcParams["font.sans-serif"] = [candidate]
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["axes.unicode_minus"] = False   # 负号正常显示
            return candidate
    warnings.warn("未找到中文字体，图表中的中文可能显示为方块", RuntimeWarning)
    return ""


def _style_axes(ax: Any, title: str, xlabel: str = "", ylabel: str = "") -> None:
    """统一的坐标轴样式：去顶右边框、浅色网格、深色标题。"""
    ax.set_title(title, fontsize=14, color=FG, pad=12, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, color=FG, fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, color=FG, fontsize=10)
    ax.tick_params(colors=FG, labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)


def build_figures(analyzer: StatsAnalyzer) -> list[ChartSpec]:
    """构建全部图表。没有记录时返回空列表，由调用方给出友好提示。"""
    if not PANDAS_OK:  # pragma: no cover - 取决于环境
        return []
    setup_font()

    records = analyzer.records
    if not records:
        return []

    df = analyzer.to_dataframe()
    summary = analyzer.summary()
    specs: list[ChartSpec] = []

    # ---------------------------------------------------------- 图 1：熟练度曲线
    fig1 = Figure(figsize=(8, 4.2), dpi=100, facecolor=BG)
    ax = fig1.add_subplot(111)
    _style_axes(ax, "最近对局到达层数变化", "对局序号", "到达层数")
    recent = df.tail(20).reset_index(drop=True)
    xs = list(range(1, len(recent) + 1))
    ys = recent["max_floor"].astype(float).tolist()
    ax.plot(xs, ys, color=ACCENT, linewidth=2, marker="o", markersize=5, label="到达层数")
    if len(ys) >= 3:
        smooth = [sum(ys[max(0, i - 2): i + 1]) / len(ys[max(0, i - 2): i + 1]) for i in range(len(ys))]
        ax.plot(xs, smooth, color=ACCENT2, linewidth=2, linestyle="--", label="3 局滑动平均")
    ax.axhline(summary["avg_floor"], color=ACCENT3, linewidth=1, linestyle=":", label="总体平均")
    ax.set_ylim(0, 11)
    ax.legend(frameon=False, fontsize=9, labelcolor=FG)
    fig1.tight_layout()
    specs.append(
        ChartSpec(
            "progress", "图 1  最近对局到达层数变化", "01_到达层数趋势.png", fig1,
            "折线为每局到达的最深层数，虚线为 3 局滑动平均。用于观察玩家熟练度是否随对局次数提升。",
        )
    )

    # ---------------------------------------------------------- 图 2：难度分布
    fig2 = Figure(figsize=(8, 4.2), dpi=100, facecolor=BG)
    ax2 = fig2.add_subplot(121)
    _style_axes(ax2, "阵亡层数分布", "层数", "局数")
    floors = summary["deaths_by_floor"]
    if floors:
        keys = sorted(floors)
        ax2.bar([str(k) for k in keys], [floors[k] for k in keys], color=ACCENT)
    ax3 = fig2.add_subplot(122)
    _style_axes(ax3, "死因 Top5", "局数", "")
    causes = summary["deaths_by_cause"].most_common(5)
    if causes:
        ax3.barh([c[0] for c in causes][::-1], [c[1] for c in causes][::-1], color=ACCENT2)
    fig2.tight_layout()
    specs.append(
        ChartSpec(
            "difficulty", "图 2  难度分布与死因统计", "02_难度分布.png", fig2,
            "左图为阵亡时所在层数，峰值出现处即难度陡增点；右图为击杀玩家的怪物类型。",
        )
    )

    # ---------------------------------------------------------- 图 3：效率散点
    fig3 = Figure(figsize=(8, 4.2), dpi=100, facecolor=BG)
    ax4 = fig3.add_subplot(111)
    _style_axes(ax4, "回合数与击杀数的关系", "回合数", "击杀数")
    wins = df["is_win"].tolist() if "is_win" in df.columns else [False] * len(df)
    point_colors = [ACCENT if win else ACCENT2 for win in wins]
    ax4.scatter(df["turns"], df["kills"], c=point_colors, s=28, alpha=0.85, edgecolors="none")
    if len(df) >= 2 and df["turns"].std() > 0:
        import numpy as np

        z = np.polyfit(df["turns"].astype(float), df["kills"].astype(float), 1)
        p = np.poly1d(z)
        line_x = [float(df["turns"].min()), float(df["turns"].max())]
        ax4.plot(line_x, p(line_x), color=ACCENT3, linewidth=1.5, linestyle="--", label="线性拟合")
        ax4.legend(frameon=False, fontsize=9, labelcolor=FG)
    fig3.tight_layout()
    specs.append(
        ChartSpec(
            "efficiency", "图 3  回合数与击杀数", "03_战斗效率.png", fig3,
            "每个点代表一局。斜率反映单位回合的击杀效率，离群点多为「暴毙局」（回合少、击杀多）。",
        )
    )

    # ---------------------------------------------------------- 图 4：各层节奏
    fig4 = Figure(figsize=(8, 4.2), dpi=100, facecolor=BG)
    ax5 = fig4.add_subplot(111)
    _style_axes(ax5, "各层平均停留回合", "层数", "平均回合数")
    stay = analyzer.floor_average_stay()
    if stay:
        keys = list(stay.keys())
        ax5.bar([str(k) for k in keys], [stay[k] for k in keys], color=ACCENT3)
        mean_stay = sum(stay.values()) / len(stay)
        ax5.axhline(mean_stay, color=ACCENT2, linestyle="--", linewidth=1)
        # 分类轴的横坐标是 0..n-1，不是楼层号本身；标注放在左上角空白处
        ax5.text(
            -0.42, mean_stay, f"平均 {mean_stay:.0f} 回合", color=ACCENT2,
            fontsize=9, va="bottom", ha="left",
        )
    fig4.tight_layout()
    specs.append(
        ChartSpec(
            "rhythm", "图 4  各层平均停留回合", "04_分层节奏.png", fig4,
            "柱高表示玩家在该层的平均停留回合。过高的层说明探索成本大，过低说明缺少内容。",
        )
    )

    # ---------------------------------------------------------- 图 5：结果构成
    fig5 = Figure(figsize=(6.8, 4.6), dpi=100, facecolor=BG)
    ax6 = fig5.add_subplot(111)
    ax6.set_title("对局结果构成", fontsize=14, color=FG, pad=12, fontweight="bold")
    mapping = {"win": "通关", "dead": "阵亡", "timeout": "超时", "quit": "中途退出"}
    counts: dict[str, int] = {}
    for result, count in df["result"].value_counts().items():
        counts[mapping.get(str(result), str(result))] = int(count)
    if counts:
        wedges, _texts, autotexts = ax6.pie(
            list(counts.values()),
            labels=list(counts.keys()),
            autopct="%1.0f%%",
            pctdistance=0.80,
            colors=[ACCENT, ACCENT2, ACCENT3, "#9aa4b2"][: len(counts)],
            startangle=90,
            counterclock=False,
            wedgeprops={"width": 0.40, "edgecolor": BG, "linewidth": 2},
            textprops={"color": FG, "fontsize": 10},
        )
        for text in autotexts:
            text.set_color("#ffffff")
            text.set_fontsize(9)
    ax6.text(
        0, 0.08, f"{summary['total']} 局", ha="center", va="center", color=FG, fontsize=11
    )
    ax6.text(
        0, -0.16, f"通关率 {summary['win_rate']:.1%}",
        ha="center", va="center", color=ACCENT, fontsize=10, fontweight="bold",
    )
    fig5.tight_layout()
    specs.append(
        ChartSpec(
            "result", "图 5  对局结果构成", "05_结果构成.png", fig5,
            "环形图展示全部对局的结局分布，中心标注总体通关率。",
        )
    )

    return specs


def close_figures(specs: list[ChartSpec]) -> None:
    """释放 Figure 占用的内存。"""
    for spec in specs:
        plt.close(spec.figure)
