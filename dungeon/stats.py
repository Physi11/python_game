"""对局统计分析模块。

对外提供两层能力：

1. ``summary()`` —— 纯 Python 聚合出的关键指标，**不依赖 pandas**，
   即使环境里没有安装 pandas，界面上的排行榜与结算统计依然可用；
2. ``to_dataframe()`` —— 转换成 pandas DataFrame，供 ``tools/make_charts.py``
   做透视与绘图。

这种"核心指标纯手写、图表另用 pandas"的分层，是为了让主程序在缺少
第三方库时也能完整运行，符合"异常处理与降级"的设计要求。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

try:  # pragma: no cover - 取决于运行环境是否安装 pandas
    import pandas as pd

    PANDAS_OK = True
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]
    PANDAS_OK = False


class StatsAnalyzer:
    """对 ``records.json`` 中的对局记录做统计。"""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = [r for r in records if isinstance(r, dict)]

    # ------------------------------------------------------------ 构造
    @classmethod
    def from_file(cls, path: Path | str) -> "StatsAnalyzer":
        """从 records.json 读取。文件不存在时得到一个空分析器而不是异常。"""
        import json

        path = Path(path)
        if not path.exists():
            return cls([])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls([])
        records = data.get("records", []) if isinstance(data, dict) else data
        return cls(records if isinstance(records, list) else [])

    # ------------------------------------------------------------ 指标
    def summary(self) -> dict[str, Any]:
        """核心指标汇总，纯 Python 实现。"""
        total = len(self.records)
        if total == 0:
            return {
                "total": 0, "wins": 0, "win_rate": 0.0, "avg_floor": 0.0,
                "best_floor": 0, "avg_turns": 0.0, "avg_kills": 0.0,
                "avg_duration": 0.0, "avg_damage_dealt": 0.0,
                "avg_damage_taken": 0.0, "top_death_cause": "—",
                "deaths_by_cause": Counter(), "deaths_by_floor": Counter(),
            }

        def mean(key: str) -> float:
            values = [float(r.get(key, 0) or 0) for r in self.records]
            return sum(values) / len(values) if values else 0.0

        wins = sum(1 for r in self.records if r.get("result") == "win")
        deaths = [r for r in self.records if r.get("result") != "win"]
        causes = Counter(str(r.get("death_cause") or "未记录原因") for r in deaths)
        floors = Counter(int(r.get("max_floor", 0) or 0) for r in deaths)

        return {
            "total": total,
            "wins": wins,
            "win_rate": wins / total,
            "avg_floor": mean("max_floor"),
            "best_floor": max((int(r.get("max_floor", 0) or 0) for r in self.records), default=0),
            "avg_turns": mean("turns"),
            "avg_kills": mean("kills"),
            "avg_duration": mean("duration_sec"),
            "avg_damage_dealt": mean("damage_dealt"),
            "avg_damage_taken": mean("damage_taken"),
            "top_death_cause": causes.most_common(1)[0][0] if causes else "—",
            "deaths_by_cause": causes,
            "deaths_by_floor": floors,
        }

    def floor_average_stay(self) -> dict[int, float]:
        """每一层的平均停留回合数，用于判断节奏是否均匀。"""
        buckets: dict[int, list[int]] = {}
        for record in self.records:
            for floor, turns in (record.get("floor_stay") or {}).items():
                try:
                    buckets.setdefault(int(floor), []).append(int(turns))
                except (TypeError, ValueError):
                    continue
        return {floor: sum(v) / len(v) for floor, v in sorted(buckets.items()) if v}

    def leaderboard(self, limit: int = 10) -> list[dict[str, Any]]:
        """排行榜：先按到达层数降序，再按击杀数降序。"""
        ranked = sorted(
            self.records,
            key=lambda r: (int(r.get("max_floor", 0) or 0), int(r.get("kills", 0) or 0)),
            reverse=True,
        )
        return ranked[:limit]

    # ------------------------------------------------------------ pandas
    def to_dataframe(self) -> Any:
        """转换成 DataFrame（需要安装 pandas）。未安装时返回 None。"""
        if not PANDAS_OK:  # pragma: no cover
            return None
        if not self.records:
            return pd.DataFrame()
        frame = pd.json_normalize(self.records)
        if "ended_at" in frame.columns:
            frame["ended_at"] = pd.to_datetime(frame["ended_at"], errors="coerce")
        if "duration_sec" in frame.columns:
            frame["duration_min"] = frame["duration_sec"] / 60.0
        if "damage_taken" in frame.columns and "damage_dealt" in frame.columns:
            frame["kd_ratio"] = frame["damage_dealt"] / frame["damage_taken"].replace(0, 1)
        frame["is_win"] = frame["result"].eq("win") if "result" in frame.columns else False
        return frame

    def floor_stay_frame(self) -> Any:
        """把 floor_stay 字典展开成 (层数, 停留回合) 的长表，供聚合使用。"""
        if not PANDAS_OK:  # pragma: no cover
            return None
        rows: list[dict[str, Any]] = []
        for record in self.records:
            for floor, turns in (record.get("floor_stay") or {}).items():
                rows.append({"floor": int(floor), "turns": int(turns)})
        return pd.DataFrame(rows)
