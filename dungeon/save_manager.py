"""存档管理模块。

设计要点
--------
1. **只用 JSON，不用 pickle**
   - 安全：``pickle.load`` 会执行任意代码，存档一旦被替换就是后门；
   - 可移植：pickle 记录的是"模块路径 + 类名"，重命名类或调整目录就报废；
   - 可读：JSON 能直接打开看、能手工改、能贴进实验报告。
2. **原子写入**：先写 ``.tmp`` 再 ``os.replace``，中途断电也不会损毁旧存档。
3. **版本迁移**：``version`` 字段 + 迁移函数链；遇到更高版本的存档直接拒绝，
   而不是抛出一堆 ``KeyError``。
4. **损坏自愈**：JSON 解析失败时把坏档备份成 ``.bak`` 再报错，绝不静默删除用户的存档。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from . import config
from .game_state import GameState


class SaveError(Exception):
    """存档读写失败。所有对外抛出的异常都统一成这个类型，便于界面层提示。"""


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """v1 → v2：策略战斗新增了装备槽与蓄力字段。

    这些字段在 ``Player.from_dict`` / ``Monster.from_dict`` 里都有默认值，
    所以迁移是**恒等**的——真正的作用是让旧存档能通过版本检查，
    而不是被"缺少迁移方案"挡在门外。
    """
    data["version"] = 2
    return data


# 版本迁移函数链：{源版本: 升级到下一版本的函数}
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _migrate_v1_to_v2,
}


class SaveManager:
    """负责存档槽位、历史战绩文件的读写。"""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).resolve().parent.parent / config.DATA_DIR_NAME
        self.data_dir = Path(data_dir)
        self.save_dir = self.data_dir / config.SAVE_DIR_NAME
        self.chart_dir = self.data_dir / config.CHART_DIR_NAME
        self.records_path = self.data_dir / config.RECORD_FILE_NAME
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.chart_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 路径
    def slot_path(self, slot: int) -> Path:
        self._validate_slot(slot)
        return self.save_dir / f"save{slot}.json"

    @staticmethod
    def _validate_slot(slot: int) -> None:
        if not isinstance(slot, int) or not (1 <= slot <= config.SAVE_SLOTS):
            raise SaveError(f"存档槽位必须是 1~{config.SAVE_SLOTS} 之间的整数")

    # ------------------------------------------------------------ 原子写
    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        """先写临时文件、强制刷盘、再原子替换，避免写一半损坏旧档。"""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:  # pragma: no cover - 极端情况下忽略清理失败
                    pass

    # ------------------------------------------------------------ 存 / 读
    def save(self, state: GameState, slot: int = 1) -> Path:
        """把当前局面写入指定槽位。"""
        path = self.slot_path(slot)
        try:
            text = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            raise SaveError(f"状态无法序列化：{exc}") from exc
        try:
            self._atomic_write(path, text)
        except OSError as exc:
            raise SaveError(f"写入存档失败：{exc}") from exc
        return path

    def exists(self, slot: int) -> bool:
        try:
            return self.slot_path(slot).exists()
        except SaveError:
            return False

    def load(self, slot: int) -> GameState:
        """读取存档并还原成 ``GameState``。"""
        path = self.slot_path(slot)
        if not path.exists():
            raise SaveError(f"{slot} 号存档槽是空的")

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SaveError(f"无法读取存档文件：{exc}") from exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            self._quarantine(path)
            raise SaveError(f"存档已损坏（第 {exc.lineno} 行 JSON 格式错误），已备份为 .bak") from exc

        if not isinstance(data, dict):
            self._quarantine(path)
            raise SaveError("存档格式不正确：根节点应为对象")

        version = int(data.get("version", 0))
        if version > config.SAVE_VERSION:
            raise SaveError(
                f"存档版本（v{version}）高于当前程序（v{config.SAVE_VERSION}），请更新程序后再读档"
            )
        while version < config.SAVE_VERSION:
            migrate = MIGRATIONS.get(version)
            if migrate is None:
                raise SaveError(f"缺少 v{version} → v{version + 1} 的存档迁移方案")
            data = migrate(data)
            version += 1

        try:
            return GameState.from_dict(data)
        except (KeyError, ValueError, IndexError) as exc:
            self._quarantine(path)
            raise SaveError(f"存档内容不完整或已损坏：{exc}") from exc

    def _quarantine(self, path: Path) -> None:
        """把损坏的存档备份为 .bak，保留用户数据而不是直接删除。"""
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:  # pragma: no cover - 备份失败不影响主流程报错
            pass

    def delete(self, slot: int) -> None:
        path = self.slot_path(slot)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise SaveError(f"删除存档失败：{exc}") from exc

    def list_meta(self) -> list[dict[str, Any]]:
        """列出所有槽位的摘要，供读档界面展示。"""
        result: list[dict[str, Any]] = []
        for slot in range(1, config.SAVE_SLOTS + 1):
            path = self.save_dir / f"save{slot}.json"
            info: dict[str, Any] = {"slot": slot, "exists": path.exists()}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    meta = data.get("meta", {})
                    info.update(
                        {
                            "saved_at": data.get("saved_at", "未知时间"),
                            "floor": meta.get("floor", "?"),
                            "turn": meta.get("turn", "?"),
                            "preview": meta.get("preview", ""),
                        }
                    )
                except (json.JSONDecodeError, OSError, AttributeError):
                    info["preview"] = "（存档损坏）"
            result.append(info)
        return result

    # ------------------------------------------------------------ 历史战绩
    def load_records(self) -> list[dict[str, Any]]:
        """读取全部对局记录。文件不存在或损坏时返回空列表，绝不让主程序崩溃。"""
        if not self.records_path.exists():
            return []
        try:
            data = json.loads(self.records_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(data, dict):
            records = data.get("records", [])
        elif isinstance(data, list):
            records = data
        else:
            records = []
        return [r for r in records if isinstance(r, dict)]

    def append_record(self, record: dict[str, Any]) -> None:
        """追加一条对局记录。保留最近 500 局，避免文件无限膨胀。"""
        records = self.load_records()
        records.append(record)
        records = records[-500:]
        payload = {"version": 1, "count": len(records), "records": records}
        try:
            self._atomic_write(
                self.records_path, json.dumps(payload, ensure_ascii=False, indent=2)
            )
        except OSError as exc:  # pragma: no cover - 磁盘异常
            raise SaveError(f"写入战绩记录失败：{exc}") from exc

    def clear_records(self) -> None:
        """清空战绩记录（菜单里提供，便于重新统计）。"""
        self._atomic_write(
            self.records_path, json.dumps({"version": 1, "count": 0, "records": []}, indent=2)
        )
