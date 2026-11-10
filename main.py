"""程序入口。

负责三件事：
1. 环境自检（Python 版本、tkinter 是否可用），给出可读的失败提示；
2. 顶层异常兜底，避免用户双击运行时窗口一闪而过看不到报错；
3. 启动主窗口。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MIN_PYTHON = (3, 10)


def check_environment() -> str | None:
    """返回错误信息；环境正常时返回 None。"""
    if sys.version_info < MIN_PYTHON:
        return (
            f"当前 Python 版本为 {sys.version.split()[0]}，"
            f"本项目需要 {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 及以上。"
        )
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return (
            "当前 Python 缺少 tkinter 图形库，无法启动界面。\n\n"
            "解决办法：安装官方版 Python（安装时勾选 tcl/tk），\n"
            "或改用自带 tkinter 的解释器运行，例如：\n"
            r"  D:\python\python.exe main.py"
        )
    return None


def main() -> int:
    problem = check_environment()
    if problem:
        print(problem, file=sys.stderr)
        _pause_if_console()
        return 1

    from ui.app import App

    try:
        app = App()
        app.mainloop()
    except Exception:  # 顶层兜底：把完整堆栈打出来，便于定位问题
        traceback.print_exc()
        _pause_if_console()
        return 1
    return 0


def _pause_if_console() -> None:
    """双击运行时控制台会一闪而过，这里停一下让用户看到错误信息。"""
    try:
        input("\n按回车键退出…")
    except (EOFError, KeyboardInterrupt):  # pragma: no cover
        pass


if __name__ == "__main__":
    raise SystemExit(main())
