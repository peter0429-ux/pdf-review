"""把一份文件走完整条链路：抽取 → 切块 → 逐块问模型 → 去重 → 组装文档。

这一层是界面唯一需要认识的东西。界面不该知道 pypdf 怎么用、重试几次、
卡片字段截到多少字——它只要进度和结果。

**分层红线**（与 `core/__init__.py` 一致）：
不 import tkinter，不弹对话框，出错就用异常往上抛。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import ai, limits
from .cards import AnalysisDocument, Card, Deck, Source, now_iso8601
from .chunker import Chunk, chunk_extraction, estimate_cards
from .extract import Extraction, ExtractError, extract

#: 一条进度事件。界面拿它画进度条和「第 3/8 块」。
#:
#: 为什么不只回一个 0…1 的浮点数：模型每块耗时差别很大，只涨百分比的话
#: 用户无法判断「是卡住了还是在干活」。块号和已出卡片数能说明它没死。
@dataclass
class Progress:
    #: 0…1，已完成块数占比
    fraction: float = 0.0
    #: 正在处理第几块（1 起；0 表示还没开始）
    chunk_index: int = 0
    chunk_total: int = 0
    #: 到目前为止攒了多少张卡
    cards_so_far: int = 0
    #: 最近一块产出的卡片题面，给界面做「刚出了什么」的提示
    recent_questions: list[str] = field(default_factory=list)
    #: 人话说明，直接显示在进度条下面
    stage: str = ""

    @property
    def percent(self) -> int:
        return int(round(max(0.0, min(1.0, self.fraction)) * 100))


@dataclass
class AnalysisOutcome:
    """一次分析的全部结果，界面拿它填列表、写盘、算统计。"""

    document: AnalysisDocument
    extraction: Extraction
    chunks: list[Chunk]
    #: 被去重丢掉的张数。界面可以提一句「合并了 N 张重复卡片」。
    dropped_duplicates: int = 0


class AnalysisError(Exception):
    """分析过程失败。消息本身就可以直接展示给用户。"""


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(block)
    return digest.hexdigest()


def _deck_summary(card_count: int, last_segment: int, unit_label: str) -> str:
    """和 iOS 侧同一条口径：「共 N 张卡片，覆盖第 1 至 M 页。」

    单元名跟着文件类型走——md 是「节」、pptx 是「张幻灯片」，
    硬写「页」会让用户以为哪儿算错了。
    """
    return f"共 {card_count} 张卡片，覆盖第 1 至 {last_segment} {unit_label}。"


def analyze_file(
    path: Path | str,
    *,
    config: ai.AIConfig,
    title: Optional[str] = None,
    cards_per_chunk: int = 6,
    on_progress: Optional[Callable[[Progress], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    extraction: Optional[Extraction] = None,
) -> AnalysisOutcome:
    """完整分析一份文件。

    `extraction` 已经抽好时可以不传 `path` 之外的抽取——界面「预览」过再分析
    就不用抽两遍（大文件抽一次要好几秒）。
    """
    source_path = Path(path)
    report = on_progress or (lambda _p: None)

    def emit(progress: Progress) -> None:
        report(progress)

    # ---- 1. 抽取 ----
    if extraction is None:
        emit(Progress(stage="正在读取文件…"))
        try:
            extraction = extract(source_path)
        except ExtractError as exc:
            raise AnalysisError(str(exc)) from exc

    if not extraction.segments:
        raise AnalysisError("这份文件里没有读到任何文字。")

    # ---- 2. 切块 ----
    chunks = chunk_extraction(extraction)
    if not chunks:
        raise AnalysisError("这份文件里没有读到任何文字。")

    total = len(chunks)
    per_chunk = max(1, min(cards_per_chunk, 12))
    emit(
        Progress(
            fraction=0.0,
            chunk_index=1,
            chunk_total=total,
            cards_so_far=0,
            stage=f"已切成 {total} 块，开始请求模型…",
        )
    )

    # ---- 3. 逐块问模型 ----
    collected: list[Card] = []
    for chunk in chunks:
        if cancel_check is not None and cancel_check():
            raise ai.AICancelled("分析已取消。")

        try:
            result = ai.analyze_chunk(
                chunk,
                document_title=title or extraction.stem_title,
                config=config,
                card_count=per_chunk,
                cancel_check=cancel_check,
            )
        except ai.AICancelled:
            raise
        except ai.AIError as exc:
            raise AnalysisError(str(exc)) from exc

        collected.extend(result.cards)

        # iOS 那边 500 张就停，PC 也一样——不是为了省 token，
        # 是再多用户也复习不完，而且文件会大到 iOS 不肯导入。
        if len(collected) >= limits.CARDS_MAX:
            collected = collected[: limits.CARDS_MAX]
            emit(
                Progress(
                    fraction=1.0,
                    chunk_index=chunk.index,
                    chunk_total=total,
                    cards_so_far=len(collected),
                    recent_questions=[card.question for card in result.cards],
                    stage=f"卡片数已达上限 {limits.CARDS_MAX} 张，提前结束。",
                )
            )
            break

        emit(
            Progress(
                fraction=chunk.index / total,
                chunk_index=chunk.index,
                chunk_total=total,
                cards_so_far=len(collected),
                recent_questions=[card.question for card in result.cards],
                stage=f"已完成第 {chunk.index} / {total} 块",
            )
        )

    if not collected:
        raise AnalysisError("模型没有给出任何可用卡片。可以换个模型再试。")

    # ---- 4. 去重 ----
    deduped = ai.deduplicate(collected)
    dropped = len(collected) - len(deduped)

    # ---- 5. 组装 ----
    last_segment = chunks[-1].last_segment
    document = AnalysisDocument(
        schema_version=limits.SUPPORTED_VERSION,
        generated_at=now_iso8601(),
        source=Source(
            file_name=extraction.file_name,
            page_count=max(1, extraction.page_count),
            sha256=_sha256_of(source_path),
        ),
        deck=Deck(
            title=(title or extraction.stem_title)[: limits.TITLE_MAX],
            summary=_deck_summary(len(deduped), last_segment, extraction.unit_label)[
                : limits.SUMMARY_MAX
            ],
        ),
        cards=deduped,
        generator=ai.GENERATOR,
    )

    emit(
        Progress(
            fraction=1.0,
            chunk_index=total,
            chunk_total=total,
            cards_so_far=len(deduped),
            stage="分析完成",
        )
    )

    return AnalysisOutcome(
        document=document,
        extraction=extraction,
        chunks=chunks,
        dropped_duplicates=dropped,
    )


def estimate_total_cards(extraction: Extraction, cards_per_chunk: int) -> int:
    """给界面预估一个「大概会出多少张」，用在开始之前的确认提示里。

    只是估算：模型经常少出，所以文案要说「最多」或「大约」。
    """
    chunks = chunk_extraction(extraction)
    return estimate_cards(len(chunks), max(1, min(cards_per_chunk, 12)))
