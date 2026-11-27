"""把抽取出来的文本切成块，供逐块请求模型。

切法照抄 iOS 的 `PDFTextExtractor.chunk(maxChars:)`：按单元（页/节/张）
累积，凑到 `CHUNK_MAX_CHARS` 就切一刀；单页本身就超长时，把这一页按行
再切开。这样一块里的内容总是连续的，AI 读到的上下文不会跳着断。

为什么不设重叠（overlap）：
  - 重叠会让相邻两块出现重复内容，生成出重复卡片；去重能拦住，但白花了
    token。
  - 卡片题面要求「能在原文找到依据」，跨块边界丢掉的半句话本来也不该
    单独成卡。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import limits
from .extract import Extraction, Segment


@dataclass
class Chunk:
    """一块待分析的文本。"""

    index: int
    #: 这块覆盖的单元序号（1 起，闭区间）
    first_segment: int
    last_segment: int
    text: str
    #: 单元的种类名（「页」「节」「张幻灯片」……）。
    #: 存一份是因为界面与 prompt 都要说「第 3 页」而不是「第 3」——
    #: 后者读起来像半句话，用户也不知道第 3 是什么。
    unit_label: str = "页"

    @property
    def segment_span(self) -> str:
        """给界面和 prompt 看的范围描述，比如「第 1–3 页」。"""
        if self.first_segment == self.last_segment:
            return f"第 {self.first_segment} {self.unit_label}"
        return f"第 {self.first_segment}–{self.last_segment} {self.unit_label}"

    @property
    def char_count(self) -> int:
        return len(self.text)


def chunk_extraction(
    extraction: Extraction, max_chars: int = limits.CHUNK_MAX_CHARS
) -> list[Chunk]:
    """把抽取结果切成块。

    空单元（扫描件里的空白页、只有图的幻灯片）不占独立的块，
    但要更新「这块覆盖到第几页」——否则卡片上的页码会往回跳。
    """
    chunks: list[Chunk] = []
    unit_label = extraction.unit_label

    buffer: list[str] = []
    buffer_len = 0
    first_segment = 0
    last_segment = 0

    def flush() -> None:
        nonlocal buffer, buffer_len, first_segment, last_segment
        text = "\n\n".join(buffer).strip()
        if text:
            chunks.append(
                Chunk(
                    index=len(chunks) + 1,
                    first_segment=first_segment,
                    last_segment=last_segment,
                    text=text,
                    unit_label=unit_label,
                )
            )
        buffer = []
        buffer_len = 0
        first_segment = 0
        last_segment = 0

    for segment in extraction.segments:
        text = segment.text.strip()
        if not text:
            continue

        # 单页就超长：先把攒着的吐出去，再把这一页单独切
        if len(text) > max_chars:
            flush()
            for piece in _split_long_text(text, max_chars):
                chunks.append(
                    Chunk(
                        index=len(chunks) + 1,
                        first_segment=segment.index,
                        last_segment=segment.index,
                        text=piece,
                        unit_label=unit_label,
                    )
                )
            continue

        # 加上这一页会超：先吐出去，再开始新的
        if buffer and buffer_len + len(text) > max_chars:
            flush()

        if not buffer:
            first_segment = segment.index
        last_segment = segment.index
        buffer.append(text)
        buffer_len += len(text)

    flush()
    return chunks


def _split_long_text(text: str, max_chars: int) -> list[str]:
    """把一段超长文本切开。先按行，单行还超长就按字符硬切。

    硬切是最后手段：一刀切在句子中间，那一块的最后半句会缺主语。
    只有在遇到「整页没有换行符」的极端 PDF 时才会走到这里。
    """
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    buffer: list[str] = []
    buffer_len = 0

    for line in text.split("\n"):
        # 单行本身超长：按字符切
        if len(line) > max_chars:
            if buffer:
                pieces.append("\n".join(buffer))
                buffer = []
                buffer_len = 0
            for start in range(0, len(line), max_chars):
                pieces.append(line[start : start + max_chars])
            continue

        if buffer and buffer_len + len(line) + 1 > max_chars:
            pieces.append("\n".join(buffer))
            buffer = [line]
            buffer_len = len(line) + 1
        else:
            buffer.append(line)
            buffer_len += len(line) + 1

    if buffer:
        pieces.append("\n".join(buffer))

    return [piece for piece in pieces if piece.strip()]


def estimate_cards(chunk_count: int, cards_per_chunk: int) -> int:
    """预估会生成多少张卡，用于界面提示「大概需要多久」。

    不是精确值（模型每次给的不一样），但量级对得上，用户心里有数。
    """
    return chunk_count * max(1, cards_per_chunk)
