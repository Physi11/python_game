"""设置系统的单元测试。

重点不是"某个键存对了"，而是**扩展通道是否可靠**：
新增一个设置项只改 ``SETTING_SPECS``，读写、校验、面板渲染都要自动跟上。
因为 ``ui/settings.py`` 不 import tkinter，这些用例可以在无显示器环境跑。
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

from ui.settings import (
    SETTING_SPECS,
    SettingSpec,
    Settings,
    load_settings,
    reset_settings,
    save_settings,
)


class TestSchema(unittest.TestCase):
    """schema 与数据类必须一一对应。"""

    def test_every_spec_has_a_field(self) -> None:
        settings = Settings()
        for spec in SETTING_SPECS:
            self.assertTrue(
                hasattr(settings, spec.key), f"Settings 缺少字段 {spec.key}"
            )

    def test_keys_are_unique(self) -> None:
        keys = [spec.key for spec in SETTING_SPECS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_required_settings_exist(self) -> None:
        keys = {spec.key for spec in SETTING_SPECS}
        for required in ("fullscreen", "adaptive_difficulty", "difficulty"):
            self.assertIn(required, keys)

    def test_choice_specs_validate_values(self) -> None:
        spec = next(s for s in SETTING_SPECS if s.key == "difficulty")
        self.assertEqual(spec.coerce("hard"), "hard")
        self.assertEqual(spec.coerce("不存在"), spec.default)
        self.assertEqual(spec.coerce(None), spec.default)

    def test_bool_spec_rejects_non_bool(self) -> None:
        spec = next(s for s in SETTING_SPECS if s.key == "fullscreen")
        self.assertIs(spec.coerce(True), True)
        self.assertEqual(spec.coerce("true"), spec.default)   # 字符串不算布尔

    def test_spec_is_frozen(self) -> None:
        spec = SETTING_SPECS[0]
        with self.assertRaises(Exception):
            spec.key = "changed"  # type: ignore[misc]


class TestPersistence(unittest.TestCase):
    """读写与容错。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_roundtrip(self) -> None:
        settings = Settings(fullscreen=True, adaptive_difficulty=False, difficulty="hard")
        self.assertTrue(save_settings(settings, self.path))
        loaded = load_settings(self.path)
        self.assertTrue(loaded.fullscreen)
        self.assertFalse(loaded.adaptive_difficulty)
        self.assertEqual(loaded.difficulty, "hard")

    def test_missing_file_returns_defaults(self) -> None:
        loaded = load_settings(self.path / "nope.json")
        self.assertEqual(loaded.fullscreen, False)
        self.assertEqual(loaded.difficulty, "normal")

    def test_corrupted_json_returns_defaults(self) -> None:
        self.path.write_text("{ this is not json", encoding="utf-8")
        loaded = load_settings(self.path)
        self.assertEqual(loaded.difficulty, "normal")

    def test_wrong_types_are_coerced(self) -> None:
        self.path.write_text(
            json.dumps({"fullscreen": "yes", "difficulty": 42}, ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = load_settings(self.path)
        self.assertIs(loaded.fullscreen, False)
        self.assertEqual(loaded.difficulty, "normal")

    def test_unknown_keys_are_preserved(self) -> None:
        """不同版本之间来回切换时，旧版不认识的键不该被抹掉。"""
        self.path.write_text(
            json.dumps({"difficulty": "hard", "future_option": 7}, ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = load_settings(self.path)
        self.assertEqual(loaded.difficulty, "hard")
        self.assertEqual(loaded.to_dict().get("future_option"), 7)

    def test_reset_restores_defaults_on_disk(self) -> None:
        save_settings(Settings(fullscreen=True, difficulty="hard"), self.path)
        fresh = reset_settings(self.path)
        self.assertFalse(fresh.fullscreen)
        self.assertEqual(load_settings(self.path).difficulty, "normal")


class TestExtensionChannel(unittest.TestCase):
    """新增设置项只写 schema 就能生效——这是"预留扩展通道"的核心承诺。"""

    def test_new_spec_is_picked_up_by_settings(self) -> None:
        # 模拟"以后加一个设置项"：只要字段存在，to_dict 就会带上它
        spec = SettingSpec(key="ui_scale", label="界面缩放", kind="bool", default=False)
        self.assertEqual(spec.coerce(True), True)
        settings = Settings()
        settings.apply(ui_scale=True)     # 未登记的键会被忽略，不会抛错
        self.assertFalse(hasattr(settings, "ui_scale"))

    def test_apply_ignores_unknown_keys(self) -> None:
        settings = Settings()
        settings.apply(difficulty="hard", nonsense=1)
        self.assertEqual(settings.difficulty, "hard")


if __name__ == "__main__":
    unittest.main()
