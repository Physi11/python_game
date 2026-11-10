"""图标资源清单的解析与查找。

这个模块**刻意不导入 tkinter 或 Pillow**，只做纯数据操作，
因此可以在没有显示器的环境下单元测试（见 ``tests/test_icons.py``）。
真正的图片加载与缩放放在 ``ui/icon_set.py``。

清单文件是 ``assets/icons.json``，用户只需把 PNG 放到 ``base_dir`` 下
清单声明的路径，重启（或按 F12）即可生效，不用改任何代码。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from dungeon import config

_TINT_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# 项目根目录。不能用相对路径或 CWD：run.bat 双击启动与 IDE 启动的工作目录不同
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = ROOT / config.ICON_MANIFEST_PATH
DEFAULT_BASE_DIR = DEFAULT_MANIFEST_PATH.parent / "icons"
SUPPORTED_VERSION = 1


class IconManifestError(Exception):
    """图标清单本身有问题（版本不支持、JSON 语法错）。"""


@dataclass(frozen=True)
class IconSpec:
    """清单里的一条图标声明。

    ``tint`` 是可选的颜色（``#rrggbb``）。game-icons 下载的是纯白剪影，
    加载时乘以这个颜色就能得到"红色怪物 / 青色玩家 / 金色道具"，
    不必为每种颜色单独存一份素材。
    """

    key: str
    file: str
    label: str = ""
    tint: str = ""

    @property
    def display_name(self) -> str:
        return self.label or self.key


@dataclass(frozen=True)
class IconManifest:
    """解析后的清单：条目表 + 图片根目录（绝对路径）。"""

    entries: dict[str, IconSpec]
    base_dir: Path

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, key: object) -> bool:
        return key in self.entries


def _resolve_base_dir(raw: object) -> Path:
    """把清单里的 base_dir 解析成绝对路径；缺省用 assets/icons。"""
    if isinstance(raw, str) and raw.strip():
        candidate = Path(raw.strip())
        return candidate if candidate.is_absolute() else (ROOT / candidate)
    return DEFAULT_BASE_DIR


def _valid_file(value: object) -> str | None:
    """校验一条 file 声明，合法则返回规范化后的相对路径。

    只接受**相对路径 + .png**：绝对路径会把工程绑死在某台机器上，
    其他格式则可能被 Pillow 之外的加载路径拒绝。
    """
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\\", "/")
    if not text or text.startswith("/") or ":" in text or ".." in text.split("/"):
        return None
    if not text.lower().endswith(".png"):
        return None
    return text


def load_manifest(path: Path | str | None = None) -> IconManifest:
    """读取图标清单。

    - 文件不存在（含整个 ``assets/`` 目录都不存在）→ 返回空清单，不抛异常；
      游戏照常运行，所有图标回退成字符。
    - JSON 语法错误 / 版本不支持 → 抛 ``IconManifestError``，由调用方提示用户。
    - 单条条目不合法（缺 file、绝对路径、非 png）→ 跳过该条，不影响其它条目。
    """
    manifest_path = Path(path) if path is not None else DEFAULT_MANIFEST_PATH
    if not manifest_path.is_file():
        return IconManifest(entries={}, base_dir=DEFAULT_BASE_DIR)

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IconManifestError(
            f"图标清单不是合法的 JSON（第 {exc.lineno} 行第 {exc.colno} 列）"
        ) from exc
    except OSError as exc:
        raise IconManifestError(f"无法读取图标清单：{exc}") from exc

    if not isinstance(data, dict):
        raise IconManifestError("图标清单的根节点应该是一个对象")

    version = data.get("version", SUPPORTED_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError) as exc:
        raise IconManifestError(f"图标清单的 version 字段不是整数：{version!r}") from exc
    if version != SUPPORTED_VERSION:
        raise IconManifestError(
            f"图标清单版本为 v{version}，当前程序只支持 v{SUPPORTED_VERSION}"
        )

    base_dir = _resolve_base_dir(data.get("base_dir"))
    raw_entries = data.get("entries")
    entries: dict[str, IconSpec] = {}
    if isinstance(raw_entries, dict):
        for key, item in raw_entries.items():
            if not isinstance(key, str) or not key.strip():
                continue
            if not isinstance(item, dict):
                continue
            file_name = _valid_file(item.get("file"))
            if file_name is None:
                continue
            label = item.get("label")
            raw_tint = item.get("tint")
            tint = raw_tint if isinstance(raw_tint, str) and _TINT_PATTERN.match(raw_tint) else ""
            entries[key.strip()] = IconSpec(
                key=key.strip(),
                file=file_name,
                label=label.strip() if isinstance(label, str) else "",
                tint=tint,
            )

    return IconManifest(entries=entries, base_dir=base_dir)


def lookup(entries: dict[str, IconSpec], *candidates: str) -> IconSpec | None:
    """按候选顺序取第一个命中的条目，全不中返回 ``None``。

    用显式候选链而不是"去掉最后一段"的字符串回退：后者表达不了
    ``item.<kind>`` 这一级（``item.sword_iron`` 去掉尾段只能得到 ``item``）。
    """
    for key in candidates:
        spec = entries.get(key)
        if spec is not None:
            return spec
    return None


def item_candidates(item_key: str, kind: str) -> tuple[str, ...]:
    """道具的三个候选键：专属 → 类别 → 通用。"""
    return (f"item.{item_key}", f"item.{kind}", "item")


def monster_candidates(kind: str) -> tuple[str, ...]:
    """怪物的两个候选键：专属 → 通用。"""
    return (f"monster.{kind}", "monster")
