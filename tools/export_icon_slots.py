"""按图标清单导出 24×24 的占位 PNG，作为改画模板。

这个脚本**不会自动运行**，只有你想要一份"已经命名好、尺寸也对"的空白素材时
才手动跑一次：它会按 ``assets/icons.json`` 里登记的路径，把游戏当前使用的字符
与配色渲染成 PNG 放进去。之后直接在文件上改画即可。

想回到"纯字符"外观，把生成的 PNG 删掉（或按 F12 重载）就行。

用法::

    python tools/export_icon_slots.py            # 只补缺失的图
    python tools/export_icon_slots.py --force    # 覆盖已有文件
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from dungeon import config  # noqa: E402
from dungeon.item import ITEM_TABLE, Armor, Potion, Scroll, Weapon  # noqa: E402
from dungeon.monster import MONSTER_TABLE  # noqa: E402
from ui import theme as th  # noqa: E402
from ui.icons import load_manifest  # noqa: E402

SUPERSAMPLE = 4           # 先画大图再缩小，边缘更干净
FONT_CANDIDATES = ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf")


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_slot_map() -> dict[str, tuple[str, str]]:
    """把清单里的每个键映射到 (字符, 颜色)，与游戏内的绘制规则保持一致。"""
    slots: dict[str, tuple[str, str]] = {
        "player": ("@", th.C_PLAYER),
        "monster": ("?", th.C_MONSTER),
        "item": ("?", th.C_ITEM),
        "stair": ("↓", th.STAIRS),
        "door": ("·", th.TEXT_DIM),
    }
    item_colors = {
        "potion": th.C_ITEM,
        "weapon": th.C_ITEM_WEAPON,
        "armor": th.C_ITEM_ARMOR,
        "scroll": th.C_ITEM_SCROLL,
    }
    glyph_of = {Potion: "!", Weapon: "/", Armor: "[", Scroll: "?"}

    for proto in MONSTER_TABLE:
        slots[f"monster.{proto.kind}"] = (proto.glyph, th.C_MONSTER)

    for kind, color in item_colors.items():
        glyph = next(g for cls, g in glyph_of.items() if cls.kind == kind)
        slots[f"item.{kind}"] = (glyph, color)

    for key, spec in ITEM_TABLE.items():
        glyph = glyph_of.get(spec["factory"], "?")
        slots[f"item.{key}"] = (glyph, item_colors.get(spec["factory"].kind, th.C_ITEM))
    return slots


def render_slot(glyph: str, color: str) -> Image.Image:
    """把单个字符画进 24×24 的透明画布。"""
    size = config.TILE_PX * SUPERSAMPLE
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if glyph:
        font = _font(int(size * 0.78))
        box = draw.textbbox((0, 0), glyph, font=font)
        x = (size - (box[2] - box[0])) / 2 - box[0]
        y = (size - (box[3] - box[1])) / 2 - box[1]
        draw.text((x, y), glyph, font=font, fill=color)
    return canvas.resize((config.TILE_PX, config.TILE_PX), Image.LANCZOS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出图标占位模板")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    if not manifest.entries:
        print("图标清单为空，无法导出。请先检查 assets/icons.json")
        return 1

    slots = build_slot_map()
    written = skipped = 0
    for key, spec in manifest.entries.items():
        target = manifest.base_dir / spec.file
        if target.exists() and not args.force:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        glyph, color = slots.get(key, ("?", th.TEXT))
        render_slot(glyph, color).save(target)
        written += 1
        print(f"  {key:24s} → {spec.file}")

    print(f"完成：写入 {written} 张，跳过 {skipped} 张已存在的文件")
    print(f"目录：{manifest.base_dir}")
    print("提示：回到游戏按 F12 即可看到效果；删掉这些 PNG 就恢复纯字符外观。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
