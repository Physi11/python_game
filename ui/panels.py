"""右侧状态面板与底部日志面板。

``StatusPanel`` 用自绘血条 + 数值网格展示角色状态，背包用可双击的列表框
呈现（比 24 个小格子更容易看清道具名称，也更符合"提示信息清晰"的要求）。

``LogPanel`` 用 ``tk.Text`` 加 tag 着色，战斗、道具、升级、危险四类信息
用不同颜色区分，并自动滚动到底部。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from dungeon import config

from . import theme as th

BAR_W = 260


class StatusPanel(ttk.Frame):
    """角色状态 + 装备 + 背包。"""

    def __init__(
        self,
        master: tk.Misc,
        theme: th.Theme,
        on_use_item: Callable[[int], None] | None = None,
        on_hover_item: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, style="Panel.TFrame", width=config.SIDE_PANEL_W)
        self.theme = theme
        self._on_use_item = on_use_item
        self._on_hover_item = on_hover_item
        self._state: Any = None
        self._items: list[Any] = []      # 上一次刷新时的背包内容，用于按身份恢复选中

        self.pack_propagate(False)
        self._build()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        pad = {"padx": 16}
        header = ttk.Label(self, text="冒 险 者", style="Title.TLabel")
        header.pack(anchor="w", pady=(14, 2), **pad)

        self.lbl_floor = ttk.Label(self, text="第 1 层", style="Dim.TLabel")
        self.lbl_floor.pack(anchor="w", **pad)

        # 血条
        self.hp_canvas = tk.Canvas(
            self, width=BAR_W, height=22, bg=th.PANEL, highlightthickness=0
        )
        self.hp_canvas.pack(pady=(10, 0), **pad)
        self.hp_bar_bg = self.hp_canvas.create_rectangle(
            0, 6, BAR_W, 21, fill=th.PANEL_ALT, outline=""
        )
        self.hp_bar = self.hp_canvas.create_rectangle(
            0, 6, BAR_W, 21, fill=th.HP_GREEN, outline=""
        )
        self.hp_text = self.hp_canvas.create_text(
            BAR_W / 2, 14, text="", fill=th.TEXT, font=self.theme.tiny
        )

        # 经验条
        self.exp_canvas = tk.Canvas(
            self, width=BAR_W, height=12, bg=th.PANEL, highlightthickness=0
        )
        self.exp_canvas.pack(pady=(4, 0), **pad)
        self.exp_canvas.create_rectangle(0, 3, BAR_W, 9, fill=th.PANEL_ALT, outline="")
        self.exp_bar = self.exp_canvas.create_rectangle(0, 3, 0, 9, fill=th.EXP_BLUE, outline="")
        self.exp_text = self.exp_canvas.create_text(
            BAR_W / 2, 6, text="", fill=th.TEXT_DIM, font=self.theme.tiny
        )

        # 数值网格（2 行 × 2 列，避免在 300 像素宽的面板里挤成一行）
        grid = ttk.Frame(self, style="Panel.TFrame")
        grid.pack(fill="x", pady=(10, 4), **pad)
        self.value_labels: dict[str, ttk.Label] = {}
        for index, (key, title) in enumerate(
            [("atk", "攻击"), ("def", "防御"), ("gold", "金币"), ("turns", "回合")]
        ):
            row, col = divmod(index, 2)
            ttk.Label(grid, text=title, style="Dim.TLabel").grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2
            )
            label = ttk.Label(grid, text="0", style="TLabel", font=self.theme.bold)
            label.grid(row=row, column=col * 2 + 1, sticky="w", padx=(0, 24), pady=2)
            self.value_labels[key] = label

        # 装备
        ttk.Label(self, text="装 备", style="Title.TLabel").pack(anchor="w", **pad)
        self.lbl_weapon = ttk.Label(self, text="近战：—", style="Dim.TLabel")
        self.lbl_weapon.pack(anchor="w", **pad)
        self.lbl_ranged = ttk.Label(self, text="远程：—", style="Dim.TLabel")
        self.lbl_ranged.pack(anchor="w", **pad)
        self.lbl_armor = ttk.Label(self, text="护甲：—", style="Dim.TLabel")
        self.lbl_armor.pack(anchor="w", **pad)
        self.lbl_charge = ttk.Label(self, text="", style="Dim.TLabel", foreground=th.CHARGE)
        self.lbl_charge.pack(anchor="w", pady=(0, 8), **pad)

        # 背包
        ttk.Label(self, text="背 包（双击使用）", style="Title.TLabel").pack(anchor="w", **pad)
        list_frame = ttk.Frame(self, style="Panel.TFrame")
        list_frame.pack(fill="both", expand=True, padx=16, pady=(2, 6))
        self.item_list = tk.Listbox(
            list_frame,
            height=8,
            bg=th.PANEL_ALT,
            fg=th.TEXT,
            selectbackground=th.BORDER,
            selectforeground=th.TEXT,
            highlightthickness=0,
            bd=0,
            font=self.theme.small,
            activestyle="none",
            exportselection=False,   # 焦点移走后仍保留选中高亮，用户不会"找不到刚选的那行"
        )
        self.item_list.pack(fill="both", expand=True)
        self.item_list.bind("<Double-Button-1>", self._use_selected)
        self.item_list.bind("<Return>", self._use_selected)
        self.item_list.bind("<Motion>", self._hover_item)
        ttk.Label(
            self,
            text=f"数字键 1~9 快速使用 · 容量 {config.INVENTORY_CAPACITY}",
            style="Dim.TLabel",
        ).pack(anchor="w", padx=16, pady=(0, 12))

    # ------------------------------------------------------------ 交互
    def _use_selected(self, event: tk.Event | None = None) -> str:
        """使用选中的道具。

        返回值必须是 ``"break"``：Tk 的 Text/Listbox 类绑定不会中断事件传播，
        回车会继续流向主窗口的 ``<Key>``，被当成"未绑定按键"报错。
        """
        selection = self.item_list.curselection()
        if selection and self._on_use_item is not None:
            self._on_use_item(int(selection[0]))
        return "break"

    def _hover_item(self, event: tk.Event) -> None:
        if self._on_hover_item is None or self._state is None:
            return
        index = self.item_list.nearest(event.y)
        inventory = self._state.player.inventory
        if 0 <= index < len(inventory):
            self._on_hover_item(inventory[index].describe())

    # ------------------------------------------------------------ 刷新
    def refresh(self, state: Any) -> None:
        self._state = state
        player = state.player

        self.lbl_floor.config(
            text=f"第 {state.floor} 层 · Lv.{player.level} · 种子 {state.rng.seed}"
        )

        ratio = player.hp_ratio
        color = th.HP_GREEN if ratio > 0.6 else th.HP_YELLOW if ratio > 0.3 else th.HP_RED
        self.hp_canvas.coords(self.hp_bar, 0, 6, max(0, BAR_W * ratio), 21)
        self.hp_canvas.itemconfig(self.hp_bar, fill=color)
        self.hp_canvas.itemconfig(
            self.hp_text, text=f"HP {player.hp} / {player.max_hp}", fill=th.TEXT
        )

        exp_need = max(1, player.exp_to_next)
        exp_ratio = min(1.0, player.exp / exp_need)
        self.exp_canvas.coords(self.exp_bar, 0, 3, BAR_W * exp_ratio, 9)
        self.exp_canvas.itemconfig(
            self.exp_text, text=f"EXP {player.exp} / {exp_need}"
        )

        self.value_labels["atk"].config(text=str(player.total_atk()))
        self.value_labels["def"].config(text=str(player.total_def()))
        self.value_labels["gold"].config(text=str(player.gold))
        self.value_labels["turns"].config(text=str(state.turn))

        melee = player.equipment.get("weapon")
        ranged = player.equipment.get("ranged")
        armor = player.equipment.get("armor")
        self.lbl_weapon.config(
            text=(
                f"近战：{melee.name}（+{melee.atk_bonus} · {melee.range_text}）"
                if melee else "近战：—"
            )
        )
        self.lbl_ranged.config(
            text=(
                f"远程：{ranged.name}（+{ranged.atk_bonus} · {ranged.range_text}）"
                if ranged else "远程：—"
            )
        )
        self.lbl_armor.config(
            text=f"护甲：{armor.name}（+{armor.def_bonus}）" if armor else "护甲：—"
        )
        if player.charge_left > 0:
            self.lbl_charge.config(text=f"⚡ 蓄力中，{player.charge_left} 回合后落下")
        else:
            self.lbl_charge.config(text="")

        # 背包重新填充；只在内容变化时重建，避免每次刷新都打断选中状态
        entries = [f"{i + 1}. {item.glyph} {item.name}" for i, item in enumerate(player.inventory)]
        if entries != list(self.item_list.get(0, "end")):
            # 用"道具对象身份"而不是下标恢复选中：用掉一件道具后列表会变短，
            # 沿用旧下标会指向另一件道具，再双击就用到错的东西
            selection = self.item_list.curselection()
            selected = (
                self._items[selection[0]]
                if selection and selection[0] < len(self._items)
                else None
            )
            self.item_list.delete(0, "end")
            for text in entries:
                self.item_list.insert("end", text)
            restored = False
            if selected is not None:
                for index, item in enumerate(player.inventory):
                    if item is selected:
                        self.item_list.selection_set(index)
                        restored = True
                        break
            if not restored:
                self.item_list.selection_clear(0, "end")
        self._items = list(player.inventory)


class LogPanel(ttk.Frame):
    """消息日志。"""

    MAX_LINES = 300

    def __init__(self, master: tk.Misc, theme: th.Theme) -> None:
        super().__init__(master, style="Panel.TFrame")
        self.theme = theme
        self._shown = 0

        wrapper = tk.Frame(self, bg=th.PANEL)
        wrapper.pack(fill="both", expand=True, padx=10, pady=(6, 4))

        self.text = tk.Text(
            wrapper,
            height=6,
            bg=th.PANEL,
            fg=th.TEXT,
            insertbackground=th.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="word",
            font=self.theme.small,
            state="disabled",
        )
        self.text.pack(fill="both", expand=True)

        for tag, color in th.LOG_COLORS.items():
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("system", foreground=th.TEXT_DIM)

    def append(self, entries: list[tuple[str, str]]) -> None:
        """追加日志并滚到底部。"""
        if not entries:
            return
        self.text.configure(state="normal")
        for text, tag in entries:
            self.text.insert("end", f"· {text}\n", (tag if tag in th.LOG_COLORS else "system"))
        # 超长日志裁掉最老的部分，避免内存与重绘开销持续增长
        line_count = int(self.text.index("end-1c").split(".")[0])
        if line_count > self.MAX_LINES:
            self.text.delete("1.0", f"{line_count - self.MAX_LINES}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
