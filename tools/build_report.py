"""把 ``docs/report_source.md`` 组装成课程报告的 .docx。

为什么用脚本而不是手工在 Word 里排：
报告里有 15 张插图、若干表格与三级标题，手工排版既慢又容易错位；
把"内容"与"排版"分开——内容写在 Markdown 里，排版交给这套脚本——
改动一处内容后重跑一次即可，不会破坏整体格式。

依赖本地 editor_sdk 服务（WorkBuddy 的本地 Office 编辑通道），
通过其命令行封装 ``edsdk.py`` 调用。

用法::

    python tools/build_report.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "report_source.md"
TARGET = ROOT / "docs" / "Python程序设计课程报告.docx"

EDSDK_DIR = Path(
    r"D:\Programs\WorkBuddy\resources\app.asar.unpacked\resources\plugins"
    r"\workbuddy-builtin\skills\workbuddy-local-office-edit"
)
EDSDK = EDSDK_DIR / "edsdk.py"
PYTHON = sys.executable

# 图片 → 图注。图号与正文中的引用一一对应
CAPTIONS: dict[str, str] = {
    "docs/flowcharts/01_主循环.png": "图 1  游戏主循环流程图",
    "docs/flowcharts/02_地图生成.png": "图 2  地牢地图生成流程图",
    "docs/flowcharts/03_战斗结算.png": "图 3  战斗结算流程图",
    "docs/screenshots/08_策略战斗.png": "图 4  策略战斗：蓝色瞄准范围、红色敌方预告与头顶倒计时",
    "docs/screenshots/01_开局界面.png": "图 5  游戏主界面（开局）",
    "docs/screenshots/02_探索与战斗.png": "图 6  探索过程中的战争迷雾与彩色日志",
    "docs/screenshots/03_操作说明.png": "图 7  操作说明窗口",
    "docs/screenshots/04_背包.png": "图 8  背包窗口",
    "docs/screenshots/05_结算.png": "图 9  本局结算窗口",
    "docs/screenshots/07_排行榜.png": "图 10  历史战绩排行榜",
    "docs/screenshots/06_统计图表.png": "图 11  程序内统计图表窗口",
    "data/charts/01_到达层数趋势.png": "图 12  最近对局到达层数变化",
    "data/charts/02_难度分布.png": "图 13  阵亡层数分布与死因统计",
    "data/charts/03_战斗效率.png": "图 14  回合数与击杀数的关系",
    "data/charts/04_分层节奏.png": "图 15  各层平均停留回合",
    "data/charts/05_结果构成.png": "图 16  对局结果构成",
    "docs/test_output.png": "图 17  单元测试运行结果",
}

IMG_PATTERN = re.compile(r"^\[\[img:([^:\]]+):(\d+)\]\]\s*$", re.MULTILINE)


# ------------------------------------------------------------------ 调用封装
def call(tool: str, params: dict, retries: int = 0) -> dict:
    """调用一个 editor_sdk 工具，返回结果字典。

    大部分工具返回 JSON 对象，但 ``create_doc`` / ``save_file`` 这类
    只返回一行人类可读文本，此时包装成 ``{"_raw": 文本}`` 交给调用方处理。

    **默认不重试**：插入类操作不是幂等的，一旦服务端已经写入但返回了非零退出码，
    重试会把同一段内容插两次——上一版报告里 4.2 / 4.3 各出现两遍就是这么来的。
    """
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(params, handle, ensure_ascii=False)
        args_file = handle.name
    last_error = ""
    for _ in range(retries + 1):
        proc = subprocess.run(
            [PYTHON, str(EDSDK), "call", tool, "--json-file", args_file],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(EDSDK_DIR),
        )
        out = (proc.stdout or "").strip()
        if out and proc.returncode == 0:
            for line in reversed(out.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        return json.loads(line)
                    except json.JSONDecodeError:
                        continue
            return {"_raw": out}
        last_error = (proc.stderr or out or "无输出")[-400:]
    raise RuntimeError(f"{tool} 调用失败：{last_error}")


def extract_file_id(result: dict) -> str:
    """从 create_doc 的返回里取出 file_id（兼容 JSON 与纯文本两种形态）。"""
    for key in ("file_id", "fileId"):
        if result.get(key):
            return str(result[key])
    match = re.search(r"file_id=([^\s,]+)", result.get("_raw", ""))
    return match.group(1) if match else ""


def last_pos(file_id: str) -> int:
    """文档末尾的可插入位置，链式追加的兜底方案。"""
    return int(call("doc_get_last_operable_pos", {"file_id": file_id})["position"])


def insert_md(file_id: str, idx: int, markdown: str) -> int:
    """插入一段 Markdown；失败时跳过并告警，绝不重复插入。

    块已经被拆到"单段落"粒度，正常情况下不会失败。真失败时宁可缺一段，
    也不要让同一段出现两遍——后者更难发现。
    """
    try:
        return _insert_md_once(file_id, idx, markdown)
    except RuntimeError as exc:
        print(f"  [跳过一段] {markdown[:40]!r}：{str(exc)[:80]}")
        return idx


def _insert_md_once(file_id: str, idx: int, markdown: str) -> int:
    fd, name = tempfile.mkstemp(suffix=".md")
    os.close(fd)                      # 必须先关闭句柄，否则 Windows 下无法删除
    tmp = Path(name)
    tmp.write_text(markdown, encoding="utf-8")
    try:
        result = call(
            "doc_insert_markdown",
            {"file_id": file_id, "idx": idx, "markdown": f"file://{tmp.as_posix()}"},
        )
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:                # 服务端可能仍持有句柄，留给系统清理
            pass
    return int(result.get("position") or result.get("last_edit_index") or last_pos(file_id))


def insert_para(file_id: str, idx: int, text: str, *, size: float | None = None,
                bold: bool = False, jc: str = "left", color: str | None = None,
                font: str | None = None, level: int = 0) -> int:
    fmt: dict = {}
    if size is not None:
        fmt["font_size"] = size
    if bold:
        fmt["bold"] = True
    if color:
        fmt["color"] = color
    if font:
        fmt["font_family"] = font
    params = {
        "file_id": file_id,
        "idx": idx,
        "text": text,
        "level": level,
        "paragraph_property": {"jc": jc},
    }
    if fmt:
        params["text_format"] = fmt
    try:
        result = call("doc_insert_paragraph_with_text", params)
    except RuntimeError:
        # 文档末尾的坐标偶尔会越界，重新问一次真实末尾再插
        params["idx"] = last_pos(file_id)
        result = call("doc_insert_paragraph_with_text", params)
    return int(result.get("next_index") or result.get("position") or last_pos(file_id))


# ------------------------------------------------------------------ 解析内容
def split_block(markdown: str) -> list[str]:
    """把一段 Markdown 拆成"一个段落 / 一个列表 / 一张表"级别的原子块。

    为什么要拆到这么细：编辑器的整块插入不是原子操作——遇到"粗体 + 行内代码 +
    列表"混排的复杂段落时，它可能先写进去一半再报错。若此时再retry或拆小重试，
    结果就是同一段内容在文档里出现两遍（上一版 4.2/4.3 各出现两次即如此）。
    拆成单段落之后每次插入都很小，实测不会再中途失败。
    """
    parts = [p.strip() for p in markdown.split("\n\n") if p.strip()]
    return parts or [markdown.strip()]


def parse_blocks() -> list[tuple[str, object]]:
    """把 Markdown 拆成 ('md', 文本) 与 ('img', 路径, 宽度) 两类块。"""
    text = SOURCE.read_text(encoding="utf-8")
    blocks: list[tuple[str, object]] = []
    cursor = 0
    for match in IMG_PATTERN.finditer(text):
        chunk = text[cursor:match.start()].strip()
        if chunk:
            blocks.extend(("md", part) for part in split_block(chunk))
        blocks.append(("img", (match.group(1), int(match.group(2)))))
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        blocks.extend(("md", part) for part in split_block(tail))
    return blocks


def _display_width(text: str) -> int:
    """估算显示宽度：中文算 2、西文算 1。用来推断表格各列的相对宽窄。"""
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def table_column_weights(markdown: str) -> list[list[float]]:
    """从 Markdown 里提取每张表各列的内容宽度，作为列宽比例的参考。"""
    tables: list[list[float]] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("|"):
            index += 1
            continue
        rows: list[str] = []
        while index < len(lines) and lines[index].strip().startswith("|"):
            rows.append(lines[index].strip())
            index += 1
        # 去掉 | --- | 这样的分隔行
        body = [r for r in rows if not re.fullmatch(r"\|[\s:\-|]+\|", r)]
        if not body:
            continue
        columns = [c.strip() for c in body[0].strip("|").split("|")]
        widths = [0] * len(columns)
        for row in body[1:] or body:
            cells = [c.strip() for c in row.strip("|").split("|")]
            for col, cell in enumerate(cells[: len(widths)]):
                widths[col] = max(widths[col], _display_width(cell))
        # 压缩极端差异：短列不要被挤成一条缝，长列也不独占整行
        weights = [0.34 + 0.66 * (w / max(widths)) if max(widths) else 1.0 for w in widths]
        tables.append(weights)
    return tables


TABLE_TOTAL_DXA = 8505       # 15cm 版心的宽度（1cm ≈ 567 dxa）
TABLE_MIN_DXA = 900


def apply_table_layout(file_id: str, weight_sets: list[list[float]]) -> None:
    """把每张表设为满页宽、按内容分配列宽、禁止行跨页断开。"""
    listing = call("doc_list_tables", {"file_id": file_id})
    tables = listing.get("tables") or listing.get("items") or []
    if not isinstance(tables, list):
        return
    done = 0
    for table, weights in zip(tables, weight_sets):
        table_id = table.get("table_id") or table.get("id")
        if not table_id:
            continue
        # manual 模式要求先读取表格当前尺寸，否则服务端会拒绝
        info = call("doc_get_table_info", {"file_id": file_id, "table_id": table_id})
        block = info.get("block") or {}
        col_count = (block.get("table") or {}).get("col_count") or len(weights)
        if len(weights) != col_count:
            weights = (weights + [1.0] * col_count)[:col_count]
        total = sum(weights) or 1.0
        widths = [max(TABLE_MIN_DXA, round(TABLE_TOTAL_DXA * w / total)) for w in weights]
        diff = TABLE_TOTAL_DXA - sum(widths)
        widths[-1] = max(TABLE_MIN_DXA, widths[-1] + diff)
        try:
            call(
                "doc_set_table_properties",
                {
                    "file_id": file_id,
                    "table_id": table_id,
                    "mode": "manual",
                    "col_widths_dxa": widths,
                    "cant_split": False,   # 该字段为 false 时才是"禁止行跨页断开"
                    "cell_v_align": "center",
                },
            )
            done += 1
        except RuntimeError as exc:
            print(f"  [表格 {table_id}] 设置失败：{str(exc)[:120]}")
    print(f"已调整 {done}/{min(len(tables), len(weight_sets))} 张表格的列宽与分页属性")


def normalize_markdown(text: str) -> str:
    """把章节标题上提一级：``## 一、实验目的`` → ``# 一、实验目的``。

    源码里用 ``##`` 是为了可读性，但报告正文里"一、二、三"应当是文档的一级标题。
    """
    text = re.sub(r"^###\s+", "## ", text, flags=re.MULTILINE)
    text = re.sub(r"^##\s+", "# ", text, flags=re.MULTILINE)
    return text


# ------------------------------------------------------------------ 封面
def build_cover(file_id: str) -> int:
    cursor = 0
    for _ in range(5):
        cursor = insert_para(file_id, cursor, "", size=14, jc="center")

    cursor = insert_para(
        file_id, cursor, "Python 程序设计课程报告",
        size=26, bold=True, jc="center", font="SimHei",
    )
    cursor = insert_para(
        file_id, cursor, "—— 地下城探险 Roguelike 游戏的设计与实现",
        size=14, jc="center", font="SimHei", color="444444",
    )

    for _ in range(6):
        cursor = insert_para(file_id, cursor, "", size=14, jc="center")

    info = [
        ("课程名称", "Python 程序设计"),
        ("实验名称", "地下城探险 Roguelike 游戏"),
        ("学生姓名", "____________"),
        ("学　　号", "____________"),
        ("专　　业", "____________"),
        ("指导教师", "____________"),
    ]
    for label, value in info:
        cursor = insert_para(
            file_id, cursor, f"{label}：{value}", size=13, jc="center", font="SimSun"
        )

    cursor = insert_para(file_id, cursor, "", size=14, jc="center")
    cursor = insert_para(file_id, cursor, "", size=14, jc="center")
    cursor = insert_para(
        file_id, cursor, "2026 年 10 月", size=12, jc="center", color="666666"
    )
    call("doc_insert_page_break", {"file_id": file_id, "idx": cursor})
    return last_pos(file_id)


# ------------------------------------------------------------------ 主流程
def main() -> int:
    if not SOURCE.exists():
        print(f"找不到报告内容：{SOURCE}")
        return 1

    created = call("create_doc", {})
    file_id = extract_file_id(created)
    if not file_id:
        print(f"创建文档失败：{created}")
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    call("save_file", {"file_id": file_id, "file_path": str(TARGET)})
    print(f"已创建文档：{TARGET.name}")

    # 全局基底格式：正文宋体小四、1.5 倍行距、两端对齐
    call(
        "doc_set_document_style",
        {
            "file_id": file_id,
            "default_text_style": {"font_family": "SimSun", "font_size": 12},
            "default_paragraph_style": {
                "line_spacing": 1.5, "line_spacing_rule": 1, "jc": "both",
            },
            "page_style": {
                "top_margin": 72, "bottom_margin": 72,
                "left_margin": 85, "right_margin": 85,
            },
        },
    )

    # 标题样式：黑体、黑色、字号分级。
    # 注意：这里只改 text_style，不传 paragraph_style——实测在本版本 editor_sdk 中
    # 给命名样式写段落属性会生成 Word 判定为"已损坏"的 styles.xml。
    for level, size in ((1, 16), (2, 14), (3, 12)):
        call(
            "doc_update_named_style",
            {
                "file_id": file_id,
                "named_style_type": f"HEADING_{level}",
                "text_style": {"font_family": "SimHei", "font_size": size, "color": "000000"},
            },
        )

    cursor = build_cover(file_id)
    print("封面完成")

    blocks = parse_blocks()
    md_count = sum(1 for kind, _ in blocks if kind == "md")
    img_count = sum(1 for kind, _ in blocks if kind == "img")
    print(f"共 {len(blocks)} 个块（文字 {md_count}、图片 {img_count}）")

    table_weights: list[list[float]] = []
    for index, (kind, payload) in enumerate(blocks, start=1):
        if kind == "md":
            markdown = normalize_markdown(payload)  # type: ignore[arg-type]
            table_weights.extend(table_column_weights(markdown))
            try:
                cursor = insert_md(file_id, cursor, markdown)
            except RuntimeError as exc:
                print(f"  [块 {index}] 插入失败：{markdown[:60]!r}")
                raise exc
        else:
            rel_path, width = payload  # type: ignore[misc]
            image_path = (ROOT / rel_path).resolve()
            if not image_path.exists():
                print(f"  [跳过] 缺少图片 {rel_path}")
                continue
            call(
                "doc_insert_image",
                {
                    "file_id": file_id,
                    "idx": cursor,
                    "image_path": str(image_path),
                    "w": width,
                },
            )
            cursor = last_pos(file_id)

            # 图注用 Markdown 插入而不是段落接口：图片之后的"文档末尾"
            # 不接受 doc_insert_paragraph_with_text（会报 past the end of story），
            # 但接受 doc_insert_markdown，所以图注统一走斜体段落。
            caption = CAPTIONS.get(rel_path, "")
            if caption:
                cursor = insert_md(file_id, cursor, f"*{caption}*")
        if index % 8 == 0:
            print(f"  进度 {index}/{len(blocks)}")

    if table_weights:
        apply_table_layout(file_id, table_weights)

    call("save_file", {"file_id": file_id, "file_path": str(TARGET)})
    print(f"已保存：{TARGET}")
    print(f"file_id={file_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
