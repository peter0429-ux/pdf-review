"""卡片与文档的数据结构 —— 与 iOS 的 `AnalysisDocument` / `ReviewCard` 对齐。

用 dataclass 而不是裸 dict，理由：字段名拼错在第一次赋值时就报错，
而不是等到导出 JSON、iOS 导入失败时才发现（那是用户端，代价高得多）。
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import datetime
from typing import Any, Optional

from . import limits


@dataclasses.dataclass
class Card:
    """一张复习卡片。

    与 iOS `AnalysisDocument.CardItem` 字段一一对应。可选字段用 None 表示
    「不写进 JSON」，而不是空字符串 —— 两者的区别在 iOS 侧会影响
    `!tags.isEmpty` 之类的判断。
    """

    question: str
    answer: str
    detail: Optional[str] = None
    tags: Optional[list[str]] = None
    source_page: Optional[int] = None
    difficulty: Optional[int] = None
    importance: Optional[int] = None

    # -- 与 JSON 的互转 --------------------------------------------------
    #
    # JSON 里用 camelCase（iOS 的 Codable 默认键名），Python 里用 snake_case。
    # 名字对照集中在这两个方法里，别的地方不许出现 "sourcePage" 字面量。

    def to_json(self) -> dict[str, Any]:
        """转成写进 .pdfreview.json 的字典。

        只写有值的字段。None 的字段整条省略，而不是写 `null` ——
        iOS 的 Codable 对 `null` 与「键不存在」处理不同：
        可选字段遇 null 会解码成 nil，行为一样，但省略更干净、文件更小。
        """
        data: dict[str, Any] = {
            "question": self.question,
            "answer": self.answer,
        }
        if self.detail is not None:
            data["detail"] = self.detail
        if self.tags is not None:
            data["tags"] = list(self.tags)
        if self.source_page is not None:
            data["sourcePage"] = self.source_page
        if self.difficulty is not None:
            data["difficulty"] = self.difficulty
        if self.importance is not None:
            data["importance"] = self.importance
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Card":
        """从 JSON 字典构造。未知字段由 `schema_check` 负责拒绝，这里只取值。"""
        return cls(
            question=str(data.get("question", "")),
            answer=str(data.get("answer", "")),
            detail=_opt_str(data.get("detail")),
            tags=_opt_str_list(data.get("tags")),
            source_page=_opt_int(data.get("sourcePage")),
            difficulty=_opt_int(data.get("difficulty")),
            importance=_opt_int(data.get("importance")),
        )

    def copy(self) -> "Card":
        """深拷贝。界面编辑草稿时要能放弃改动，得拿一份独立对象。"""
        return dataclasses.replace(
            self,
            tags=list(self.tags) if self.tags is not None else None,
        )


@dataclasses.dataclass
class Deck:
    """牌组元信息。"""

    title: str
    summary: Optional[str] = None
    language: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"title": self.title}
        if self.summary is not None:
            data["summary"] = self.summary
        if self.language is not None:
            data["language"] = self.language
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Deck":
        return cls(
            title=str(data.get("title", "")),
            summary=_opt_str(data.get("summary")),
            language=_opt_str(data.get("language")),
        )


@dataclasses.dataclass
class Source:
    """来源文件信息。"""

    file_name: str
    page_count: int
    sha256: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "fileName": self.file_name,
            "pageCount": self.page_count,
        }
        if self.sha256 is not None:
            data["sha256"] = self.sha256
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Source":
        return cls(
            file_name=str(data.get("fileName", "")),
            page_count=_opt_int(data.get("pageCount")) or 0,
            sha256=_opt_str(data.get("sha256")),
        )


@dataclasses.dataclass
class AnalysisDocument:
    """一份完整的 .pdfreview.json。

    字段顺序与 `schema/analysis.v1.schema.json` 的 properties 一致；
    写文件时按键名排序，所以这个顺序只影响可读性。
    """

    schema_version: str
    generated_at: str
    source: Source
    deck: Deck
    cards: list[Card]
    generator: Optional[str] = None

    #: 当前支持的版本
    SUPPORTED_VERSION = limits.SUPPORTED_VERSION

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "generatedAt": self.generated_at,
            "source": self.source.to_json(),
            "deck": self.deck.to_json(),
            "cards": [card.to_json() for card in self.cards],
        }
        if self.generator is not None:
            data["generator"] = self.generator
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "AnalysisDocument":
        return cls(
            schema_version=str(data.get("schemaVersion", "")),
            generated_at=str(data.get("generatedAt", "")),
            source=Source.from_json(data.get("source") or {}),
            deck=Deck.from_json(data.get("deck") or {}),
            cards=[Card.from_json(item) for item in (data.get("cards") or [])],
            generator=_opt_str(data.get("generator")),
        )

    def encoded(self) -> str:
        """序列化成人类可读的 JSON 文本。

        `ensure_ascii=False` 是必须的：默认会把中文转成 \\uXXXX，
        文件打开全是转义序列，用户没法手工编辑，也看不出内容对不对。

        `sort_keys=True` 让同一份内容每次导出字节一致，便于比较与去重。
        末尾补换行：git 与多数编辑器都喜欢文件以换行结束。
        """
        return (
            json.dumps(
                self.to_json(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    # ------------------------------------------------------------------
    # 语义校验
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """检查这份文档能不能被 iOS 收下。返回问题列表，空表示可用。

        逐条对应 iOS 的 `AnalysisValidator.validate(_:)`，顺序也照抄 ——
        这样两端报的第一个问题总是一样的，用户不会看到「电脑说 A 不行、
        手机说 B 不行」。

        与 `schema_check` 的分工：
          - 这里查**语义**（长度、非空、范围、标签去重），不查类型与未知字段。
          - `schema_check` 查**结构**（类型、必填、未知键、正则）。
        导出前两个都要过；只过一个是不可靠的。
        """
        problems: list[str] = []

        if self.schema_version != limits.SUPPORTED_VERSION:
            problems.append(
                f"schemaVersion 是 {self.schema_version!r}，"
                f"这个版本只认 {limits.SUPPORTED_VERSION!r}"
            )

        if not _ISO8601_RE.match(self.generated_at):
            problems.append(
                f"generatedAt 不是合法的 ISO 8601 时间（必须带 Z 或 ±HH:MM）："
                f"{self.generated_at!r}"
            )

        if self.generator is not None and len(self.generator) > limits.GENERATOR_MAX:
            problems.append(
                f"generator 超过 {limits.GENERATOR_MAX} 字（现在 {len(self.generator)}）"
            )

        if self.deck.summary is not None and len(self.deck.summary) > limits.SUMMARY_MAX:
            problems.append(
                f"牌组摘要超过 {limits.SUMMARY_MAX} 字（现在 {len(self.deck.summary)}）"
            )

        if not self.deck.title.strip():
            problems.append("牌组标题不能为空")
        elif len(self.deck.title) > limits.TITLE_MAX:
            problems.append(
                f"牌组标题超过 {limits.TITLE_MAX} 字（现在 {len(self.deck.title)}）"
            )

        if not (1 <= len(self.cards) <= limits.CARDS_MAX):
            problems.append(
                f"卡片数量要在 1 到 {limits.CARDS_MAX} 之间（现在 {len(self.cards)}）"
            )

        for index, card in enumerate(self.cards, start=1):
            problems.extend(_validate_card(card, index))

        return problems


_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$"
)


def _validate_card(card: Card, index: int) -> list[str]:
    """单张卡片的语义校验。index 从 1 起，报错时告诉用户是第几张。"""
    problems: list[str] = []
    prefix = f"第 {index} 张卡片"

    if not card.question.strip():
        problems.append(f"{prefix}：题目不能为空")
    elif len(card.question) > limits.QUESTION_MAX:
        problems.append(
            f"{prefix}：题目超过 {limits.QUESTION_MAX} 字（现在 {len(card.question)}）"
        )

    if not card.answer.strip():
        problems.append(f"{prefix}：答案不能为空")
    elif len(card.answer) > limits.ANSWER_MAX:
        problems.append(
            f"{prefix}：答案超过 {limits.ANSWER_MAX} 字（现在 {len(card.answer)}）"
        )

    if card.detail is not None and len(card.detail) > limits.DETAIL_MAX:
        problems.append(
            f"{prefix}：补充说明超过 {limits.DETAIL_MAX} 字（现在 {len(card.detail)}）"
        )

    if card.tags is not None:
        if len(card.tags) > limits.TAGS_MAX:
            problems.append(
                f"{prefix}：标签超过 {limits.TAGS_MAX} 个（现在 {len(card.tags)}）"
            )
        seen: set[str] = set()
        for tag in card.tags:
            if not tag.strip():
                problems.append(f"{prefix}：有空白标签")
                break
            if len(tag) > limits.TAG_LENGTH_MAX:
                problems.append(
                    f"{prefix}：标签 {tag[:10]!r} 超过 {limits.TAG_LENGTH_MAX} 字"
                )
                break
            if tag in seen:
                problems.append(f"{prefix}：标签 {tag!r} 重复了")
                break
            seen.add(tag)

    if card.source_page is not None and card.source_page < 1:
        problems.append(f"{prefix}：sourcePage 必须 ≥ 1（现在是 {card.source_page}）")

    for name, value in (("difficulty", card.difficulty), ("importance", card.importance)):
        if value is not None and not (limits.SCORE_MIN <= value <= limits.SCORE_MAX):
            problems.append(
                f"{prefix}：{name} 要在 {limits.SCORE_MIN} 到 {limits.SCORE_MAX} 之间"
                f"（现在是 {value}）"
            )

    return problems


# ---------------------------------------------------------------------------
# 取值的容错辅助
# ---------------------------------------------------------------------------
#
# AI 返回的 JSON 里，类型经常不是你以为的那个：`sourcePage` 可能给成
# "12" 字符串或 12.0 浮点；`tags` 可能给成单个字符串而不是数组。
# 这几个函数把这堆破烂挡在这里，别让它流到校验器再报「类型不对」。


def _opt_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    # 数字之类当成文本，比直接丢弃信息更合理
    return str(value)


def _opt_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            try:
                return int(float(value.strip()))
            except ValueError:
                return None
    return None


def _opt_str_list(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        # 单个字符串当单元素数组，比丢掉强
        text = value.strip()
        return [text] if text else None
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    return None


#: ISO 8601 带时区的格式，与 schema 的 generatedAt.pattern 一致。
def now_iso8601() -> str:
    """当前本地时间的 ISO 8601 表示，带时区偏移。

    不用 `datetime.now().isoformat()`：那个在无时区时会产出
    `2026-11-21T10:00:00`（没有 Z 也没有 +08:00），iOS 会拒收。
    用 `astimezone()` 保证一定带偏移。
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")
