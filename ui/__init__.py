"""表现层（tkinter 界面）。

本包只负责"画"和"收输入"，不含任何游戏规则。注意 ``__init__`` 刻意不导入
``app``：这样 ``tools/make_charts.py`` 可以单独导入 ``ui.charts`` 画图，
而不必拉起整个 Tk 环境。
"""

from __future__ import annotations

__all__ = ["app", "charts", "dialogs", "map_view", "panels", "theme"]
