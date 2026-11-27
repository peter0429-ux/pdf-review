"""把各种文档抽成纯文本。

支持的格式与各自的「最小单元」：

  | 扩展名        | 库          | 单元     |
  |---------------|-------------|----------|
  | .pdf          | pypdf       | 页       |
  | .docx         | python-docx | 节（按标题分） |
  | .pptx         | python-pptx | 张幻灯片 |
  | .xlsx         | openpyxl    | 个工作表 |
  | .txt / .md    | 标准库      | 段       |
  | .html / .htm  | bs4 + lxml  | 节（按 h1–h3 分） |

为什么要有「单元」这个概念：卡片需要 `sourcePage` 指回原文位置。PDF 有页号，
别的格式没有，硬编一个假页号（比如「每 1800 字算一页」）会让卡片上写着
「第 7 页」而用户翻到第 7 页什么也找不到。所以按格式本身的结构切，
界面上写「第 3 张幻灯片」而不是「第 3 页」。

**不做 OCR**：扫描版 PDF（整页是图片）抽不出文字，这里会明确报错让用户知道，
而不是返回空字符串让 AI 去编。
"""

from __future__ import annotations

import html
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import limits

#: 支持的扩展名 → 界面上的格式名
SUPPORTED_SUFFIXES: dict[str, str] = {
    ".pdf": "PDF",
    ".docx": "Word 文档",
    ".pptx": "PowerPoint 演示文稿",
    ".xlsx": "Excel 工作簿",
    ".txt": "纯文本",
    ".md": "Markdown",
    ".html": "网页",
    ".htm": "网页",
}


class ExtractError(Exception):
    """抽取失败。消息直接给用户看，所以要写人话。"""


@dataclass
class Segment:
    """原文的一段。index 从 1 起，与卡片里的 sourcePage 对应。"""

    index: int
    label: str
    text: str


@dataclass
class Extraction:
    """一份文档抽出来的全部文本。"""

    file_name: str
    kind: str
    #: 「页」「节」「张幻灯片」…… 用于拼 label 与提示语
    unit_label: str
    segments: list[Segment]
    full_text: str
    has_text_layer: bool = True

    @property
    def page_count(self) -> int:
        """单元数。字段名沿用 iOS 的 pageCount（格式标准里就叫这个）。"""
        return len(self.segments)

    @property
    def text_length(self) -> int:
        return len(self.full_text)

    @property
    def char_count(self) -> int:
        return len(self.full_text)

    @property
    def stem_title(self) -> str:
        """文件名去掉扩展名，当牌组标题的默认值。

        放在这里而不是界面里：核心层已经知道 `file_name`，界面再拼一次
        就会出现「iOS 版叫这个、PC 版叫那个」的分叉。
        """
        name = Path(self.file_name)
        stem = name.stem.strip() or name.name
        return stem[: limits.TITLE_MAX]


def extract(path: Path | str) -> Extraction:
    """按扩展名分派。不支持的格式抛 ExtractError。"""
    target = Path(path)
    if not target.exists():
        raise ExtractError(f"文件不存在：{target}")
    if not target.is_file():
        raise ExtractError(f"这不是一个文件：{target}")

    size = target.stat().st_size
    if size == 0:
        raise ExtractError(f"文件是空的（0 字节）：{target.name}")
    if size > limits.MAX_FILE_BYTES:
        raise ExtractError(
            f"文件 {size / 1024 / 1024:.1f} MB，超过 {limits.MAX_FILE_BYTES // 1024 // 1024} MB 上限。"
            "太大的文档切成几份再导入，或者先用别的工具压缩一下图片。"
        )

    suffix = target.suffix.lower()
    handler = _HANDLERS.get(suffix)
    if handler is None:
        supported = "、".join(sorted(SUPPORTED_SUFFIXES))
        raise ExtractError(f"还不支持 {suffix or '（无扩展名）'} 格式。现在能处理：{supported}")

    try:
        extraction = handler(target)
    except ExtractError:
        raise
    except Exception as exc:  # noqa: BLE001 - 第三方库的异常五花八门，统一包装
        raise ExtractError(f"读取 {target.name} 失败：{exc}") from exc

    extraction.file_name = target.name
    # 「有没有文字层」只对 PDF 有意义：扫描件是 PDF 独有的问题，
    # 其他格式要么有文字要么抽不出来（上面已经抛错了）。
    # 若对所有格式都套 200 字门槛，一份只有三行字的 .txt 会被判成
    # 「没有文字层」而拒绝分析 —— 那是误伤。
    extraction.has_text_layer = (
        _looks_like_text(extraction) if extraction.kind == "pdf" else True
    )
    return extraction


# ---------------------------------------------------------------------------
# 各格式的抽取
# ---------------------------------------------------------------------------


def _extract_pdf(path: Path) -> Extraction:
    from pypdf import PdfReader

    reader = PdfReader(str(path))

    # 加密 PDF：先试空密码（很多「只限制编辑」的 PDF 是这种）
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise ExtractError(
                "这个 PDF 有密码保护，解不开。请先用 PDF 阅读器另存一份无密码的版本。"
            ) from exc

    segments: list[Segment] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - 单页抽失败不该毁掉整个文档
            text = ""
        text = normalize(text)
        segments.append(Segment(index=index, label=f"第 {index} 页", text=text))

    if not segments:
        raise ExtractError("这个 PDF 一页都没有，文件可能已经损坏。")

    full_text = normalize("\n\n".join(s.text for s in segments))
    if not full_text.strip():
        raise ExtractError(
            "这个 PDF 里没有可提取的文字。它多半是扫描件（整页都是图片），"
            "当前版本不做图片识别。可以用带 OCR 的工具先转成文字版 PDF，或者直接导出成 .txt。"
        )

    return Extraction(
        file_name=path.name,
        kind="pdf",
        unit_label="页",
        segments=segments,
        full_text=full_text,
    )


def _extract_docx(path: Path) -> Extraction:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))

    # 按标题切节。python-docx 的 body 是按顺序的 block 列表，
    # 要同时处理段落与表格（表格里的内容往往是关键数据，漏了就白搭）。
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_lines:
            sections.append((current_title, current_lines))
        current_title = ""
        current_lines = []

    for block in _iter_docx_blocks(document):
        if isinstance(block, Paragraph):
            style_name = (block.style.name or "") if block.style else ""
            is_heading = style_name.startswith("Heading") or style_name.startswith("标题")
            text = block.text.strip()
            if not text:
                continue
            if is_heading:
                flush()
                current_title = text
            else:
                current_lines.append(text)
        elif isinstance(block, Table):
            rows: list[str] = []
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                # 合并单元格会重复同一段文字，去掉相邻重复
                deduped = [c for i, c in enumerate(cells) if i == 0 or cells[i - 1] != c]
                line = " | ".join(c for c in deduped if c)
                if line:
                    rows.append(line)
            if rows:
                current_lines.extend(rows)

    flush()

    if not sections:
        raise ExtractError("这个 Word 文档里没有文字内容。")

    segments: list[Segment] = []
    for index, (title, lines) in enumerate(sections, start=1):
        body = "\n".join(lines)
        text = f"{title}\n{body}" if title else body
        segments.append(
            Segment(index=index, label=f"第 {index} 节", text=normalize(text))
        )

    return Extraction(
        file_name=path.name,
        kind="docx",
        unit_label="节",
        segments=segments,
        full_text=normalize("\n\n".join(s.text for s in segments)),
    )


def _iter_docx_blocks(document):
    """按文档顺序产出 Paragraph 与 Table。

    python-docx 没有直接给这个顺序，要自己走 XML 的 body 子节点。
    `document.paragraphs` 与 `document.tables` 是两个独立列表，
    合并它们会丢掉原始顺序 —— 那样标题与它下面的表格就对不上了。
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = document.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _extract_pptx(path: Path) -> Extraction:
    from pptx import Presentation

    presentation = Presentation(str(path))
    segments: list[Segment] = []

    for index, slide in enumerate(presentation.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            # 有 text_frame 的才是文字；图片、图表没有文字可抽
            if not getattr(shape, "has_text_frame", False):
                continue
            frame = shape.text_frame
            for paragraph in frame.paragraphs:
                text = "".join(run.text for run in paragraph.runs).strip()
                if text:
                    lines.append(text)
            # 表格
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    deduped = [
                        c for i, c in enumerate(cells) if i == 0 or cells[i - 1] != c
                    ]
                    line = " | ".join(c for c in deduped if c)
                    if line:
                        lines.append(line)

        if lines:
            segments.append(
                Segment(
                    index=index,
                    label=f"第 {index} 张幻灯片",
                    text=normalize("\n".join(lines)),
                )
            )

    if not segments:
        raise ExtractError("这份演示文稿里没有文字，可能全是图片。")

    # 空幻灯片被跳过后 index 不连续，重排一次让 label 与序号对上
    for new_index, segment in enumerate(segments, start=1):
        segment.index = new_index
        segment.label = f"第 {new_index} 张幻灯片"

    return Extraction(
        file_name=path.name,
        kind="pptx",
        unit_label="张幻灯片",
        segments=segments,
        full_text=normalize("\n\n".join(s.text for s in segments)),
    )


def _extract_xlsx(path: Path) -> Extraction:
    from openpyxl import load_workbook

    # data_only=True：读公式算出来的值，而不是 "=SUM(A1:A9)"。
    # 注意：如果这个文件从没被 Excel 保存过计算结果，值是 None，
    # 那种情况下公式文本才是唯一有用的东西 —— 所以下面兜了一层。
    workbook = load_workbook(str(path), data_only=True, read_only=True)
    segments: list[Segment] = []

    try:
        for index, sheet in enumerate(workbook.worksheets, start=1):
            lines: list[str] = []
            header: list[str] = []

            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                cells = ["" if value is None else str(value).strip() for value in row]
                if not any(cells):
                    continue
                if row_index == 0:
                    header = cells
                    continue
                if header and any(header):
                    pairs = [
                        f"{header[i]}: {cells[i]}"
                        for i in range(min(len(header), len(cells)))
                        if header[i] and cells[i]
                    ]
                    if pairs:
                        lines.append("；".join(pairs))
                        continue
                # 没有表头就整行拼起来
                line = " | ".join(c for c in cells if c)
                if line:
                    lines.append(line)

            if lines:
                segments.append(
                    Segment(
                        index=len(segments) + 1,
                        label=f"第 {len(segments) + 1} 个工作表：{sheet.title}",
                        text=normalize("\n".join(lines)),
                    )
                )
    finally:
        workbook.close()

    if not segments:
        raise ExtractError("这个 Excel 工作簿里没有数据（所有单元格都是空的）。")

    return Extraction(
        file_name=path.name,
        kind="xlsx",
        unit_label="个工作表",
        segments=segments,
        full_text=normalize("\n\n".join(s.text for s in segments)),
    )


def _extract_text(path: Path) -> Extraction:
    text = _read_text_file(path)
    if not text.strip():
        raise ExtractError("这个文件里没有文字。")

    suffix = path.suffix.lower()
    if suffix == ".md":
        sections = _split_markdown(text)
        unit_label = "节"
    else:
        sections = _split_by_length(text, target=3000)
        unit_label = "段"

    segments = [
        Segment(index=i, label=f"第 {i} {unit_label}", text=normalize(body))
        for i, body in enumerate(sections, start=1)
        if body.strip()
    ]
    if not segments:
        raise ExtractError("这个文件里没有文字。")

    return Extraction(
        file_name=path.name,
        kind="txt" if suffix == ".txt" else "md",
        unit_label=unit_label,
        segments=segments,
        full_text=normalize("\n\n".join(s.text for s in segments)),
    )


def _extract_html(path: Path) -> Extraction:
    from bs4 import BeautifulSoup

    raw = _read_text_file(path)
    soup = BeautifulSoup(raw, "lxml")

    # 去掉不产生正文的标签。留着 script/style 会让 AI 读到一堆 JS，
    # nav/footer 则是全站重复的导航文字。
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()

    root = soup.body or soup
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_lines:
            sections.append((current_title, current_lines))
        current_title = ""
        current_lines = []

    for element in root.find_all(["h1", "h2", "h3", "p", "li", "td", "th", "pre", "blockquote"]):
        # 嵌套的 p/li 会被 find_all 重复命中，跳过已在父元素里处理过的
        if element.find_parent(["p", "li", "pre", "blockquote"]) is not None:
            continue
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if element.name in ("h1", "h2", "h3"):
            flush()
            current_title = text
        else:
            current_lines.append(text)

    flush()

    if not sections:
        # 有些页面完全由 div/span 组成，没有 p/li。退化成整页文本。
        fallback = soup.get_text("\n", strip=True)
        if not fallback.strip():
            raise ExtractError("这个网页里没有可读的正文。")
        sections = [("", [fallback])]

    segments: list[Segment] = []
    for index, (title, lines) in enumerate(sections, start=1):
        body = "\n".join(lines)
        text = f"{title}\n{body}" if title else body
        segments.append(
            Segment(index=index, label=f"第 {index} 节", text=normalize(text))
        )

    return Extraction(
        file_name=path.name,
        kind="html",
        unit_label="节",
        segments=segments,
        full_text=normalize("\n\n".join(s.text for s in segments)),
    )


_HANDLERS: dict[str, Callable[[Path], Extraction]] = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".pptx": _extract_pptx,
    ".xlsx": _extract_xlsx,
    ".txt": _extract_text,
    ".md": _extract_text,
    ".html": _extract_html,
    ".htm": _extract_html,
}


# ---------------------------------------------------------------------------
# 文本清洗与切分
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """统一换行、去零宽字符、压缩空行。与 iOS 的 `PDFTextExtractor.normalize` 一致。

    零宽字符（U+200B）与 BOM（U+FEFF）常藏在从网页复制的文本里，
    它们不可见却会影响字符串比较 —— 去重时会认为两句话不一样。
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\u00a0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 行尾空白
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


def _read_text_file(path: Path) -> str:
    """读文本文件，依次尝试几种编码。

    顺序是有讲究的：utf-8-sig 放最前，因为带 BOM 的 UTF-8 用 utf-8 读会
    在开头留一个 U+FEFF；gb18030 放最后，它能解码几乎任何字节序列，
    所以必须在所有更精确的编码之后尝试，否则会把 UTF-8 中文读成乱码。
    """
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    # 全失败就用替换字符，至少让用户看到部分内容
    return raw.decode("utf-8", errors="replace")


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")


def _split_markdown(text: str) -> list[str]:
    """按 Markdown 的一到三级标题切节。没有标题就当一整块。"""
    lines = text.split("\n")
    sections: list[str] = []
    current: list[str] = []

    for line in lines:
        if _HEADING_RE.match(line) and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append("\n".join(current))

    return sections or [text]


def _split_by_length(text: str, target: int) -> list[str]:
    """按空行分段，再把小段合并到大约 target 字。

    不能直接按字符数硬切：那样会把一句话拦腰截断，AI 读到的半句话
    容易生成错卡片。按段落攒，只有单段本身超长时才退化成按行切。
    """
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return [text]

    blocks: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        if current and current_len + len(paragraph) > target:
            blocks.append("\n\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len += len(paragraph)

    if current:
        blocks.append("\n\n".join(current))

    # 单段超长（比如一整页没有换行的内容）再按行切
    result: list[str] = []
    for block in blocks:
        if len(block) <= target * 2:
            result.append(block)
            continue
        lines = block.split("\n")
        buffer: list[str] = []
        buffer_len = 0
        for line in lines:
            if buffer and buffer_len + len(line) > target:
                result.append("\n".join(buffer))
                buffer = [line]
                buffer_len = len(line)
            else:
                buffer.append(line)
                buffer_len += len(line)
        if buffer:
            result.append("\n".join(buffer))

    return result


def _looks_like_text(extraction: Extraction) -> bool:
    """够不够当「有文字层」用。与 iOS 的判定一致：总字数与平均每单元字数都达标。

    门槛不是为了挑剔，是为了拦住「只有页眉页脚和页码」的扫描件 ——
    那种 PDF 能抽出几十个字，但让 AI 基于它生成卡片纯属浪费钱。
    """
    total = extraction.text_length
    if total < limits.TEXT_LAYER_MIN_CHARS:
        return False
    count = max(1, extraction.page_count)
    return total / count >= limits.TEXT_LAYER_MIN_PER_PAGE
