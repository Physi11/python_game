"""图标清单的解析与查找测试。

``ui/icons.py`` 刻意不导入 tkinter / Pillow，所以这些用例**不需要显示器**，
可以和其余测试一起在 ``python -m unittest discover -s tests`` 里跑完。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.icons import (
    DEFAULT_MANIFEST_PATH,
    IconManifestError,
    item_candidates,
    load_manifest,
    lookup,
    monster_candidates,
)


class ManifestCase(unittest.TestCase):
    """提供一个"写临时清单文件"的小工具。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_manifest(self, payload: object) -> Path:
        path = self.tmp_dir / "icons.json"
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


class TestManifestLoading(ManifestCase):
    """清单解析的容错行为。"""

    def test_missing_file_returns_empty(self) -> None:
        """清单不存在时返回空表，游戏照常运行（全部回退字符）。"""
        manifest = load_manifest(self.tmp_dir / "nope.json")
        self.assertEqual(len(manifest.entries), 0)
        self.assertTrue(manifest.base_dir.is_absolute())

    def test_invalid_json_raises_typed_error(self) -> None:
        """坏 JSON 抛 IconManifestError，而不是让 json 的异常直接冒出去。"""
        path = self.write_manifest("{ 这不是 JSON ")
        with self.assertRaises(IconManifestError) as ctx:
            load_manifest(path)
        self.assertIn("JSON", str(ctx.exception))

    def test_unsupported_version_rejected(self) -> None:
        path = self.write_manifest({"version": 99, "entries": {}})
        with self.assertRaises(IconManifestError) as ctx:
            load_manifest(path)
        self.assertIn("99", str(ctx.exception))

    def test_entry_without_file_is_skipped(self) -> None:
        """缺 file 字段的条目不参与匹配，避免"声明了却永远加载不到"。"""
        path = self.write_manifest(
            {"version": 1, "entries": {"player": {"label": "玩家"}, "door": {"file": "door.png"}}}
        )
        manifest = load_manifest(path)
        self.assertNotIn("player", manifest.entries)
        self.assertIn("door", manifest.entries)

    def test_absolute_or_non_png_file_is_skipped(self) -> None:
        """绝对路径会把工程绑死在本机，非 png 则可能加载不了，一律拒绝。"""
        path = self.write_manifest(
            {
                "version": 1,
                "entries": {
                    "a": {"file": "C:/Windows/x.png"},
                    "b": {"file": "/usr/share/x.png"},
                    "c": {"file": "../escape.png"},
                    "d": {"file": "x.jpg"},
                    "e": {"file": "ok/item.png"},
                },
            }
        )
        manifest = load_manifest(path)
        self.assertEqual(sorted(manifest.entries), ["e"])

    def test_base_dir_is_resolved_against_project_root(self) -> None:
        path = self.write_manifest({"version": 1, "base_dir": "assets/icons", "entries": {}})
        manifest = load_manifest(path)
        self.assertTrue(manifest.base_dir.is_absolute())
        self.assertEqual(manifest.base_dir.name, "icons")

    def test_tint_is_parsed_and_validated(self) -> None:
        """tint 必须是 #rrggbb，写错就忽略而不是让整条图标失效。"""
        path = self.write_manifest(
            {
                "version": 1,
                "entries": {
                    "a": {"file": "a.png", "tint": "#E05A5A"},
                    "b": {"file": "b.png", "tint": "red"},
                    "c": {"file": "c.png"},
                },
            }
        )
        manifest = load_manifest(path)
        self.assertEqual(manifest.entries["a"].tint, "#E05A5A")
        self.assertEqual(manifest.entries["b"].tint, "")
        self.assertEqual(manifest.entries["c"].tint, "")

    def test_shipped_manifest_is_valid(self) -> None:
        """项目自带的那份清单必须能正常解析，且每条都是相对 .png。"""
        self.assertTrue(DEFAULT_MANIFEST_PATH.is_file(), "assets/icons.json 不见了")
        manifest = load_manifest()
        self.assertGreaterEqual(len(manifest.entries), 15)
        for spec in manifest.entries.values():
            self.assertTrue(spec.file.endswith(".png"), spec.file)
            self.assertFalse(spec.file.startswith("/"), spec.file)
            self.assertNotIn("..", spec.file)


class TestLookup(ManifestCase):
    """三级回退：专属 → 类别 → 通用。"""

    def setUp(self) -> None:
        super().setUp()
        self.manifest = load_manifest(
            self.write_manifest(
                {
                    "version": 1,
                    "entries": {
                        "item.potion": {"file": "item/potion.png"},
                        "item": {"file": "item/_default.png"},
                    },
                }
            )
        )

    def test_exact_key_wins(self) -> None:
        """专属图标存在时，不能退到类别或通用。"""
        manifest = load_manifest(
            self.write_manifest(
                {
                    "version": 1,
                    "entries": {
                        "item.potion": {"file": "item/potion.png"},
                        "item.potion_small": {"file": "item/potion_small.png"},
                    },
                }
            )
        )
        spec = lookup(manifest.entries, *item_candidates("potion_small", "potion"))
        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "item.potion_small")

    def test_falls_back_to_kind(self) -> None:
        spec = lookup(self.manifest.entries, *item_candidates("potion_small", "potion"))
        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "item.potion")

    def test_falls_back_to_root(self) -> None:
        spec = lookup(self.manifest.entries, *item_candidates("sword_iron", "weapon"))
        self.assertIsNotNone(spec)
        self.assertEqual(spec.key, "item")

    def test_unknown_key_returns_none(self) -> None:
        """清单里一条都没有时返回 None，由调用方回退到字符绘制。"""
        self.assertIsNone(lookup({}, "player"))
        self.assertIsNone(lookup(self.manifest.entries, "monster.goblin"))

    def test_item_candidates_order(self) -> None:
        self.assertEqual(
            item_candidates("sword_iron", "weapon"),
            ("item.sword_iron", "item.weapon", "item"),
        )

    def test_monster_candidates_order(self) -> None:
        self.assertEqual(monster_candidates("goblin"), ("monster.goblin", "monster"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
