"""界面主题模块。

集中管理配色、字体与 ttk 样式。所有颜色都是深色主题下的低饱和配色，
目的是让地图上的角色与道具能"跳"出来，同时长时间看着不刺眼。

字体做了逐级回退：优先微软雅黑，其次黑体，最后交给 Tk 默认字体，
保证在任何 Windows 机器上都不会出现方块字。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ------------------------------------------------------------------ 配色
BG = "#0e1116"            # 窗口底色
PANEL = "#171b23"         # 面板底色
PANEL_ALT = "#1f242e"     # 面板内嵌区域
BORDER = "#2b3240"        # 分割线
TEXT = "#dfe6f2"          # 主文字
TEXT_DIM = "#8b97ab"      # 次要文字
ACCENT = "#5ad1c4"        # 强调色（青）
DANGER = "#e5484d"        # 危险色（红）
GOLD = "#e8c45a"          # 金币/道具

# 地图
WALL = "#3d4a66"
WALL_EDGE = "#52618a"
FLOOR = "#1e2836"
FLOOR_ALT = "#222d3c"
DOOR = "#6b5029"
STAIRS = "#e0b64e"

# 迷雾：已探索但当前不可见的区域整体压暗
DIM_FACTOR = 0.6
UNEXPLORED = "#07080b"

# 状态
HP_GREEN = "#3ddc84"
HP_YELLOW = "#f5c542"
HP_RED = "#e5484d"
EXP_BLUE = "#5aa9e6"
MP_PURPLE = "#a78bfa"

# 战斗高亮：蓝=玩家瞄准，红=敌人锁定，黄=自己蓄力
AIM = "#4a9eff"
AIM_BAD = "#7a8699"
THREAT = "#e5484d"
THREAT_TEXT = "#ffb3b5"
CHARGE = "#e8c45a"

# 多只敌人同时蓄力时，按出现顺序给每只分配一种颜色，范围描边与头顶数字同色。
# 刻意避开蓝色（玩家瞄准）和金色（自己蓄力），否则三类高亮会混在一起。
THREAT_PALETTE = (
    "#ff5c5c",   # 红
    "#ff9d3d",   # 橙
    "#ff6bd6",   # 品红
    "#b98cff",   # 紫
    "#4ddba0",   # 青绿
)
THREAT_BADGE_BG = "#0a0c11"     # 倒计时徽章底色，比任何地板都深，保证数字对比度
THREAT_BADGE_TEXT = "#ffffff"   # 数字用纯白：威胁色写字会在彩色图标上糊掉

# 实体
C_PLAYER = "#7ff0e0"
C_MONSTER = "#e05a5a"
C_MONSTER_HURT = "#a03a3a"
C_ITEM = "#f0cf6b"
C_ITEM_WEAPON = "#c9d4e6"
C_ITEM_ARMOR = "#9fb3c8"
C_ITEM_SCROLL = "#c79bf0"

# 精英怪：金色描边，与普通怪一眼可分
ELITE = "#ffd166"
# 治疗怪：青绿色，和红色系攻击怪区分开——它是要优先点掉的目标
HEALER = "#7ddc9a"

# 趣味房间：底色刻意低饱和，避免抢走角色的视觉重心
FEATURE_FILL = {
    "heal": "#15302f",
    "vault": "#302a17",
    "trap": "#33191c",
    "shrine": "#241d33",
}
FEATURE_COLOR = {
    "heal": "#5ad1c4",
    "vault": "#e8c45a",
    "trap": "#e5484d",
    "shrine": "#b98cff",
}

# 日志分类配色
LOG_COLORS = {
    "system": TEXT_DIM,
    "combat": "#e07a7a",
    "item": "#e8c45a",
    "level": "#5ad1c4",
    "danger": "#f0736f",
}

# ------------------------------------------------------------------ 字体
_FALLBACK_FONTS = ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun")


def enable_dpi_awareness() -> bool:
    """声明进程 DPI 感知，让界面在高分屏上按物理像素渲染（文字不糊）。

    必须在创建 ``tk.Tk()`` **之前**调用，否则无效。
    Windows 8.1+ 用 ``SetProcessDpiAwareness``，更老的系统退化到
    ``SetProcessDPIAware``。非 Windows 平台直接返回 False。
    """
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            return True
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
            return True
    except (AttributeError, OSError, ImportError):
        return False


def pick_font(root: tk.Misc | None = None) -> str:
    """从系统字体里挑一个可用的中文字体。"""
    try:
        families = set(tkfont.families(root))
    except tk.TclError:  # pragma: no cover - 无图形环境
        return "TkDefaultFont"
    for name in _FALLBACK_FONTS:
        if name in families:
            return name
    return "TkDefaultFont"


class Theme:
    """保存本窗口实际使用的字体，供各控件共享。"""

    def __init__(self, root: tk.Misc) -> None:
        self.family = pick_font(root)
        self.base = (self.family, 10)
        self.small = (self.family, 9)
        self.tiny = (self.family, 8)
        self.bold = (self.family, 10, "bold")
        self.title = (self.family, 16, "bold")
        self.subtitle = (self.family, 11)
        self.map_glyph = (self.family, 13, "bold")
        self.map_text = (self.family, 11)
        self.map_badge = (self.family, 7, "bold")

    def apply(self, root: tk.Misc) -> None:
        """统一 ttk 控件样式。"""
        style = ttk.Style(root)
        try:
            style.theme_use("clam")   # clam 主题才允许自定义颜色
        except tk.TclError:  # pragma: no cover
            pass
        style.configure(".", background=BG, foreground=TEXT, font=self.base)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=TEXT, font=self.base)
        style.configure("Dim.TLabel", background=PANEL, foreground=TEXT_DIM, font=self.small)
        style.configure("Title.TLabel", background=PANEL, foreground=ACCENT, font=self.bold)
        style.configure(
            "TButton",
            background=PANEL_ALT,
            foreground=TEXT,
            font=self.small,
            borderwidth=0,
            padding=(8, 4),
        )
        style.map(
            "TButton",
            background=[("active", BORDER), ("disabled", PANEL)],
            foreground=[("disabled", TEXT_DIM)],
        )
        style.configure(
            "Accent.TButton", background=ACCENT, foreground="#0c1116", font=self.bold
        )
        style.map("Accent.TButton", background=[("active", "#78e3d6")])

        # 下拉框：clam 默认是浅色的，放到深色面板上像一块补丁，这里统一压暗。
        # readonly 状态的背景由 fieldbackground 控制，必须单独 map 才生效。
        style.configure(
            "TCombobox",
            fieldbackground=PANEL_ALT,
            background=PANEL_ALT,
            foreground=TEXT,
            arrowcolor=TEXT,
            borderwidth=1,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", PANEL_ALT), ("disabled", PANEL)],
            foreground=[("readonly", TEXT), ("disabled", TEXT_DIM)],
            selectbackground=[("readonly", PANEL_ALT)],
            selectforeground=[("readonly", TEXT)],
            background=[("readonly", PANEL_ALT), ("active", BORDER)],
        )
        # 下拉弹出的列表不在 ttk 样式体系里，只能用 option 数据库
        root.option_add("*TCombobox*Listbox.background", PANEL_ALT)
        root.option_add("*TCombobox*Listbox.foreground", TEXT)
        root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        root.option_add("*TCombobox*Listbox.selectForeground", "#0c1116")

    @staticmethod
    def dim(color: str, factor: float = DIM_FACTOR) -> str:
        """把颜色按比例压暗，用于迷雾区域。结果会缓存，避免重复计算。"""
        cached = _DIM_CACHE.get((color, factor))
        if cached is not None:
            return cached
        color = color.lstrip("#")
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        dimmed = f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"
        _DIM_CACHE[(color, factor)] = dimmed
        return dimmed


_DIM_CACHE: dict[tuple[str, float], str] = {}
