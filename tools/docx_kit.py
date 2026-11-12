"""课程报告的排版工具层。

为什么单独抽一个模块
--------------------
报告里有 8 个章节、40 余个小节、15 张表格、19 张插图、5 段伪代码。
如果把这些排版细节和正文内容混在一个文件里，改一句话都要在几百行里翻。
这里只负责"怎么排"，`build_report.py` 只负责"写什么"。

样式基线直接取自 `Python 大作业评分标准.docx`：
A4（21 × 29.7 cm）、上下边距 2.54 cm、左右边距 3.175 cm、正文宋体小四。
标题字号在模板的 20/16 pt 基础上做了收敛——那两级是 Word 默认样式，
直接用于 30 页正文会明显头重脚轻，这里统一成 16/14/12 pt 的学术报告惯例。
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# 中文字体：正文宋体，标题黑体，伪代码等宽
FONT_SONG = "宋体"
FONT_HEI = "黑体"
FONT_MONO = "Consolas"
FONT_LATIN = "Times New Roman"

BODY_PT = 12          # 小四
CAPTION_PT = 10.5     # 五号
TABLE_PT = 10.5
MONO_PT = 9.0

TEXT_WIDTH_CM = 14.65  # 21 − 3.175 × 2，插图与表格的可用宽度


# ---------------------------------------------------------------- 底层工具
def _set_run_fonts(run, east: str, latin: str, size: float | None = None,
                   bold: bool | None = None, color: RGBColor | None = None) -> None:
    """同时设置西文与东亚字体。只设 run.font.name 对中文无效。"""
    run.font.name = latin
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:eastAsia"), east)
    rfonts.set(qn("w:cs"), latin)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def _style_font(style, east: str, latin: str, size: float,
                bold: bool = False, color: RGBColor | None = None) -> None:
    style.font.name = latin
    style.font.size = Pt(size)
    style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for key in ("w:ascii", "w:hAnsi", "w:cs"):
        rfonts.set(qn(key), latin)
    rfonts.set(qn("w:eastAsia"), east)
    # 去掉主题字体绑定，否则 Word 会优先用主题字体覆盖显式设置
    for key in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rfonts.get(qn(key)) is not None:
            del rfonts.attrib[qn(key)]


def _first_line_indent_chars(paragraph, chars: int = 2) -> None:
    """按"字符"设置首行缩进。python-docx 只支持长度，中文字符数要用 XML。"""
    ppr = paragraph._p.get_or_add_pPr()
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        ppr.append(ind)
    ind.set(qn("w:firstLineChars"), str(chars * 100))
    ind.set(qn("w:firstLine"), str(int(BODY_PT * chars * 20)))  # 1pt = 20 twips


def _shade(element, fill: str) -> None:
    """给段落或单元格加底色。"""
    pr = element.get_or_add_tcPr() if element.tag.endswith("tc") else element.get_or_add_pPr()
    shd = pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        pr.append(shd)
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


def _para_border(paragraph, color: str = "BFC7D5", size: int = 6) -> None:
    """给段落加一圈细边框（伪代码块用）。"""
    ppr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(size))
        el.set(qn("w:space"), "4")
        el.set(qn("w:color"), color)
        borders.append(el)
    ppr.append(borders)


# ---------------------------------------------------------------- 文档骨架
def new_document(template: Path) -> Document:
    """以评分标准文档为底稿新建报告，继承它的页面设置。

    直接 `Document()` 会得到 Letter 纸与 1 英寸边距，与模板不一致；
    以模板为底再清空正文，页面尺寸、页边距、页眉页脚距离都原样保留。
    """
    doc = Document(str(template))

    body = doc.element.body
    for child in list(body):
        # 末尾的 sectPr 是页面设置，必须留着，否则整篇文档变成默认版式
        if child.tag == qn("w:sectPr"):
            continue
        body.remove(child)

    _normalize_styles(doc)
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.175)
    section.right_margin = Cm(3.175)
    section.header_distance = Cm(1.5)
    section.footer_distance = Cm(1.75)
    return doc


def _normalize_styles(doc: Document) -> None:
    """把模板里的样式改成中文课程报告的排版基线。"""
    styles = doc.styles

    normal = styles["Normal"]
    _style_font(normal, FONT_SONG, FONT_LATIN, BODY_PT)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)

    # 正文：1.5 倍行距 + 首行缩进 2 字符 + 两端对齐
    body = styles.add_style("报告正文", 1)  # 1 = WD_STYLE_TYPE.PARAGRAPH
    body.base_style = normal
    _style_font(body, FONT_SONG, FONT_LATIN, BODY_PT)
    pf = body.paragraph_format
    pf.line_spacing = 1.5
    pf.space_before = Pt(0)
    pf.space_after = Pt(3)
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    # 三级标题：黑体、黑色、与下段同页
    for name, size, before, after, align in (
        ("Heading 1", 16, 18, 10, WD_ALIGN_PARAGRAPH.CENTER),
        ("Heading 2", 14, 12, 6, WD_ALIGN_PARAGRAPH.LEFT),
        ("Heading 3", 12, 8, 4, WD_ALIGN_PARAGRAPH.LEFT),
    ):
        style = styles[name]
        _style_font(style, FONT_HEI, FONT_LATIN, size, bold=True, color=RGBColor(0, 0, 0))
        pf = style.paragraph_format
        pf.space_before = Pt(before)
        pf.space_after = Pt(after)
        pf.line_spacing = 1.25
        pf.alignment = align
        pf.keep_with_next = True
        pf.first_line_indent = Pt(0)
        if name == "Heading 1":
            # 每章从新页开始：学术报告的通行做法，也让章末的留白显得是有意为之
            pf.page_break_before = True

    caption = styles.add_style("图表题注", 1)
    caption.base_style = normal
    _style_font(caption, FONT_SONG, FONT_LATIN, CAPTION_PT, color=RGBColor(0x33, 0x33, 0x33))
    caption.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption.paragraph_format.space_before = Pt(3)
    caption.paragraph_format.space_after = Pt(9)
    caption.paragraph_format.line_spacing = 1.2

    pseudo = styles.add_style("伪代码", 1)
    pseudo.base_style = normal
    _style_font(pseudo, FONT_SONG, FONT_MONO, MONO_PT)
    pf = pseudo.paragraph_format
    pf.line_spacing = 1.06
    pf.space_before = Pt(4)
    pf.space_after = Pt(6)
    pf.left_indent = Cm(0.4)
    pf.right_indent = Cm(0.4)


# ---------------------------------------------------------------- 行内富文本
# 支持两种行内标记：**加粗** 与 `代码`。
# 早先只处理加粗，反引号被原样印进文档（"`dungeon/`"），非常像没写完的稿子。
_TOKEN = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\*[^*\n]+\*)")
CODE_COLOR = RGBColor(0x1F, 0x3B, 0x63)   # 深藏青：与正文区分，又不像超链接


def add_rich(paragraph, text: str, size: float = BODY_PT,
             east: str = FONT_SONG, latin: str = FONT_LATIN,
             bold: bool = False, color: RGBColor | None = None) -> None:
    """把带 `**加粗**` 与 `` `代码` `` 标记的文本写进段落。

    代码片段用等宽字体、字号略小、深藏青色，既保留了“这是标识符”的语义，
    又不会像行内代码块那样把行距撑开。
    """
    for token in _TOKEN.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            run = paragraph.add_run(token[2:-2])
            _set_run_fonts(run, east, latin, size, bold=True, color=color)
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            run = paragraph.add_run(token[1:-1])
            _set_run_fonts(run, FONT_MONO, FONT_MONO, size - 0.5,
                           bold=bold, color=CODE_COLOR)
        elif token.startswith("*") and token.endswith("*") and len(token) > 2:
            # 单星号 = 斜体，用于引文。必须放在 ** 之后判断，否则会把加粗吃掉
            run = paragraph.add_run(token[1:-1])
            _set_run_fonts(run, east, latin, size, bold=bold, color=color)
            run.font.italic = True
        else:
            run = paragraph.add_run(token)
            _set_run_fonts(run, east, latin, size, bold=bold, color=color)


# ---------------------------------------------------------------- 内容块
def h1(doc: Document, text: str, new_page: bool = True) -> None:
    """一级标题。``new_page=False`` 用于紧跟目录分节之后的第一章。"""
    para = doc.add_paragraph(text, style="Heading 1")
    if not new_page:
        para.paragraph_format.page_break_before = False


def h2(doc: Document, text: str) -> None:
    doc.add_paragraph(text, style="Heading 2")


def h3(doc: Document, text: str) -> None:
    doc.add_paragraph(text, style="Heading 3")


def p(doc: Document, text: str, indent: bool = True, bold_lead: bool = False) -> None:
    """正文段落。支持 `**加粗**` 与 `` `代码` `` 行内标记。"""
    para = doc.add_paragraph(style="报告正文")
    if indent:
        _first_line_indent_chars(para, 2)
    add_rich(para, text)
    if bold_lead:
        para.paragraph_format.space_before = Pt(3)


def bullet(doc: Document, text: str) -> None:
    """项目符号段落。手动加“·”而不是用列表样式，避免与标题缩进打架。"""
    para = doc.add_paragraph(style="报告正文")
    para.paragraph_format.left_indent = Cm(0.85)
    para.paragraph_format.first_line_indent = Cm(-0.35)
    add_rich(para, "· " + text)


def note(doc: Document, text: str) -> None:
    """小字注释（灰色），用于"待填写"提示。"""
    para = doc.add_paragraph()
    para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_before = Pt(6)
    run = para.add_run(text)
    _set_run_fonts(run, FONT_SONG, FONT_LATIN, 9, color=RGBColor(0x88, 0x88, 0x88))


def page_break(doc: Document) -> None:
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def figure(doc: Document, path: Path, caption: str, width_cm: float) -> None:
    """居中插图 + 下方题注。图注与图必须同页，故设置 keep_with_next。"""
    para = doc.add_paragraph()
    para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_before = Pt(6)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.keep_with_next = True
    para.add_run().add_picture(str(path), width=Cm(width_cm))
    cap = doc.add_paragraph(caption, style="图表题注")
    cap.paragraph_format.keep_with_next = False


def pseudo(doc: Document, lines: list[str]) -> None:
    """伪代码块：等宽字体 + 浅灰底 + 细边框，整块放在一个段落里。"""
    para = doc.add_paragraph(style="伪代码")
    # 伪代码块必须整块留在同一页：跨页会从中间断开，读者要翻页才能看完一段算法
    para.paragraph_format.keep_together = True
    _shade(para._p, "F4F6F9")
    _para_border(para)
    for index, line in enumerate(lines):
        run = para.add_run(line)
        _set_run_fonts(run, FONT_SONG, FONT_MONO, MONO_PT)
        if index != len(lines) - 1:
            run.add_break()


def _table_borders(table) -> None:
    """三线表的变体：外框与表头下边稍粗，内部细线。"""
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge, size in (("top", 8), ("left", 4), ("bottom", 8), ("right", 4),
                       ("insideH", 4), ("insideV", 4)):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(size))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "A6A6A6")
        borders.append(el)
    tbl_pr.append(borders)


def table(doc: Document, caption: str, header: list[str], rows: list[list[str]],
          widths: list[float] | None = None, align: str = "center") -> None:
    """带题注的表格；题注在**上方**（工科报告惯例）。"""
    cap = doc.add_paragraph(caption, style="图表题注")
    cap.paragraph_format.space_before = Pt(8)
    cap.paragraph_format.space_after = Pt(3)
    cap.paragraph_format.keep_with_next = True

    tbl = doc.add_table(rows=1, cols=len(header))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    _table_borders(tbl)

    if widths:
        grid = tbl._tbl.tblGrid
        for index, width in enumerate(widths):
            if index < len(grid.gridCol_lst):
                grid.gridCol_lst[index].set(qn("w:w"), str(int(width * 567)))

    header_row = tbl.rows[0]
    # 表头跨页重复
    tr_pr = header_row._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    tr_pr.append(repeat)

    for cell, text in zip(header_row.cells, header):
        _fill_cell(cell, text, bold=True, shade="EDF0F5", align="center")
    for row_data in rows:
        row = tbl.add_row()
        for cell, text in zip(row.cells, row_data):
            _fill_cell(cell, text, bold=False, shade=None, align=align)

    if widths:
        for row in tbl.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Cm(width)

    # 表后留一点空隙
    tail = doc.add_paragraph()
    tail.paragraph_format.space_after = Pt(4)
    tail.paragraph_format.line_spacing = 1.0


def _fill_cell(cell, text: str, bold: bool, shade: str | None, align: str = "center") -> None:
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    para = cell.paragraphs[0]
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(2)
    para.paragraph_format.line_spacing = 1.1
    para.paragraph_format.first_line_indent = Pt(0)
    para.alignment = (
        WD_ALIGN_PARAGRAPH.CENTER if align == "center" else WD_ALIGN_PARAGRAPH.LEFT
    )
    add_rich(para, str(text), size=TABLE_PT, bold=bold)
    if shade:
        _shade(cell._tc, shade)


# ---------------------------------------------------------------- 域与页脚
def add_toc(doc: Document, levels: str = "1-2") -> None:
    """插入 Word 目录域。

    python-docx 无法计算页码，所以这里插入真正的 TOC 域，由 Word 在打开时
    更新（`build_report.py` 会调用 Word COM 自动更新一次，用户拿到的成稿
    已经带页码，不需要手动按 F9）。
    """
    para = doc.add_paragraph()
    para.paragraph_format.line_spacing = 1.5
    run = para.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f' TOC \\o "{levels}" \\h \\z \\u '
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "（目录将在生成时自动更新）"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(separate)
    run._r.append(placeholder)
    run._r.append(end)


def add_page_field(section, start_at: int | None = None) -> None:
    """页脚居中页码；``start_at`` 用于让正文从 1 重新编号。"""
    section.footer.is_linked_to_previous = False
    para = section.footer.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for child in list(para._p):
        if child.tag != qn("w:pPr"):
            para._p.remove(child)
    run = para.add_run()
    _set_run_fonts(run, FONT_SONG, FONT_LATIN, 9, color=RGBColor(0x44, 0x44, 0x44))
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for el in (begin, instr, end):
        run._r.append(el)

    if start_at is not None:
        sect_pr = section._sectPr
        pg = sect_pr.find(qn("w:pgNumType"))
        if pg is None:
            pg = OxmlElement("w:pgNumType")
            sect_pr.append(pg)
        pg.set(qn("w:start"), str(start_at))


def clear_footer(section) -> None:
    section.footer.is_linked_to_previous = False
    for para in section.footer.paragraphs:
        for child in list(para._p):
            if child.tag != qn("w:pPr"):
                para._p.remove(child)


def new_section(doc: Document):
    """另起一节（新页）。分节的目的只有一个：让封面/目录不参与页码编号。"""
    return doc.add_section(WD_SECTION.NEW_PAGE)


def cell_bottom_border(cell, color: str = "9AA3B0", size: int = 6) -> None:
    """只给单元格加下边框，用来做封面的“填空横线”。"""
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "0")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)


def plain_row_table(doc: Document, rows: list[tuple[str, str]],
                    widths: tuple[float, float], size: float = 14,
                    label_pad: float = 0.6):
    """无边框的两列表格，用于封面信息栏。

    用表格而不是居中段落：每行标签长度不同（“课程名称”与“学　　号”），
    逐段居中对齐会让右侧填空线的起点参差不齐；表格能让标签右对齐、
    横线左端严格对齐。
    """
    tbl = doc.add_table(rows=0, cols=2)
    tbl.autofit = False
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for label, value in rows:
        row = tbl.add_row()
        left, right = row.cells
        left.width = Cm(widths[0])
        right.width = Cm(widths[1])
        left.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        right.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        lpara = left.paragraphs[0]
        lpara.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        lpara.paragraph_format.space_before = Pt(6)
        lpara.paragraph_format.space_after = Pt(6)
        _set_run_fonts(lpara.add_run(label + "："), FONT_SONG, FONT_LATIN, size)

        rpara = right.paragraphs[0]
        rpara.alignment = WD_ALIGN_PARAGRAPH.LEFT
        rpara.paragraph_format.space_before = Pt(6)
        rpara.paragraph_format.space_after = Pt(6)
        rpara.paragraph_format.left_indent = Cm(0.15)
        _set_run_fonts(rpara.add_run(value), FONT_SONG, FONT_LATIN, size)
        if not value.strip() or set(value) <= {"＿", " ", ""}:
            cell_bottom_border(right)
    return tbl
