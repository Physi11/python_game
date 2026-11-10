"""主窗口。

职责只有三件事：
1. **装配**界面（菜单栏、地图画布、状态面板、日志、状态栏）；
2. **收输入**（键盘与鼠标），并把输入翻译成 ``GameState`` 的五个意图方法；
3. **贴表现**（把逻辑层给出的事件渲染成飘字、日志、状态栏提示）。

这里没有任何战斗公式、地图生成或数值判断——那些全在 ``dungeon/`` 里。
界面层甚至不知道"伤害怎么算"，它只知道"有个 damage 事件要在某格弹字"。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from dungeon import config
from dungeon.game_state import GameState, GameStatus
from dungeon.save_manager import SaveError, SaveManager
from dungeon.stats import StatsAnalyzer

from . import dialogs
from . import theme as th
from .icon_set import IconSet
from .icons import DEFAULT_BASE_DIR, IconManifest, IconManifestError, load_manifest
from .map_view import MapView
from .panels import LogPanel, StatusPanel

# 键盘 → 方向。keysym 统一转小写后比较
DIR_KEYS: dict[str, tuple[int, int]] = {
    "w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0),
    "up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
}

# 接受键盘输入的控件：焦点落在它们身上时，按键必须交给控件自己处理。
# 注意不包含 Listbox —— 见 LISTBOX_OWNED 的说明。
TEXT_WIDGETS = (tk.Entry, tk.Text)

# Listbox 会自己消费的按键。Tk 的 listbox.tcl 里这些类绑定都不返回 "break"，
# 所以事件会继续冒泡到主窗口的 <Key>；若不在这里拦下，会变成"方向键既滚动
# 列表又移动角色""空格既选中列表项又浪费一回合"的双重响应。
LISTBOX_OWNED = frozenset(
    {"up", "down", "left", "right", "prior", "next", "home", "end", "space"}
)

DEFAULT_HINT = "WASD/方向键 移动　空格 等待　G 拾取/下楼　I 背包　> 下楼　F5/F9 存读档　? 帮助"


class App(tk.Tk):
    """地下城探险主程序窗口。"""

    def __init__(self, seed: int | None = None) -> None:
        # 必须在创建 Tk 之前声明 DPI 感知，否则高分屏上文字会被系统拉伸变糊
        th.enable_dpi_awareness()
        super().__init__()
        self.title(config.APP_TITLE)
        self.configure(bg=th.BG)
        self.geometry(f"{config.WINDOW_WIDTH}x{config.WINDOW_HEIGHT}+80+40")
        self.resizable(False, False)

        self.theme = th.Theme(self)
        self.theme.apply(self)

        self.save_manager = SaveManager()
        self.state: GameState = GameState.new_game(seed=seed)
        self.icons = self._load_icon_set()
        self._record_saved = False
        self._status_after: str | None = None
        self._last_log: tuple[str, str] | None = None

        self._build_ui()
        self._build_menu()
        self._bind_keys()

        self._attach_state(self.state, fresh=True)
        self.set_status("欢迎来到地下城。按 ? 查看操作说明。")

    # ================================================================ 界面装配
    def _build_ui(self) -> None:
        container = tk.Frame(self, bg=th.BG)
        container.pack(fill="both", expand=True, padx=10, pady=(6, 8))

        top = tk.Frame(container, bg=th.BG)
        top.pack(fill="both", expand=False)

        self.map_view = MapView(
            top,
            self.theme,
            icon_set=self.icons,
            on_click=self._on_canvas_click,
            on_hover=self._on_canvas_hover,
        )
        self.map_view.pack(side="left")

        self.status_panel = StatusPanel(
            top,
            self.theme,
            on_use_item=self._use_item,
            on_hover_item=lambda text: self.set_status(text),
        )
        self.status_panel.pack(side="left", fill="y", padx=(10, 0))

        self.log_panel = LogPanel(container, self.theme)
        self.log_panel.pack(fill="x", pady=(8, 0))
        self._log_text = self.log_panel.text
        # Tk 的 Text 被点击时会无条件抢焦点，这里延迟一拍再把焦点还给地图
        self._log_text.bind("<Button-1>", self._on_log_click, add="+")

        bar = tk.Frame(container, bg=th.PANEL, height=config.STATUS_BAR_H)
        bar.pack(fill="x", pady=(6, 0))
        bar.pack_propagate(False)

        self.status_label = tk.Label(
            bar, text="", bg=th.PANEL, fg=th.TEXT_DIM, font=self.theme.small, anchor="w"
        )
        self.status_label.pack(side="left", padx=10)

        self.hint_label = tk.Label(
            bar, text=DEFAULT_HINT, bg=th.PANEL, fg="#6b7688", font=self.theme.tiny, anchor="e"
        )
        self.hint_label.pack(side="right", padx=10)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self, tearoff=0, bg=th.PANEL, fg=th.TEXT, activebackground=th.BORDER)
        self.config(menu=menubar)

        game_menu = tk.Menu(menubar, tearoff=0)
        game_menu.add_command(label="新游戏", accelerator="N", command=self.new_game)
        game_menu.add_command(label="新游戏（指定种子）", command=self.new_game_with_seed)
        game_menu.add_separator()
        game_menu.add_command(label="保存到 1 号槽", accelerator="F5", command=lambda: self.save_game(1))
        game_menu.add_command(label="读取 1 号槽", accelerator="F9", command=lambda: self.load_game(1))
        game_menu.add_command(label="存档管理…", command=self.show_saves)
        game_menu.add_separator()
        game_menu.add_command(label="退出", command=self.on_quit)
        menubar.add_cascade(label="游戏", menu=game_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="背包", accelerator="I", command=self.show_inventory)
        view_menu.add_command(label="历史战绩", command=self.show_leaderboard)
        view_menu.add_command(label="统计图表", accelerator="M", command=self.show_charts)
        view_menu.add_separator()
        view_menu.add_command(label="重载图标资源", accelerator="F12", command=self.reload_icons)
        view_menu.add_command(label="清空历史战绩", command=self.clear_records)
        menubar.add_cascade(label="查看", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="操作说明", accelerator="?", command=self.show_help)
        help_menu.add_command(label="关于", command=self.show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)

    def _bind_keys(self) -> None:
        self.bind("<Key>", self._on_key)
        self.bind("<F5>", lambda _e: self.save_game(1))
        self.bind("<Control-s>", lambda _e: self.save_game(1))
        self.bind("<F9>", lambda _e: self.load_game(1))
        self.bind("<Control-o>", lambda _e: self.load_game(1))
        self.bind("<F12>", lambda _e: self.reload_icons())

    # ================================================================ 图标资源
    def _load_icon_set(self) -> IconSet:
        """读取 ``assets/icons.json`` 并构建图标集。

        清单缺失或某张图片损坏时一律降级到字符绘制，绝不让界面起不来。
        """
        try:
            manifest = load_manifest()
        except IconManifestError as exc:
            print(f"[图标] 清单加载失败，改用字符绘制：{exc}")
            manifest = IconManifest(entries={}, base_dir=DEFAULT_BASE_DIR)
        return IconSet(self, manifest)

    def reload_icons(self) -> None:
        """热重载图标资源（菜单「查看 → 重载图标资源」/ F12）。

        顺序必须是"先建新 → 再刷新 → 最后丢旧"：反过来会有一瞬间画布上的
        图元还指着已经被回收的 PhotoImage，出现空白或报错。
        """
        old = self.map_view.icon_set
        self.map_view.icon_set = self._load_icon_set()
        self.map_view.refresh(force=True)
        del old
        self.set_status(f"图标已重载：{self.map_view.icon_set.summary()}")

    # ================================================================ 状态切换
    def _attach_state(self, state: GameState, fresh: bool = False) -> None:
        """把新的局面接到界面上（开新档 / 读档之后）。"""
        self.state = state
        self.map_view.set_state(state)
        self.status_panel.refresh(state)
        if fresh:
            self.log_panel.clear()
            self._last_log = None
            self._append_new_log()
            self._last_log = state.log[-1] if state.log else None
        self._record_saved = False
        self._refresh()
        # 新开档 / 读档后，键盘焦点交还地图，避免焦点停在某个弹窗或列表上
        self._focus_map()

    def _append_new_log(self) -> None:
        """只把新增的日志行推给日志面板，避免整屏重复。

        用"上一条日志对象的身份"作为游标：``GameState.log`` 是定长 deque，
        装满后会挤掉最老的条目，用下标做游标会错位，用对象身份最稳。
        """
        entries = list(self.state.log)
        if not entries:
            return
        start = 0
        if self._last_log is not None:
            for index in range(len(entries) - 1, -1, -1):
                if entries[index] is self._last_log:
                    start = index + 1
                    break
            else:
                # 上一条已经被挤出队列，只补最近几条，避免刷屏
                start = max(0, len(entries) - 5)
        new_entries = entries[start:]
        if new_entries:
            self.log_panel.append(new_entries)

    def _refresh(self) -> None:
        """把逻辑层的状态同步到界面：地图、面板、日志、飘字。"""
        self.map_view.refresh()
        self.status_panel.refresh(self.state)

        events = self.state.drain_events()
        for event in events:
            kind = event.get("kind")
            if kind == "damage":
                self.map_view.spawn_float(
                    event["x"], event["y"], event.get("text", ""), event.get("tone", "player")
                )
            elif kind == "miss":
                self.map_view.spawn_float(event["x"], event["y"], "MISS", "player")
            elif kind == "pickup":
                self.map_view.spawn_float(event["x"], event["y"], "+", "heal")
            elif kind == "levelup":
                self.map_view.spawn_float(event["x"], event["y"], "LV UP", "crit")

        self._append_new_log()
        if self.state.log:
            self._last_log = self.state.log[-1]
        self._check_finished()

    def _check_finished(self) -> None:
        """一局结束时写入战绩并弹出结算窗口（只做一次）。"""
        if not self.state.is_finished or self._record_saved:
            return
        self._record_saved = True
        try:
            self.save_manager.append_record(self.state.build_record())
        except SaveError as exc:  # 磁盘异常不影响继续看结算
            self.set_status(f"战绩写入失败：{exc}", "warn")

        result_text = {
            GameStatus.WIN: "通关成功",
            GameStatus.DEAD: "你倒下了",
            GameStatus.TIMEOUT: "探索超时",
            GameStatus.QUIT: "已退出本局",
        }.get(self.state.status, "本局结束")
        self.set_status(result_text)
        self.after(260, self._popup_game_over)

    def _popup_game_over(self) -> None:
        dialogs.show_game_over(
            self,
            self.theme,
            self.state,
            on_restart=self.new_game,
            on_leaderboard=self.show_leaderboard,
        )

    # ================================================================ 输入
    def _on_key(self, event: tk.Event) -> None:
        keysym = (event.keysym or "").lower()

        # 输入框（种子输入等）需要独占键盘；日志区是只读的，按键应当直接作用于游戏
        if isinstance(event.widget, TEXT_WIDGETS):
            if event.widget is getattr(self, "_log_text", None):
                self._focus_map()
            else:
                return
        # 列表只独占它自己会消费的那几个键，其余按键照常交给游戏
        if isinstance(event.widget, tk.Listbox) and keysym in LISTBOX_OWNED:
            return

        if keysym in DIR_KEYS:
            dx, dy = DIR_KEYS[keysym]
            self._do_move(dx, dy)
            return

        if keysym in ("space", " "):
            self._do_action(self.state.wait)
        elif keysym == "g":
            self._interact_here()
        elif keysym == "greater" or keysym == "period":
            self._do_action(self.state.descend)
        elif keysym == "i":
            self.show_inventory()
        elif keysym == "n":
            self.new_game()
        elif keysym == "m":
            self.show_charts()
        elif keysym == "escape":
            self._leave_list_focus()
        elif keysym == "question" or keysym == "slash":
            self.show_help()
        elif keysym in tuple(f"kp_{i}" for i in range(1, 10)) or (
            len(keysym) == 1 and keysym.isdigit() and keysym != "0"
        ):
            index = int(keysym[-1]) - 1
            self._use_item(index)
        else:
            self.set_status(f"按键「{event.keysym}」暂未绑定功能，按 ? 查看快捷键", "warn")

    # ---------------------------------------------------------------- 焦点
    def _focus_map(self) -> None:
        """把键盘焦点交还地图画布。

        Tk 的 ``listbox.tcl`` 与 ``text.tcl`` 里，鼠标按下时会无条件
        ``focus $w``（``-takefocus 0`` 拦不住，它只影响 Tab 遍历）。
        焦点一旦停在背包列表或日志区，主窗口的 ``<Key>`` 就会被
        ``_on_key`` 的守卫挡掉，表现为"方向键、I、> 全部失效"。
        """
        try:
            self.map_view.focus_set()
        except tk.TclError:      # 窗口正在销毁
            pass

    def _on_log_click(self, _event: tk.Event) -> None:
        """点击日志区后把焦点还给地图（延迟一拍，先让日志完成自身定位）。"""
        self.after_idle(self._focus_map)

    def _leave_list_focus(self) -> None:
        """按 Esc 从背包列表/日志区退回到地图。"""
        try:
            widget = self.focus_get()
        except (KeyError, tk.TclError):   # pragma: no cover - 极端情况
            widget = None
        self._focus_map()
        if isinstance(widget, (tk.Listbox, tk.Text)):
            self.set_status("已离开道具列表，回到地图")

    def _interact_here(self) -> None:
        """对脚下格子执行"默认交互"：有道具就拾取，站在楼梯上就下楼。

        这条分流放在界面层而不是 ``GameState.interact()``：后者的契约是
        "不消耗回合"，而 ``descend()`` 会推进回合数，改它会同时破坏
        ``G`` 键语义与批量模拟器的步进假设。放在这里既守住逻辑层的契约，
        又让鼠标点击、``G`` 键、``>`` 键三条路径共用同一套判定。
        """
        state = self.state
        if state.item_at(*state.player.pos) is None and state.stairs_here:
            self._do_action(state.descend)
        else:
            self._do_action(state.interact)

    def _do_move(self, dx: int, dy: int) -> None:
        self._do_action(lambda: self.state.try_move(dx, dy))

    def _do_action(self, action: Any) -> None:
        """统一的动作入口：执行 → 刷新界面 → 提示结果。"""
        if self.state.is_finished:
            self.set_status("本局已经结束，按 N 开始新的一局", "warn")
            return
        action()
        self._refresh()

    def _use_item(self, index: int) -> None:
        try:
            if self.state.is_finished:
                return
            inventory = self.state.player.inventory
            if index >= len(inventory):
                self.set_status("这个格子里没有道具", "warn")
                return
            name = inventory[index].name
            ok = self.state.use_item(index)
            if ok:
                self.set_status(f"使用了{name}")
            self._refresh()
        finally:
            # 无论成功与否都把焦点还给地图，否则用过道具后键盘会"卡"在列表上
            self._focus_map()

    def _on_canvas_click(self, x: int, y: int) -> None:
        """鼠标点击：相邻格移动/攻击，同格执行默认交互（拾取或下楼）。"""
        if self.state.is_finished:
            return
        px, py = self.state.player.pos
        if (x, y) == (px, py):
            self._interact_here()
            return
        dx, dy = x - px, y - py
        if abs(dx) + abs(dy) == 1:
            self._do_move(dx, dy)
        else:
            self.set_status("只能移动到相邻的格子（用键盘可连续移动）", "warn")

    def _on_canvas_hover(self, x: int, y: int) -> None:
        state = self.state
        if (x, y) not in state.dungeon.explored:
            self.set_status("未探索的区域")
            return
        monster = state.monster_at(x, y)
        if monster is not None and (x, y) in state.dungeon.visible:
            self.set_status(
                f"{monster.name}　HP {monster.hp}/{monster.max_hp}　"
                f"攻击 {monster.atk}　防御 {monster.defense}　"
                f"击杀奖励 {monster.exp_reward} 经验"
            )
            return
        item = state.item_at(x, y)
        if item is not None and (x, y) in state.dungeon.visible:
            self.set_status(item.describe())
            return
        tile = state.dungeon.tile_at(x, y)
        names = {"WALL": "石墙", "FLOOR": "地面", "DOOR": "门", "STAIRS": "向下的楼梯"}
        self.set_status(names.get(tile.name, "地面"))

    # ================================================================ 状态栏
    def set_status(self, text: str, level: str = "info") -> None:
        """更新状态栏。警告信息 2.5 秒后自动恢复默认提示。"""
        color = {"info": th.TEXT, "warn": th.GOLD, "danger": th.DANGER}.get(level, th.TEXT)
        self.status_label.config(text=text, fg=color)
        if self._status_after is not None:
            try:
                self.after_cancel(self._status_after)
            except tk.TclError:  # pragma: no cover
                pass
        self._status_after = self.after(2500, self._reset_status)

    def _reset_status(self) -> None:
        self._status_after = None
        self.status_label.config(text=DEFAULT_HINT.split("　")[0], fg=th.TEXT_DIM)

    # ================================================================ 菜单命令
    def new_game(self, seed: int | None = None) -> None:
        if not self._confirm_discard("开始新游戏会丢失当前进度，确定吗？"):
            return
        state = GameState.new_game(seed=seed)
        self._attach_state(state, fresh=True)
        self.set_status(f"新的一局开始了（种子 {state.rng.seed}）")

    def new_game_with_seed(self) -> None:
        text = simpledialog.askstring("指定种子", "输入一个整数种子（相同种子会生成相同地图）：", parent=self)
        if text is None:
            return
        if not text.strip().isdigit():
            self.set_status("种子必须是正整数", "warn")
            return
        self.new_game(seed=int(text.strip()))

    def save_game(self, slot: int = 1) -> None:
        if self.state.is_finished:
            self.set_status("本局已结束，结算数据已自动存入战绩", "warn")
            return
        try:
            path = self.save_manager.save(self.state, slot)
        except SaveError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.set_status(f"已保存到 {slot} 号槽（{path.name}）")
        self.log_panel.append([(f"进度已保存到 {slot} 号存档槽", "system")])

    def load_game(self, slot: int = 1) -> None:
        if not self.save_manager.exists(slot):
            self.set_status(f"{slot} 号槽还没有存档", "warn")
            return
        if not self._confirm_discard("读取存档会覆盖当前进度，确定吗？"):
            return
        try:
            state = self.save_manager.load(slot)
        except SaveError as exc:
            messagebox.showerror("读档失败", str(exc), parent=self)
            self.set_status("读档失败，详见弹窗提示", "warn")
            return
        self._attach_state(state, fresh=True)
        self.set_status(f"已读取 {slot} 号存档：第 {state.floor} 层")

    def show_saves(self) -> None:
        metas = self.save_manager.list_meta()
        lines = []
        for meta in metas:
            if meta["exists"]:
                lines.append(f"{meta['slot']} 号槽　{meta.get('preview', '')}　（{meta.get('saved_at', '')}）")
            else:
                lines.append(f"{meta['slot']} 号槽　空")
        messagebox.showinfo("存档管理", "\n\n".join(lines), parent=self)

    def show_inventory(self) -> None:
        dialogs.show_inventory(self, self.theme, self.state, on_use=self._use_item)

    def show_help(self) -> None:
        dialogs.show_help(self, self.theme)

    def show_leaderboard(self) -> None:
        dialogs.show_leaderboard(self, self.theme, self.save_manager.load_records())

    def show_charts(self) -> None:
        analyzer = StatsAnalyzer(self.save_manager.load_records())
        dialogs.show_charts(self, self.theme, analyzer)

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            f"{config.APP_TITLE}\n"
            f"{config.APP_SUBTITLE}\n\n"
            "一个用纯 Python + tkinter 实现的地牢探险 Roguelike：\n"
            "程序化地图生成、回合制战斗、JSON 存档、matplotlib 统计图表。\n\n"
            f"Python {config.MAX_FLOOR} 层地下城，等你来挑战。",
            parent=self,
        )

    def clear_records(self) -> None:
        if not messagebox.askyesno("清空战绩", "确定要清空全部历史战绩吗？此操作不可撤销。", parent=self):
            return
        self.save_manager.clear_records()
        self.set_status("历史战绩已清空")

    def _confirm_discard(self, message: str) -> bool:
        if self.state.is_finished or self.state.turn == 0:
            return True
        return messagebox.askyesno("确认", message, parent=self)

    def on_quit(self) -> None:
        self.destroy()


def run(seed: int | None = None) -> None:
    """启动应用。"""
    app = App(seed=seed)
    app.mainloop()
