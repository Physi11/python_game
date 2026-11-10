"""把统计图表导出成 PNG，供实验报告插图。

图形构建逻辑复用 ``ui/charts.py``（与程序内「查看 → 统计图表」完全同源），
这里只负责批量保存成 300dpi 的图片文件。

用法::

    python tools/make_charts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon import config  # noqa: E402
from dungeon.stats import StatsAnalyzer  # noqa: E402
from ui.charts import build_figures, close_figures  # noqa: E402


def main() -> int:
    data_dir = ROOT / config.DATA_DIR_NAME
    records_path = data_dir / config.RECORD_FILE_NAME
    analyzer = StatsAnalyzer.from_file(records_path)

    if not analyzer.records:
        print("暂无对局记录。请先运行：python tools/balance_sim.py --games 30 --record")
        return 1

    specs = build_figures(analyzer)
    if not specs:
        print("未能构建图表：请确认已安装 matplotlib 与 pandas")
        return 1

    out_dir = data_dir / config.CHART_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = analyzer.summary()
    print(f"共 {summary['total']} 局记录，通关 {summary['wins']} 局"
          f"（{summary['win_rate']:.1%}），平均到达 {summary['avg_floor']:.2f} 层")
    print(f"平均回合 {summary['avg_turns']:.0f}，平均击杀 {summary['avg_kills']:.1f}")

    for spec in specs:
        path = out_dir / spec.filename
        spec.figure.savefig(path, dpi=300, facecolor=spec.figure.get_facecolor(),
                            bbox_inches="tight", pad_inches=0.18)
        print(f"已保存 {path.relative_to(ROOT)}")

    close_figures(specs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
