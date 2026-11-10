"""把 docx 导出成 PDF 再把每页渲染成 PNG，用于人工校版。

只在开发阶段校验报告排版用，不参与程序本体。
依赖本机安装的 Microsoft Word（通过 COM 导出 PDF）与 pymupdf（渲染图片）。

用法::

    python tools/preview_docx.py docs/Python程序设计课程报告.docx
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent


PS_TEMPLATE = """
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {{
    $doc = $word.Documents.Open("{docx}", $false, $true)
    $doc.SaveAs([ref] "{pdf}", [ref] 17)
    $doc.Close([ref] $false)
}} finally {{
    $word.Quit()
}}
Write-Output "PDF_OK"
"""


def docx_to_pdf(docx: Path, pdf: Path) -> bool:
    script = PS_TEMPLATE.format(docx=docx.as_posix(), pdf=pdf.as_posix())
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    return "PDF_OK" in (result.stdout or "")


def render_pdf(pdf: Path, out_dir: Path, zoom: float = 1.6) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open(pdf)
    matrix = pymupdf.Matrix(zoom, zoom)
    for index, page in enumerate(document, start=1):
        pixmap = page.get_pixmap(matrix=matrix)
        target = out_dir / f"page{index:02d}.png"
        pixmap.save(target)
    pages = document.page_count
    document.close()
    print(f"共 {pages} 页，已渲染到 {out_dir}")
    return pages


def main(argv: list[str]) -> int:
    docx = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "Python程序设计课程报告.docx"
    if not docx.exists():
        print(f"找不到文档：{docx}")
        return 1
    pdf = docx.with_suffix(".preview.pdf")
    if not docx_to_pdf(docx, pdf):
        print("Word 导出 PDF 失败")
        return 1
    render_pdf(pdf, ROOT / "docs" / "report_preview")
    pdf.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
