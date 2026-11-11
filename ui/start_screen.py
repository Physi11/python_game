"""开始界面（覆盖层）。

实现方式：一个铺满主窗口的 ``tk.Frame``，用 ``place(relwidth=1, relheight=1)``
压在游戏界面之上。相比"先开一个独立 Tk 再销毁"的常见写法，这样做的原因是：

* 只有一个 ``Tk`` 根窗口，全屏切换、DPI 缩放、主题样式都只需要处理一份；
* 覆盖层销毁后底下就是初始化好的游戏界面，不需要重建窗口，不会闪一下；
* 以后想加"暂停菜单"可以直接复用同一套覆盖层套路。

按钮回调全部由 ``App`` 注入，这个模块不认识 ``GameState``——它只负责长相。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from dungeon import config

from . import theme as th


class StartOverlay(tk.Frame):
    """盖在游戏界面上的开始菜单。"""

    def __init__(
        self,
        master: tk.Misc,
        theme: th.Theme,
        on_start: Callable[[], None],
        on_load: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=th.BG)
        self.theme = theme
        self._build(on_start, on_load, on_settings, on_quit)

    # ------------------------------------------------------------ 装配
    def _build(
        self,
        on_start: Callable[[], None],
        on_load: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        # 背景装饰：用画布画一层淡淡的格子，暗示"地牢"，同时不抢文字注意力
        backdrop = tk.Canvas(self, bg=th.BG, highlightthickness=0, bd=0)
        backdrop.place(relwidth=1, relheight=1)
        self._paint_backdrop(backdrop)
        backdrop.bind("<Configure>", lambda _e: self._paint_backdrop(backdrop))

        card = tk.Frame(self, bg=th.PANEL, padx=56, pady=44)
        card.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            card,
            text="地 下 城 探 险",
            bg=th.PANEL,
            fg=th.ACCENT,
            font=(self.theme.family, 30, "bold"),
        ).pack()
        tk.Label(
            card,
            text="DUNGEON DELVE",
            bg=th.PANEL,
            fg="#4c5a72",
            font=(self.theme.family, 11),
        ).pack(pady=(2, 6))
        tk.Label(
            card,
            text=f"深入 {config.MAX_FLOOR} 层，击败深渊领主",
            bg=th.PANEL,
            fg=th.TEXT_DIM,
            font=self.theme.small,
        ).pack(pady=(0, 26))

        buttons = (
            ("开始新游戏", on_start, "Accent.TButton"),
            ("读取存档", on_load, "TButton"),
            ("设　　置", on_settings, "TButton"),
            ("退出游戏", on_quit, "TButton"),
        )
        for text, command, style in buttons:
            ttk.Button(card, text=text, style=style, command=command, width=22).pack(
                pady=5
            )

        tk.Label(
            card,
            text="F11 切换全屏　·　? 查看操作说明\n设置会保存在 data/settings.json",
            bg=th.PANEL,
            fg="#5a6678",
            font=self.theme.tiny,
            justify="center",
            wraplength=420,
        ).pack(pady=(24, 0))

        self.bind("<Escape>", lambda _e: None)   # 开始界面按 Esc 不做任何事

    def _paint_backdrop(self, canvas: tk.Canvas) -> None:
        """画一层稀疏的暗色网格 + 几个若隐若现的地牢符号。"""
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        step = 40
        for x in range(0, width, step):
            canvas.create_line(x, 0, x, height, fill="#141821")
        for y in range(0, height, step):
            canvas.create_line(0, y, width, y, fill="#141821")
        # 几个装饰符号，位置按比例摆放，缩放窗口时依然分布均匀
        for rx, ry, glyph, color in (
            (0.12, 0.22, "@", "#1d3a3a"),
            (0.88, 0.30, "W", "#3a1d1d"),
            (0.18, 0.78, "↓", "#3a331d"),
            (0.84, 0.74, "≈", "#1d3a30"),
        ):
            canvas.create_text(
                width * rx,
                height * ry,
                text=glyph,
                fill=color,
                font=(self.theme.family, 46, "bold"),
            )


def version_text() -> str:
    """开始界面页脚用的版本号（直接读配置，避免两处维护）。"""
    return f"v{config.SAVE_VERSION}.0"
