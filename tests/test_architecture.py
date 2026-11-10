"""架构守卫测试。

用代码来保证"逻辑层不依赖界面层"这条设计约定不被无意破坏：
只要有人在 ``dungeon/`` 目录里写了 ``import tkinter``，这条用例就会失败。

这类"把架构约定变成可执行断言"的做法，比写在文档里靠自觉遵守更可靠，
也是本项目模块化设计的直接证据。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN_MODULES = ("tkinter", "PIL", "matplotlib", "pandas")


class TestLayerSeparation(unittest.TestCase):
    """逻辑层与表现层的隔离。"""

    def test_logic_layer_has_no_gui_imports(self) -> None:
        package = ROOT / "dungeon"
        pattern = re.compile(
            r"^\s*(?:import|from)\s+(" + "|".join(FORBIDDEN_MODULES) + r")\b",
            re.MULTILINE,
        )
        offenders: list[str] = []
        for path in sorted(package.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                # stats.py 允许在 try 块中做可选的 pandas 降级导入
                if path.name == "stats.py" and match.group(1) == "pandas":
                    continue
                offenders.append(f"{path.name}: {match.group(1)}")
        self.assertEqual(offenders, [], f"逻辑层出现了界面/绘图库依赖：{offenders}")

    def test_ui_layer_has_no_rule_logic(self) -> None:
        """界面层不应该出现伤害公式、地图生成之类的规则代码。"""
        ui_dir = ROOT / "ui"
        if not ui_dir.exists():
            self.skipTest("界面层尚未创建")
        suspicious = ("base_damage", "resolve_attack", "Dungeon.generate", "MONSTER_TABLE")
        offenders: list[str] = []
        for path in sorted(ui_dir.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for token in suspicious:
                if token in text:
                    offenders.append(f"{path.name}: {token}")
        self.assertEqual(offenders, [], f"界面层出现了业务规则：{offenders}")

    def test_icon_manifest_module_is_headless(self) -> None:
        """``ui/icons.py`` 必须保持纯数据操作，否则图标测试就需要显示器了。"""
        path = ROOT / "ui" / "icons.py"
        self.assertTrue(path.is_file(), "缺少 ui/icons.py")
        text = path.read_text(encoding="utf-8")
        for token in ("import tkinter", "from tkinter", "from PIL", "import PIL"):
            self.assertNotIn(
                token, text, f"ui/icons.py 不应出现 {token!r}，它必须能无头运行"
            )


class TestModuleSurface(unittest.TestCase):
    """公共 API 的稳定性。"""

    def test_package_exports(self) -> None:
        import dungeon

        for name in ("GameState", "Dungeon", "Player", "Monster", "Rng", "SaveManager"):
            self.assertTrue(hasattr(dungeon, name), f"dungeon 未导出 {name}")

    def test_log_entry_shape(self) -> None:
        """日志条目必须是 (文本, 分类) 二元组，界面层依赖这个约定着色。"""
        from dungeon.game_state import GameState

        state = GameState.new_game(seed=1)
        for entry in state.recent_log(5):
            self.assertEqual(len(entry), 2)
            self.assertIsInstance(entry[0], str)
            self.assertIsInstance(entry[1], str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
