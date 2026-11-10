"""存档系统测试。

重点验证三件事：
1. 存读往返后关键字段完全一致；
2. 随机数状态能精确复原（否则读档后怪物行为会漂移）；
3. 损坏存档、版本过新等异常情况给出可读的 SaveError，而不是崩溃。
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

from dungeon import config
from dungeon.game_state import GameState
from dungeon.save_manager import SaveError, SaveManager


class SaveTestBase(unittest.TestCase):
    """为每个用例准备一个独立的临时数据目录，互不干扰。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = SaveManager(Path(self._tmp.name))
        self.state = GameState.new_game(seed=20261025)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestSaveRoundtrip(SaveTestBase):
    """正常路径：存 → 读 → 一致。"""

    def test_roundtrip_keeps_state(self) -> None:
        # 先走几步、打几下，让状态"脏"起来，才能验证真的存下来了
        for _ in range(30):
            self.state.try_move(1, 0)
        self.manager.save(self.state, 1)
        restored = self.manager.load(1)

        self.assertEqual(restored.player.pos, self.state.player.pos)
        self.assertEqual(restored.player.hp, self.state.player.hp)
        self.assertEqual(restored.player.gold, self.state.player.gold)
        self.assertEqual(restored.floor, self.state.floor)
        self.assertEqual(restored.turn, self.state.turn)
        self.assertEqual(restored.dungeon.to_rows(), self.state.dungeon.to_rows())
        self.assertEqual(restored.dungeon.stairs, self.state.dungeon.stairs)
        self.assertEqual(len(restored.monsters), len(self.state.monsters))
        self.assertEqual(len(restored.items_on_floor), len(self.state.items_on_floor))
        self.assertEqual(
            [item.key for item in restored.player.inventory],
            [item.key for item in self.state.player.inventory],
        )

    def test_rng_state_reproducible(self) -> None:
        """读档后的随机序列必须与存档时完全一致。

        这是"读档后怪物行为漂移"这类隐蔽 bug 的守门测试。
        """
        self.manager.save(self.state, 1)
        expected = [self.state.rng.randint(0, 10**9) for _ in range(10)]

        restored = self.manager.load(1)
        actual = [restored.rng.randint(0, 10**9) for _ in range(10)]
        self.assertEqual(expected, actual)

    def test_save_then_delete(self) -> None:
        self.manager.save(self.state, 2)
        self.assertTrue(self.manager.exists(2))
        self.manager.delete(2)
        self.assertFalse(self.manager.exists(2))

    def test_list_meta(self) -> None:
        self.manager.save(self.state, 1)
        metas = self.manager.list_meta()
        self.assertEqual(len(metas), config.SAVE_SLOTS)
        self.assertTrue(metas[0]["exists"])
        self.assertIn("第 1 层", metas[0]["preview"])


class TestSaveAbnormal(SaveTestBase):
    """异常路径：坏文件、缺字段、版本过新。"""

    def test_load_empty_slot_raises(self) -> None:
        with self.assertRaises(SaveError):
            self.manager.load(3)

    def test_corrupted_json_raises_and_backs_up(self) -> None:
        self.manager.save(self.state, 1)
        path = self.manager.slot_path(1)
        path.write_text("{ 这不是合法 JSON ", encoding="utf-8")

        with self.assertRaises(SaveError) as ctx:
            self.manager.load(1)
        self.assertIn("损坏", str(ctx.exception))

        backup = path.with_suffix(path.suffix + ".bak")
        self.assertTrue(backup.exists(), "损坏的存档应该被备份，而不是被删除")
        self.assertTrue(path.exists(), "原始文件不应被自动删除")

    def test_missing_required_field(self) -> None:
        """删掉 player 字段后应报"内容不完整"而不是 KeyError 崩溃。"""
        data = self.state.to_dict()
        del data["player"]
        self.manager.slot_path(1).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        with self.assertRaises(SaveError) as ctx:
            self.manager.load(1)
        self.assertIn("不完整", str(ctx.exception))

    def test_version_too_new(self) -> None:
        data = self.state.to_dict()
        data["version"] = 99
        self.manager.slot_path(1).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        with self.assertRaises(SaveError) as ctx:
            self.manager.load(1)
        self.assertIn("版本", str(ctx.exception))

    def test_invalid_slot_number(self) -> None:
        with self.assertRaises(SaveError):
            self.manager.save(self.state, 0)
        with self.assertRaises(SaveError):
            self.manager.save(self.state, config.SAVE_SLOTS + 1)

    def test_records_append_and_load(self) -> None:
        record = self.state.build_record()
        self.manager.append_record(record)
        self.manager.append_record(dict(record, id="second"))
        records = self.manager.load_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1]["id"], "second")


if __name__ == "__main__":
    unittest.main(verbosity=2)
