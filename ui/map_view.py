"""地图渲染视图。

性能设计（这是界面不卡顿的关键）
--------------------------------
**绝不每回合 ``delete("all")`` 重画。** 启动时一次性创建 40×25 共 1000 个
矩形与 1000 个文字图元并缓存 item id；之后每回合只对"外观签名"发生变化的
格子调用 ``itemconfig``。玩家走一步通常只有 2 个格子 + 视野边缘十几格变化，
单帧更新量不到 50 次，远低于重画 2000 个图元的开销。

迷雾的三种状态（未探索 / 已探索 / 当前可见）通过**改同一个矩形的填充色**
实现，不额外增加图层，也不会出现遮挡错位。
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from dungeon import config
from dungeon.dungeon import Dungeon, Tile

from . import theme as th
from .icons import item_candidates, monster_candidates

TILE = config.TILE_PX


class MapView(tk.Canvas):
    """地牢地图画布。"""

    FLOAT_LIMIT = 20          # 同屏飘字上限
    FLOAT_STEP = 2            # 每帧上移像素
    FLOAT_FRAMES = 14         # 飘字存活帧数

    def __init__(
        self,
        master: tk.Misc,
        theme: th.Theme,
        icon_set: Any = None,
        on_click: Callable[[int, int], None] | None = None,
        on_hover: Callable[[int, int], None] | None = None,
        on_alt_click: Callable[[int, int], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            width=config.MAP_CANVAS_W,
            height=config.MAP_CANVAS_H,
            bg=th.UNEXPLORED,
            highlightthickness=0,
            bd=0,
        )
        self.theme = theme
        self.state: Any = None
        self.icon_set = icon_set          # 图标清单为空时所有格子退回字符绘制
        self._on_click = on_click
        self._on_hover = on_hover
        self._on_alt_click = on_alt_click

        self._rect: dict[tuple[int, int], int] = {}
        self._text: dict[tuple[int, int], int] = {}
        self._img: dict[tuple[int, int], int] = {}   # 懒创建的图标图元
        self._sig: dict[tuple[int, int], tuple[str, str, str, str, tuple[str, ...]]] = {}
        self._floats: list[list[Any]] = []
        self._hover_cell: tuple[int, int] | None = None

        # 战斗图层：红/黄威胁区、蓝色瞄准预览、头顶倒计时
        self._overlay_items: dict[tuple[int, int], int] = {}
        self._threat_cells: set[tuple[int, int]] = set()
        self._badges: dict[tuple[int, int], tuple[int, int]] = {}
        self._aim_items: dict[tuple[int, int], int] = {}
        self._aim_cells: set[tuple[int, int]] = set()

        self._build_grid()
        self._hover_box = self.create_rectangle(
            0, 0, TILE, TILE, outline=th.ACCENT, width=2, state="hidden"
        )
        self._player_ring = self.create_oval(
            0, 0, TILE, TILE, outline=th.C_PLAYER, width=2, state="hidden"
        )

        self.bind("<Button-1>", self._handle_click)
        self.bind("<Button-3>", self._handle_alt_click)
        self.bind("<Motion>", self._handle_hover)
        self.bind("<Leave>", self._handle_leave)
        self.bind("<Destroy>", self._handle_destroy)

        self._after_id: str | None = self.after(40, self._animate)

    # ------------------------------------------------------------ 网格
    def _build_grid(self) -> None:
        """一次性创建全部格子的矩形与文字图元。"""
        font_glyph = self.theme.map_glyph
        for y in range(config.MAP_H):
            for x in range(config.MAP_W):
                x0, y0 = x * TILE, y * TILE
                rect = self.create_rectangle(
                    x0, y0, x0 + TILE, y0 + TILE, fill=th.UNEXPLORED, outline="", width=1
                )
                text = self.create_text(
                    x0 + TILE / 2,
                    y0 + TILE / 2 + 1,
                    text="",
                    fill=th.TEXT,
                    font=font_glyph,
                    state="hidden",
                )
                self._rect[(x, y)] = rect
                self._text[(x, y)] = text

    # ------------------------------------------------------------ 数据绑定
    def set_state(self, state: Any) -> None:
        """切换到新的局面（开新档、读档、换层）。"""
        self.state = state
        self._sig.clear()
        self._clear_floats()
        self.clear_aim()
        for cell in list(self._badges):
            for item in self._badges.pop(cell):
                self.delete(item)
        for cell in list(self._threat_cells):
            if cell in self._overlay_items:
                self.itemconfig(self._overlay_items[cell], state="hidden")
        self._threat_cells.clear()
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        """增量刷新：只更新外观发生变化的格子。"""
        if self.state is None:
            return
        dungeon: Dungeon = self.state.dungeon
        for y in range(dungeon.height):
            for x in range(dungeon.width):
                look = self._cell_look(x, y)
                if not force and self._sig.get((x, y)) == look:
                    continue
                self._sig[(x, y)] = look
                fill, glyph, color, outline, candidates = look
                self.itemconfig(self._rect[(x, y)], fill=fill, outline=outline)
                text_id = self._text[(x, y)]
                image_id = self._img.get((x, y))

                # 有图标就画图并藏起文字，没有就反过来——两条路互斥
                photo = (
                    self.icon_set.image(candidates, dim=(x, y) not in dungeon.visible)
                    if (candidates and self.icon_set is not None)
                    else None
                )
                if photo is not None:
                    if image_id is None:
                        image_id = self.create_image(
                            x * TILE + TILE / 2,
                            y * TILE + TILE / 2,
                            image=photo,
                            state="hidden",
                        )
                        self._img[(x, y)] = image_id
                    self.itemconfig(image_id, image=photo, state="normal")
                    self.itemconfig(text_id, state="hidden")
                    continue

                if image_id is not None:
                    self.itemconfig(image_id, state="hidden")
                if glyph:
                    self.itemconfig(text_id, text=glyph, fill=color, state="normal")
                else:
                    self.itemconfig(text_id, state="hidden")

        self._update_player_ring()
        self._sync_threat_overlays()
        self._sync_charge_badges()
        self.tag_raise(self._hover_box)
        self.tag_raise(self._player_ring)
        self.tag_raise("aim")
        self.tag_raise("badge")

    # ------------------------------------------------------------ 威胁与瞄准图层
    def _overlay(self, cell: tuple[int, int], color: str, tag: str) -> int:
        """按需创建一个覆盖在格子上的半透明高亮块。"""
        item = self._overlay_items.get(cell)
        if item is None:
            x, y = cell
            item = self.create_rectangle(
                x * TILE + 1, y * TILE + 1,
                x * TILE + TILE - 1, y * TILE + TILE - 1,
                fill=color, outline=color, stipple="gray25", width=2,
                tags=(tag,), state="hidden",
            )
            self._overlay_items[cell] = item
        self.itemconfig(item, fill=color, outline=color, tags=(tag,), state="normal")
        return item

    def _sync_threat_overlays(self) -> None:
        """红色 = 敌人已锁定的打击区域；黄色 = 玩家自己的蓄力区域。"""
        state = self.state
        wanted: dict[tuple[int, int], str] = {}
        if state is not None:
            for monster in state.monsters:
                if monster.alive and monster.telegraph:
                    for cell in monster.telegraph:
                        wanted[cell] = th.THREAT
            if state.player.charge_left > 0:
                for cell in state.player.charge_tiles:
                    wanted[cell] = th.CHARGE

        for cell in list(self._threat_cells - set(wanted)):
            self.itemconfig(self._overlay_items[cell], state="hidden")
        for cell, color in wanted.items():
            self._overlay(cell, color, "threat")
        self._threat_cells = set(wanted)

    def _sync_charge_badges(self) -> None:
        """敌人头顶的"还有几回合出手"倒计时。

        数字直接写在格子上会被红色预告块吃掉对比度，所以做成
        "深色小圆角底 + 亮红数字"的徽章，压在格子顶部。
        """
        state = self.state
        wanted: dict[tuple[int, int], str] = {}
        if state is not None:
            for monster in state.monsters:
                if monster.alive and monster.charge_left > 0:
                    wanted[monster.pos] = str(monster.charge_left)

        for cell in list(set(self._badges) - set(wanted)):
            for item in self._badges.pop(cell):
                self.delete(item)

        for cell, text in wanted.items():
            x, y = cell
            cx = x * TILE + TILE / 2
            top = y * TILE - 6
            pair = self._badges.get(cell)
            if pair is None:
                rect = self.create_rectangle(
                    cx - 7, top, cx + 7, top + 13,
                    fill="#141821", outline=th.THREAT, width=1, tags=("badge",),
                )
                label = self.create_text(
                    cx, top + 6, text=text, fill=th.THREAT_TEXT,
                    font=self.theme.tiny, tags=("badge",),
                )
                self._badges[cell] = (rect, label)
            else:
                rect, label = pair
                self.coords(rect, cx - 7, top, cx + 7, top + 13)
                self.coords(label, cx, top + 6)
                self.itemconfig(label, text=text)

    def show_aim(self, cells: frozenset[tuple[int, int]], valid: bool = True) -> None:
        """瞄准预览：蓝色高亮这一击会覆盖哪些格子。"""
        color = th.AIM if valid else th.AIM_BAD
        for cell in list(self._aim_cells - cells):
            self.itemconfig(self._aim_items[cell], state="hidden")
        for cell in cells:
            item = self._aim_items.get(cell)
            if item is None:
                x, y = cell
                item = self.create_rectangle(
                    x * TILE + 1, y * TILE + 1,
                    x * TILE + TILE - 1, y * TILE + TILE - 1,
                    fill=color, outline=color, stipple="gray50", width=2, tags=("aim",),
                )
                self._aim_items[cell] = item
            self.itemconfig(item, fill=color, outline=color, state="normal")
        self._aim_cells = set(cells)

    def clear_aim(self) -> None:
        for item in self._aim_items.values():
            self.itemconfig(item, state="hidden")
        self._aim_cells = set()

    def _update_player_ring(self) -> None:
        px, py = self.state.player.pos
        if not self._is_lit(px, py):
            self.itemconfig(self._player_ring, state="hidden")
            return
        pad = 2
        self.coords(
            self._player_ring,
            px * TILE + pad,
            py * TILE + pad,
            px * TILE + TILE - pad,
            py * TILE + TILE - pad,
        )
        # 站在楼梯上时把光圈改成金色：玩家图标会盖住脚下的 ↓，
        # 不给个视觉提示的话，玩家根本不知道自己正踩在楼梯上
        on_stairs = self.state.stairs_here
        self.itemconfig(
            self._player_ring,
            outline=th.STAIRS if on_stairs else th.C_PLAYER,
            width=3 if on_stairs else 2,
            state="normal",
        )

    def _is_lit(self, x: int, y: int) -> bool:
        return (x, y) in self.state.dungeon.explored

    # ------------------------------------------------------------ 单格外观
    def _cell_look(self, x: int, y: int) -> tuple[str, str, str, str, tuple[str, ...]]:
        """计算一个格子应该长什么样。

        返回 ``(底色, 字符, 字符颜色, 边框色, 图标候选键)``。
        候选键是一个元组，按"专属 → 类别 → 通用"排列，交给 ``IconSet`` 查找；
        清单里没有对应图片时返回空元组，界面就退回字符绘制。
        """
        state = self.state
        dungeon: Dungeon = state.dungeon
        visible = (x, y) in dungeon.visible
        explored = (x, y) in dungeon.explored

        if not explored:
            return th.UNEXPLORED, "", th.TEXT, "", ()

        tile = dungeon.tile_at(x, y)
        outline = ""
        if tile is Tile.WALL:
            fill = th.WALL
            outline = th.WALL_EDGE      # 1 像素亮边，让墙看起来像砖块
        elif tile is Tile.DOOR:
            fill = th.DOOR
        elif tile is Tile.STAIRS:
            fill = th.FLOOR_ALT
        else:
            fill = th.FLOOR if (x + y) % 2 == 0 else th.FLOOR_ALT

        glyph, color = "", th.TEXT
        candidates: tuple[str, ...] = ()
        if visible:
            if tile is Tile.STAIRS:
                glyph, color = "↓", th.STAIRS
                candidates = ("stair",)
            elif tile is Tile.DOOR:
                glyph, color = "·", th.TEXT_DIM
                candidates = ("door",)
        else:
            fill = th.Theme.dim(fill)
            if outline:
                outline = th.Theme.dim(outline)

        # 实体优先级：玩家 > 怪物 > 道具
        if (x, y) == state.player.pos:
            glyph, color = "@", th.C_PLAYER
            candidates = ("player",)
            if not visible:
                color = th.Theme.dim(color)
        elif visible:
            monster = state.monster_at(x, y)
            if monster is not None:
                glyph = monster.glyph
                color = th.C_MONSTER if monster.hp_ratio > 0.6 else th.C_MONSTER_HURT
                candidates = monster_candidates(monster.kind)
            else:
                item = state.item_at(x, y)
                if item is not None:
                    glyph = item.glyph
                    color = {
                        "potion": th.C_ITEM,
                        "weapon": th.C_ITEM_WEAPON,
                        "armor": th.C_ITEM_ARMOR,
                        "scroll": th.C_ITEM_SCROLL,
                    }.get(item.kind, th.C_ITEM)
                    candidates = item_candidates(item.key, item.kind)

        return fill, glyph, color, outline, candidates

    # ------------------------------------------------------------ 飘字
    def spawn_float(self, x: int, y: int, text: str, tone: str = "player") -> None:
        """在指定格子上方弹出一段伤害/提示文字。"""
        color = {
            "player": th.TEXT,
            "crit": th.GOLD,
            "hurt": th.DANGER,
            "magic": th.MP_PURPLE,
            "heal": th.HP_GREEN,
        }.get(tone, th.TEXT)
        cx, cy = x * TILE + TILE / 2, y * TILE + TILE / 2
        item = self.create_text(
            cx, cy, text=text, fill=color, font=self.theme.map_glyph, tags=("float",)
        )
        # 新创建的图元默认在最上层，但之后懒创建的图标图元会盖住它，先抬一次
        self.tag_raise(item)
        self._floats.append([item, 0])
        while len(self._floats) > self.FLOAT_LIMIT:
            old = self._floats.pop(0)
            self.delete(old[0])

    def _animate(self) -> None:
        """飘字动画：每 40 毫秒上移一小段，存活帧数用尽后删除。"""
        alive: list[list[Any]] = []
        for item, frame in self._floats:
            frame += 1
            if frame >= self.FLOAT_FRAMES:
                self.delete(item)
                continue
            self.move(item, 0, -self.FLOAT_STEP)
            alive.append([item, frame])
        self._floats = alive
        self._after_id = self.after(40, self._animate)

    def _clear_floats(self) -> None:
        for item, _ in self._floats:
            self.delete(item)
        self._floats.clear()

    def _handle_destroy(self, event: tk.Event) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:  # pragma: no cover
                pass
            self._after_id = None

    # ------------------------------------------------------------ 鼠标交互
    def cell_at(self, px: int, py: int) -> tuple[int, int] | None:
        """把像素坐标换算成格子坐标，越界返回 None。"""
        x, y = px // TILE, py // TILE
        if 0 <= x < config.MAP_W and 0 <= y < config.MAP_H:
            return x, y
        return None

    def _handle_click(self, event: tk.Event) -> None:
        # 点击地图即把键盘焦点要回来，否则焦点还留在背包列表上，方向键会失效
        try:
            self.focus_set()
        except tk.TclError:      # pragma: no cover - 窗口正在销毁
            pass
        cell = self.cell_at(event.x, event.y)
        if cell is not None and self._on_click is not None:
            self._on_click(*cell)

    def _handle_alt_click(self, event: tk.Event) -> None:
        """右键：切换瞄准模式。"""
        try:
            self.focus_set()
        except tk.TclError:      # pragma: no cover
            pass
        cell = self.cell_at(event.x, event.y)
        if cell is not None and self._on_alt_click is not None:
            self._on_alt_click(*cell)

    def _handle_hover(self, event: tk.Event) -> None:
        cell = self.cell_at(event.x, event.y)
        if cell is None:
            self._hide_hover()
            return
        if cell != self._hover_cell:
            self._hover_cell = cell
            x, y = cell
            self.coords(
                self._hover_box, x * TILE, y * TILE, x * TILE + TILE, y * TILE + TILE
            )
            self.itemconfig(self._hover_box, state="normal")
            self.tag_raise(self._hover_box)
        if self._on_hover is not None and self.state is not None:
            self._on_hover(*cell)

    def _handle_leave(self, event: tk.Event) -> None:
        self._hide_hover()

    def _hide_hover(self) -> None:
        self._hover_cell = None
        self.itemconfig(self._hover_box, state="hidden")
