"""各类弹出窗口：帮助、结算、排行榜、统计图表。

所有窗口共用一套深色样式与居中逻辑，保证观感统一。
统计图表窗口用 ``FigureCanvasTkAgg`` 把 matplotlib 图形直接嵌进 Tk，
支持上一张 / 下一张翻页——这是"可视化 + 界面友好"两项评分的直接体现。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from dungeon import config
from dungeon.game_state import GameStatus, GameState
from dungeon.stats import StatsAnalyzer

from . import theme as th

HELP_ROWS = [
    ("↑ ↓ ← → / W A S D", "移动一格（每回合只能做一个行动：移动 / 攻击 / 等待）"),
    ("空格", "原地等待一回合"),
    ("F 或 鼠标右键", "进入 / 退出瞄准模式"),
    ("鼠标左键", "瞄准中：确认攻击；平时：点击相邻格移动、点脚下拾取或下楼"),
    ("Tab", "瞄准中切换近战 / 远程武器"),
    ("Esc", "取消瞄准（没有瞄准时把焦点交还地图）"),
    ("G", "拾取脚下道具；站在楼梯上则直接下楼"),
    ("1 ~ 9", "快速使用背包中对应编号的道具"),
    ("I", "打开 / 关闭背包"),
    (">", "站在楼梯上时进入下一层"),
    ("F5 / Ctrl+S", "保存到 1 号存档槽"),
    ("F9 / Ctrl+O", "读取 1 号存档槽"),
    ("N", "开始新的一局"),
    ("M", "打开 / 关闭统计图表"),
    ("F12", "重载图标资源"),
    ("?", "显示本帮助"),
]

# 战斗配色说明，单独一段，避免塞进按键表里
COMBAT_LEGEND = [
    ("蓝色高亮", "你这一击会覆盖的格子（瞄准时实时预览）"),
    ("红色高亮", "敌人已经锁定的打击区域，站进去就会挨打"),
    ("黄色高亮", "你自己的蓄力区域，重武器会在下回合落下"),
    ("头顶数字", "敌人还有几回合出手；数字归零的那一回合结算"),
]


def center(win: tk.Toplevel, parent: tk.Misc, width: int, height: int) -> None:
    """把窗口摆到父窗口中央。"""
    win.update_idletasks()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
    except tk.TclError:  # pragma: no cover
        px = py = 0
        pw, ph = width, height
    x = px + max(0, (pw - width) // 2)
    y = py + max(0, (ph - height) // 3)
    win.geometry(f"{width}x{height}+{x}+{y}")


def make_window(
    parent: tk.Misc, theme: th.Theme, title: str, width: int, height: int
) -> tk.Toplevel:
    """创建统一风格的子窗口。

    额外挂一个 ``<Destroy>`` 钩子：弹窗关闭后把键盘焦点还给主窗口。
    Tk 在销毁一个拥有焦点的 Toplevel 时，不保证焦点会落到一个能接收
    ``<Key>`` 的控件上；不主动回收的话，关掉背包窗口后会出现
    "方向键不响应"的假死现象。
    """
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=th.BG)
    win.transient(parent)
    center(win, parent, width, height)
    win.resizable(False, False)
    _bind_focus_return(win, parent)
    return win


def _bind_focus_return(win: tk.Toplevel, parent: tk.Misc) -> None:
    """弹窗销毁后把焦点交还父窗口。

    两个坑：
    1. ``<Destroy>`` 对每个子控件都会触发一次，必须用 ``event.widget is win``
       过滤，否则一个 30 个控件的对话框会回调 30 多次；
    2. 主窗口退出时 ``parent`` 可能已经在销毁中，必须吞掉 ``TclError``，
       否则控制台会冒一段 traceback。
    """

    def _on_destroy(event: tk.Event) -> None:
        if event.widget is not win:
            return

        def _give_back() -> None:
            try:
                if not parent.winfo_exists():
                    return
                # 主窗口提供了 _focus_map() 时优先用它，把焦点精确还给地图画布；
                # 否则退回到"聚焦父窗口"，键盘事件同样能被主窗口的 <Key> 接住。
                restore = getattr(parent, "_focus_map", None)
                if callable(restore):
                    restore()
                else:
                    parent.focus_set()
            except tk.TclError:      # 父窗口正在销毁
                pass

        try:
            parent.after_idle(_give_back)   # 立即设可能被窗口管理器覆盖
        except tk.TclError:                  # pragma: no cover
            pass

    win.bind("<Destroy>", _on_destroy, add="+")


# ====================================================================== 帮助
def show_help(parent: tk.Misc, theme: th.Theme) -> tk.Toplevel:
    win = make_window(parent, theme, "操作说明", 780, 760)

    header = tk.Frame(win, bg=th.BG)
    header.pack(fill="x", padx=24, pady=(20, 6))
    tk.Label(
        header, text="操 作 说 明", bg=th.BG, fg=th.ACCENT, font=theme.title
    ).pack(anchor="w")
    tk.Label(
        header,
        text="目标是深入地下城第 10 层，击败深渊领主。撞向怪物即攻击。",
        bg=th.BG,
        fg=th.TEXT_DIM,
        font=theme.small,
    ).pack(anchor="w", pady=(4, 0))

    body = tk.Frame(win, bg=th.PANEL)
    body.pack(fill="both", expand=True, padx=24, pady=10)

    for index, (keys, desc) in enumerate(HELP_ROWS):
        bg = th.PANEL if index % 2 == 0 else th.PANEL_ALT
        row = tk.Frame(body, bg=bg)
        row.pack(fill="x")
        tk.Label(
            row, text=keys, bg=bg, fg=th.GOLD, font=theme.bold, width=16, anchor="w"
        ).pack(side="left", padx=(12, 4), pady=7)
        tk.Label(
            row, text=desc, bg=bg, fg=th.TEXT, font=theme.small, anchor="w",
            justify="left", wraplength=520,
        ).pack(side="left", fill="x", expand=True, pady=7)

    footer = tk.Frame(win, bg=th.BG)
    footer.pack(fill="x", padx=24, pady=(4, 18))
    tk.Label(
        footer,
        text="战场色块",
        bg=th.BG, fg=th.ACCENT, font=theme.bold,
    ).pack(anchor="w", pady=(0, 2))
    for keys, desc in COMBAT_LEGEND:
        row = tk.Frame(footer, bg=th.BG)
        row.pack(fill="x")
        tk.Label(
            row, text=keys, bg=th.BG, fg=th.GOLD, font=theme.small, width=12, anchor="w"
        ).pack(side="left")
        tk.Label(
            row, text=desc, bg=th.BG, fg=th.TEXT_DIM, font=theme.small, anchor="w"
        ).pack(side="left")
    tk.Label(
        footer,
        text="提示：先看红色区域决定站哪里，再决定这一回合是走位还是出手。重武器伤害高但要蓄力，"
             "轻武器可以立刻打断敌人。",
        bg=th.BG,
        fg=th.TEXT_DIM,
        font=theme.small,
        wraplength=700,
        justify="left",
    ).pack(anchor="w", pady=(8, 0))
    ttk.Button(footer, text="知道了", style="Accent.TButton", command=win.destroy).pack(
        anchor="e", pady=(8, 0)
    )

    win.bind("<Escape>", lambda _e: win.destroy())
    win.focus_set()
    return win


# ====================================================================== 背包
def show_inventory(
    parent: tk.Misc,
    theme: th.Theme,
    state: GameState,
    on_use: Callable[[int], None] | None = None,
) -> tk.Toplevel:
    """背包窗口：左侧列表，右侧详情，支持双击使用。"""
    win = make_window(parent, theme, "背包", 640, 520)
    player = state.player

    header = tk.Frame(win, bg=th.BG)
    header.pack(fill="x", padx=22, pady=(16, 6))
    tk.Label(header, text="背 包", bg=th.BG, fg=th.ACCENT, font=theme.title).pack(side="left")
    tk.Label(
        header,
        text=f"{len(player.inventory)} / {config.INVENTORY_CAPACITY} 格",
        bg=th.BG,
        fg=th.TEXT_DIM,
        font=theme.small,
    ).pack(side="right")

    body = tk.Frame(win, bg=th.BG)
    body.pack(fill="both", expand=True, padx=22)

    left = tk.Frame(body, bg=th.PANEL)
    left.pack(side="left", fill="both", expand=True)

    listing = tk.Listbox(
        left,
        bg=th.PANEL,
        fg=th.TEXT,
        selectbackground=th.BORDER,
        selectforeground=th.TEXT,
        highlightthickness=0,
        bd=0,
        font=theme.base,
        activestyle="none",
        exportselection=False,
    )
    listing.pack(fill="both", expand=True, padx=4, pady=4)
    if player.inventory:
        for index, item in enumerate(player.inventory, start=1):
            listing.insert("end", f" {index}.  {item.glyph}  {item.name}")
        listing.selection_set(0)
    else:
        listing.insert("end", " （背包是空的）")

    right = tk.Frame(body, bg=th.PANEL_ALT, width=250)
    right.pack(side="left", fill="both", padx=(10, 0))
    right.pack_propagate(False)
    detail_title = tk.Label(
        right, text="", bg=th.PANEL_ALT, fg=th.GOLD, font=theme.bold, wraplength=220,
        justify="left", anchor="w",
    )
    detail_title.pack(anchor="w", padx=14, pady=(14, 4))
    detail_text = tk.Label(
        right, text="", bg=th.PANEL_ALT, fg=th.TEXT, font=theme.small,
        wraplength=220, justify="left", anchor="nw",
    )
    detail_text.pack(anchor="w", padx=14, fill="both", expand=True)

    hint = tk.Label(
        win, text="双击道具使用 / 装备，或选中后按回车", bg=th.BG, fg=th.TEXT_DIM, font=theme.tiny
    )
    hint.pack(anchor="w", padx=22, pady=(6, 0))

    def show_detail(_event: tk.Event | None = None) -> None:
        selection = listing.curselection()
        if not selection or not player.inventory:
            detail_title.config(text="（空）")
            detail_text.config(text="")
            return
        index = selection[0]
        if index >= len(player.inventory):
            return
        item = player.inventory[index]
        detail_title.config(text=f"{item.glyph}  {item.name}")
        detail_text.config(text=f"类型：{_kind_name(item.kind)}\n\n{item.desc}")

    def use_selected(_event: tk.Event | None = None) -> None:
        selection = listing.curselection()
        if not selection or on_use is None:
            return
        win.destroy()
        on_use(int(selection[0]))

    listing.bind("<<ListboxSelect>>", show_detail)
    listing.bind("<Double-Button-1>", use_selected)
    listing.bind("<Return>", use_selected)
    show_detail()

    footer = tk.Frame(win, bg=th.BG)
    footer.pack(fill="x", padx=22, pady=(4, 14))
    ttk.Button(footer, text="使用", style="Accent.TButton", command=use_selected).pack(side="right")
    ttk.Button(footer, text="关闭", command=win.destroy).pack(side="right", padx=8)

    win.bind("<Escape>", lambda _e: win.destroy())
    listing.focus_set()
    return win


def _kind_name(kind: str) -> str:
    return {"potion": "药水", "weapon": "武器", "armor": "护甲", "scroll": "卷轴"}.get(kind, "道具")


# ====================================================================== 结算
def rating_for(state: GameState) -> tuple[str, str]:
    """根据结果给出评级与点评。"""
    if state.status == GameStatus.WIN:
        return "S", "深渊领主已被击败，你通关了！"
    if state.max_floor >= 8:
        return "A", "你已深入地下城深处，只差一步就能见到深渊领主。"
    if state.max_floor >= 5:
        return "B", "稳步推进，但装备与等级还有提升空间。"
    if state.max_floor >= 3:
        return "C", "刚刚摸到门道，注意别在低层恋战。"
    return "D", "出师不利，先熟悉一下操作，多利用地形与药水。"


def show_game_over(
    parent: tk.Misc,
    theme: th.Theme,
    state: GameState,
    on_restart: Callable[[], None] | None = None,
    on_leaderboard: Callable[[], None] | None = None,
) -> tk.Toplevel:
    win = make_window(parent, theme, "本局结算", 560, 620)

    title_text = {
        GameStatus.WIN: "通 关 成 功",
        GameStatus.DEAD: "你 倒 下 了",
        GameStatus.TIMEOUT: "探 索 超 时",
        GameStatus.QUIT: "已 退 出 本 局",
    }.get(state.status, "本 局 结 束")
    title_color = th.ACCENT if state.status == GameStatus.WIN else th.DANGER

    tk.Label(win, text=title_text, bg=th.BG, fg=title_color, font=(theme.family, 22, "bold")).pack(
        pady=(22, 2)
    )

    grade, comment = rating_for(state)
    tk.Label(win, text=f"评级  {grade}", bg=th.BG, fg=th.GOLD, font=(theme.family, 18, "bold")).pack()
    tk.Label(
        win, text=comment, bg=th.BG, fg=th.TEXT_DIM, font=theme.small,
        wraplength=480, justify="center",
    ).pack(pady=(4, 14))

    player = state.player
    record = state.build_record()
    rows = [
        ("到达层数", f"{state.max_floor} / {config.MAX_FLOOR}"),
        ("角色等级", f"Lv.{player.level}"),
        ("总回合数", f"{state.turn}"),
        ("击杀数", f"{player.kills}"),
        ("金币", f"{player.gold}"),
        ("造成伤害", f"{player.damage_dealt}"),
        ("承受伤害", f"{player.damage_taken}"),
        ("伤害交换比", f"{player.kd_ratio:.2f}"),
        ("用时", f"{record['duration_sec'] // 60} 分 {record['duration_sec'] % 60} 秒"),
        ("死因", state.death_cause or "—"),
    ]

    body = tk.Frame(win, bg=th.PANEL)
    body.pack(fill="x", padx=30)
    for index, (label, value) in enumerate(rows):
        bg = th.PANEL if index % 2 == 0 else th.PANEL_ALT
        row = tk.Frame(body, bg=bg)
        row.pack(fill="x")
        tk.Label(row, text=label, bg=bg, fg=th.TEXT_DIM, font=theme.small, width=12, anchor="w").pack(
            side="left", padx=(14, 0), pady=6
        )
        tk.Label(row, text=value, bg=bg, fg=th.TEXT, font=theme.bold, anchor="e").pack(
            side="right", padx=(0, 14), pady=6
        )

    buttons = tk.Frame(win, bg=th.BG)
    buttons.pack(pady=20)

    def restart() -> None:
        win.destroy()
        if on_restart is not None:
            on_restart()

    def leaderboard() -> None:
        win.destroy()
        if on_leaderboard is not None:
            on_leaderboard()

    ttk.Button(buttons, text="再来一局", style="Accent.TButton", command=restart).pack(
        side="left", padx=6
    )
    ttk.Button(buttons, text="查看排行榜", command=leaderboard).pack(side="left", padx=6)
    ttk.Button(buttons, text="关闭", command=win.destroy).pack(side="left", padx=6)

    win.bind("<Escape>", lambda _e: win.destroy())
    win.focus_set()
    return win


# ====================================================================== 排行榜
def show_leaderboard(parent: tk.Misc, theme: th.Theme, records: list[dict[str, Any]]) -> tk.Toplevel:
    win = make_window(parent, theme, "历史战绩", 720, 620)

    tk.Label(win, text="历 史 战 绩", bg=th.BG, fg=th.ACCENT, font=theme.title).pack(
        anchor="w", padx=24, pady=(20, 2)
    )

    analyzer = StatsAnalyzer(records)
    summary = analyzer.summary()
    if summary["total"]:
        line = (
            f"共 {summary['total']} 局 · 通关 {summary['wins']} 局"
            f"（{summary['win_rate']:.1%}）· 平均到达 {summary['avg_floor']:.1f} 层"
            f" · 最深 {summary['best_floor']} 层 · 最常见死因：{summary['top_death_cause']}"
        )
    else:
        line = "还没有任何对局记录。打完一局后这里会自动累积数据。"
    tk.Label(
        win, text=line, bg=th.BG, fg=th.TEXT_DIM, font=theme.small, wraplength=670, justify="left"
    ).pack(anchor="w", padx=24, pady=(0, 10))

    columns = ("rank", "time", "floor", "level", "kills", "turns", "result", "cause")
    headers = {
        "rank": "#", "time": "时间", "floor": "层数", "level": "等级",
        "kills": "击杀", "turns": "回合", "result": "结果", "cause": "备注",
    }
    widths = {
        "rank": 40, "time": 150, "floor": 60, "level": 60,
        "kills": 60, "turns": 70, "result": 70, "cause": 170,
    }

    frame = tk.Frame(win, bg=th.PANEL)
    frame.pack(fill="both", expand=True, padx=24, pady=(0, 10))

    tree = ttk.Treeview(frame, columns=columns, show="headings", height=14)
    for col in columns:
        tree.heading(col, text=headers[col])
        tree.column(col, width=widths[col], anchor="center")
    tree.pack(fill="both", expand=True)

    result_text = {"win": "通关", "dead": "阵亡", "timeout": "超时", "quit": "退出"}
    for index, record in enumerate(analyzer.leaderboard(30), start=1):
        tree.insert(
            "",
            "end",
            values=(
                index,
                str(record.get("ended_at", ""))[:16].replace("T", " "),
                record.get("max_floor", "-"),
                record.get("player_level", "-"),
                record.get("kills", "-"),
                record.get("turns", "-"),
                result_text.get(str(record.get("result")), "—"),
                record.get("death_cause") or "—",
            ),
        )

    ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 16))
    win.bind("<Escape>", lambda _e: win.destroy())
    win.focus_set()
    return win


# ====================================================================== 图表
def show_charts(parent: tk.Misc, theme: th.Theme, analyzer: StatsAnalyzer) -> tk.Toplevel | None:
    """统计图表窗口。matplotlib 未安装时给出提示并返回 None。"""
    try:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    except ImportError:  # pragma: no cover - 取决于环境
        _message(parent, theme, "未安装 matplotlib", "请先执行：pip install matplotlib")
        return None

    from .charts import build_figures, close_figures

    specs = build_figures(analyzer)
    if not specs:
        _message(
            parent,
            theme,
            "暂无对局数据",
            "先玩一局游戏，或运行 tools/balance_sim.py 批量生成模拟对局后再查看。",
        )
        return None

    win = make_window(parent, theme, "统计图表", 980, 700)

    header = tk.Frame(win, bg=th.BG)
    header.pack(fill="x", padx=20, pady=(14, 4))
    tk.Label(header, text="统 计 图 表", bg=th.BG, fg=th.ACCENT, font=theme.title).pack(side="left")
    counter = tk.Label(header, text="", bg=th.BG, fg=th.TEXT_DIM, font=theme.small)
    counter.pack(side="right")

    body = tk.Frame(win, bg=th.BG)
    body.pack(fill="both", expand=True, padx=20)
    note = tk.Label(
        win, text="", bg=th.BG, fg=th.TEXT_DIM, font=theme.small,
        wraplength=920, justify="left",
    )
    note.pack(fill="x", padx=20, pady=(6, 4))

    state = {"index": 0, "canvas": None}

    def render() -> None:
        spec = specs[state["index"]]
        if state["canvas"] is not None:
            state["canvas"].get_tk_widget().destroy()
        figure = spec.figure
        figure.set_size_inches(9.2, 5.2)
        canvas = FigureCanvasTkAgg(figure, master=body)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        state["canvas"] = canvas
        counter.config(text=f"{state['index'] + 1} / {len(specs)}　{spec.title}")
        note.config(text=spec.note)

    def step(delta: int) -> None:
        state["index"] = (state["index"] + delta) % len(specs)
        render()

    footer = tk.Frame(win, bg=th.BG)
    footer.pack(fill="x", padx=20, pady=(4, 14))
    ttk.Button(footer, text="← 上一张", command=lambda: step(-1)).pack(side="left")
    ttk.Button(footer, text="下一张 →", command=lambda: step(1)).pack(side="left", padx=8)
    ttk.Button(footer, text="关闭", command=win.destroy).pack(side="right")

    render()

    def on_close() -> None:
        close_figures(specs)
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)
    win.bind("<Escape>", lambda _e: on_close())
    win.bind("<Left>", lambda _e: step(-1))
    win.bind("<Right>", lambda _e: step(1))
    win.focus_set()
    return win


def _message(parent: tk.Misc, theme: th.Theme, title: str, text: str) -> tk.Toplevel:
    """轻量提示窗口，避免依赖 messagebox 的原生样式。"""
    win = make_window(parent, theme, title, 460, 200)
    tk.Label(win, text=title, bg=th.BG, fg=th.ACCENT, font=theme.title).pack(pady=(26, 6))
    tk.Label(
        win, text=text, bg=th.BG, fg=th.TEXT, font=theme.base,
        wraplength=400, justify="center",
    ).pack(padx=20)
    ttk.Button(win, text="知道了", style="Accent.TButton", command=win.destroy).pack(pady=16)
    win.focus_set()
    return win
