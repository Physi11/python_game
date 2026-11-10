"""把图标清单里的图片加载成 Tk 可以绘制的 ``PhotoImage``。

与 ``ui/icons.py`` 的分工：那边只做"清单解析与键查找"（纯数据、可无头单测），
这边负责真正碰 Tk 与 Pillow 的部分。

三条硬规则
----------
1. **返回的 PhotoImage 必须被本对象长期持有**。Canvas 只记 Tcl 侧的 image 名字，
   Python 对象一旦被回收，Tcl 图像随之删除，画布上的格子会变成空白。
2. **变暗版必须拆开 alpha 通道**。``Image.eval`` / ``point`` / ``Brightness``
   都会连透明度一起压，半透明图标的边缘会糊成一圈黑边。
3. **任何异常都返回 None**。图标目录是让用户自己丢文件进去的，
   出现坏图、超大图、改了扩展名的 JPG 都在所难免——一张图坏了不能让游戏起不来，
   回退到字符即可。
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from dungeon import config

from .icons import DEFAULT_BASE_DIR, IconManifest, IconSpec, lookup

try:  # Pillow 只是"推荐依赖"，没有它游戏照样能玩
    from PIL import Image, ImageTk

    PIL_OK = True
except ImportError:  # pragma: no cover - 取决于运行环境
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]
    PIL_OK = False


# Pillow 10 起把重采样常量挪进了 Image.Resampling，这里兼容新旧两版
_resampling = getattr(Image, "Resampling", Image) if PIL_OK else None
_NEAREST = getattr(_resampling, "NEAREST", 0)
_LANCZOS = getattr(_resampling, "LANCZOS", 1)

# 缩放前先压到这个尺寸，防止用户丢一张 4000×4000 的图把启动拖慢
_PREPARE_PX = 128
# 迷雾里图标的压暗比例，与 theme.DIM_FACTOR 保持一致的观感
_DIM_FACTOR = 0.6


def _dimmed(image: Any) -> Any:
    """只压暗 RGB、保留 alpha。"""
    r, g, b, a = image.convert("RGBA").split()
    rgb = Image.merge("RGB", (r, g, b)).point(lambda value: int(value * _DIM_FACTOR))
    r2, g2, b2 = rgb.split()
    return Image.merge("RGBA", (r2, g2, b2, a))


class IconSet:
    """一组按清单加载好的图标。"""

    def __init__(
        self,
        master: tk.Misc,
        manifest: IconManifest | None = None,
        size: int | None = None,
    ) -> None:
        self._master = master
        self._size = int(size or config.TILE_PX)
        self._manifest = manifest or IconManifest(entries={}, base_dir=DEFAULT_BASE_DIR)
        # 缓存里也会存 None（"这张图不存在"），避免每帧都去 stat 一次磁盘
        self._cache: dict[tuple[str, bool], Any] = {}
        self.failed: list[str] = []

    # ------------------------------------------------------------ 查询
    @property
    def manifest(self) -> IconManifest:
        return self._manifest

    def __len__(self) -> int:
        return len(self._manifest)

    def spec(self, candidates: tuple[str, ...]) -> IconSpec | None:
        return lookup(self._manifest.entries, *candidates) if candidates else None

    def image(self, candidates: tuple[str, ...], dim: bool = False) -> Any | None:
        """取候选链命中的第一个图标的 PhotoImage；没有图返回 None。"""
        spec = self.spec(candidates)
        if spec is None:
            return None
        key = (spec.key, bool(dim))
        if key in self._cache:
            return self._cache[key]
        photo = self._render(spec, dim)
        self._cache[key] = photo
        return photo

    def clear(self) -> None:
        self._cache.clear()
        self.failed.clear()

    def summary(self) -> str:
        """给状态栏用的一句话摘要。"""
        defined = len(self._manifest)
        if defined == 0:
            return "图标清单为空，全部使用字符绘制"
        return f"图标清单 {defined} 项 · Pillow {'可用' if PIL_OK else '缺失'}"

    # ------------------------------------------------------------ 渲染
    def _render(self, spec: IconSpec, dim: bool) -> Any | None:
        path = self._manifest.base_dir / spec.file
        if not path.is_file():
            return None
        try:
            if PIL_OK:
                return self._render_with_pillow(path, dim)
            return self._render_plain(path, dim)
        except Exception:  # noqa: BLE001 - 坏图不能拖垮游戏
            self.failed.append(spec.file)
            return None

    def _render_with_pillow(self, path: Path, dim: bool) -> Any | None:
        with Image.open(path) as raw:
            raw.load()
            image = raw.convert("RGBA")
        image.thumbnail((_PREPARE_PX, _PREPARE_PX), _LANCZOS)
        image = image.resize((self._size, self._size), _NEAREST)
        if dim:
            image = _dimmed(image)
        return ImageTk.PhotoImage(image, master=self._master)

    def _render_plain(self, path: Path, dim: bool) -> Any | None:
        """没有 Pillow 时的退化路径。

        ``tk.PhotoImage`` 只能整数倍 zoom / subsample，没办法把任意尺寸缩到
        24×24，所以尺寸不符就直接放弃、交给字符；也无法压暗，迷雾格一律用字符。
        """
        if dim:
            return None
        photo = tk.PhotoImage(file=str(path), master=self._master)
        if photo.width() != self._size or photo.height() != self._size:
            return None
        return photo

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<IconSet entries={len(self._manifest)} pillow={PIL_OK}>"
