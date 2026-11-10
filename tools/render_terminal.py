"""把命令行输出渲染成"终端截图"风格的 PNG。

报告里需要一张单元测试的运行结果图，但测试是在控制台跑的、没有窗口可截。
这里用 Pillow 把文本按等宽字体画到深色背景上，效果与 Windows Terminal 截图一致。

用法::

    python tools/render_terminal.py docs/test_output.txt docs/test_output.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

BG = "#1b1d23"
BAR = "#2b2f39"
FG = "#d7dce5"
DIM = "#8b93a3"
GREEN = "#5ad17a"
BLUE = "#6c9ef8"

LINE_H = 26
PAD = 22
FONT_SIZE = 15


def load_font() -> ImageFont.FreeTypeFont:
    """挑选一个同时支持中文与等宽的字体。

    Consolas 没有中文字形，直接用它渲染会把中文画成方块；
    这里优先用新宋体（NSimSun），它的西文是半角、中文是全角，
    最接近中文终端里的显示效果。
    """
    candidates = [
        ("C:/Windows/Fonts/simsun.ttc", 1),      # NSimSun，等宽
        ("C:/Windows/Fonts/simsun.ttc", 0),      # SimSun
        ("C:/Windows/Fonts/msyh.ttc", 0),        # 微软雅黑
    ]
    for name, index in candidates:
        try:
            return ImageFont.truetype(name, FONT_SIZE, index=index)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _text_width(font: ImageFont.FreeTypeFont, text: str) -> float:
    """按实际字形量宽度，中文是西文的两倍宽，不能简单按字符数估算。"""
    try:
        return font.getlength(text)
    except AttributeError:  # pragma: no cover - 极老版本 Pillow
        return len(text) * FONT_SIZE * 0.6


def render(text: str, out_path: Path, skip: int = 0, limit: int = 40) -> None:
    lines = [line.rstrip("\n") for line in text.splitlines()]
    if skip > 0:
        # 保留开头几行与结尾若干行，中间用省略号代替
        head = lines[:skip]
        tail = lines[-(limit - skip):]
        lines = head + ["  ……（中间 30 条用例已省略）……"] + tail
    font = load_font()
    width = int(max(760, max(_text_width(font, line) for line in lines) + PAD * 2))
    height = len(lines) * LINE_H + PAD * 2 + 34

    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    # 顶部标题栏，模拟终端窗口
    draw.rectangle([0, 0, width, 30], fill=BAR)
    draw.text((PAD, 8), "命令提示符  —  python -m unittest discover -s tests -v",
              fill=DIM, font=font)

    y = 34 + PAD
    for line in lines:
        color = FG
        if "ok" in line and line.rstrip().endswith("ok"):
            color = DIM
        if line.startswith("Ran ") or line.strip() == "OK":
            color = GREEN
        elif line.startswith("test_"):
            color = FG
        elif "..." in line:
            color = BLUE
        draw.text((PAD, y), line, fill=color, font=font)
        y += LINE_H

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    print(f"已生成 {out_path.relative_to(ROOT)}  ({width}×{height})")


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "test_output.txt"
    dst = Path(argv[2]) if len(argv) > 2 else ROOT / "docs" / "test_output.png"
    if not src.exists():
        print(f"找不到输入文件：{src}")
        return 1
    render(src.read_text(encoding="utf-8"), dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
