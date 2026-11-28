"""本地牌组库：每个牌组一个文件夹，里面放 `deck.pdfreview.json` 和 `meta.json`。

为什么要落盘而不是只在内存里攒着：
  - 分析一份几十页的文档要几分钟、几十次请求。中途关掉窗口全丢掉，用户会骂人。
  - 用户可能想拿同一份文档的不同章节反复生成，或者事后手工改几张卡。
  - 导出给 iPhone 的 `.pdfreview.json` 就是这个文件，不用另存一份。

为什么一个牌组一个文件夹而不是一个 JSON 装全部：
  - 单文件损坏只毁一个牌组，不是全部。
  - 以后加缩略图、原始抽取文本，直接放进同一个文件夹，不用改结构。

默认位置：`%USERPROFILE%\\Documents\\PdfReviewPC\\decks\\`。
放「文档」而不是 `%APPDATA%`，是因为用户会想自己去文件夹里找导出的 JSON。

便携模式（exe 旁边有 `portable.txt`，或设了 `PDFREVIEW_HOME`）下改成
程序目录里的 `decks\\`，整个文件夹可以拷走。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from . import cards as cards_mod
from .cards import AnalysisDocument
from .settings import portable_dir

#: 牌组主文件的固定名字。刻意用带 `.pdfreview.json` 的名字，
#: 这样用户在资源管理器里一眼能认出来「这就是要传到手机上的那个文件」。
DECK_FILE_NAME = "deck.pdfreview.json"

#: 辅助信息（不属于格式标准，iOS 不会读这个文件）
META_FILE_NAME = "meta.json"


def default_workspace() -> Path:
    """牌组库的根目录。

    便携模式用程序目录（跟着 exe 走），否则 `%USERPROFILE%\\Documents\\PdfReviewPC`。

    只算路径不建目录——理由同 `settings.app_data_dir()`：读列表时目录不存在
    本来就该得到空列表，不该把程序拦在启动画面之外。
    """
    portable = portable_dir()
    if portable is not None:
        return portable
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "Documents" / "PdfReviewPC"


def decks_dir(workspace: Optional[Path] = None) -> Path:
    """牌组目录。同样只算路径；真要写牌组时由 `create` 建。"""
    root = workspace or default_workspace()
    return root / "decks"


# ---------------------------------------------------------------------------
# 文件夹命名
# ---------------------------------------------------------------------------

#: Windows 文件名里不允许出现的字符。另外要挡掉结尾的点和空格
#: （`foo.` 与 `foo ` 在资源管理器里创建会失败或被自动改名）。
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_folder_name(title: str, suffix: str) -> str:
    """把牌组标题变成安全的文件夹名。

    截到 60 个字符：Windows 的路径总长上限是 260，牌组名再长就会在
    深层目录里触发「路径过长」，而那个错误信息完全看不出是名字的问题。
    """
    cleaned = _ILLEGAL_CHARS.sub("", title).strip().rstrip(". ")
    if not cleaned:
        cleaned = "未命名牌组"
    if len(cleaned) > 60:
        cleaned = cleaned[:60].rstrip(". ")
    return f"{cleaned}-{suffix}"


def _short_hash(text: str) -> str:
    """8 位十六进制，够避开同名冲突（同标题不同内容的概率远小于 1/16^8）。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# 牌组
# ---------------------------------------------------------------------------


@dataclass
class DeckMeta:
    """`meta.json` 的内容 —— 只给本程序用，不进格式标准。"""

    title: str
    source_file: Optional[str] = None
    source_kind: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    #: 抽取时用的页数（PDF 是页数，docx 之类按「段」折算，见 extract.py）
    page_count: int = 0
    #: 抽取出来的纯文本长度，界面上显示「原文 xx 字」
    text_length: int = 0
    #: 上次分析到第几块，用于断点续跑（0 表示没开始）
    chunks_done: int = 0

    def to_json(self) -> dict:
        return {
            "title": self.title,
            "sourceFile": self.source_file,
            "sourceKind": self.source_kind,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "pageCount": self.page_count,
            "textLength": self.text_length,
            "chunksDone": self.chunks_done,
        }

    @classmethod
    def from_json(cls, data: dict) -> "DeckMeta":
        return cls(
            title=str(data.get("title", "")),
            source_file=_opt(data.get("sourceFile")),
            source_kind=_opt(data.get("sourceKind")),
            created_at=str(data.get("createdAt", "")),
            updated_at=str(data.get("updatedAt", "")),
            page_count=_int(data.get("pageCount")),
            text_length=_int(data.get("textLength")),
            chunks_done=_int(data.get("chunksDone")),
        )


@dataclass
class DeckEntry:
    """牌组列表里的一行。只读元信息，不加载全部卡片（列表可能有几十个）。"""

    folder: Path
    meta: DeckMeta
    card_count: int

    @property
    def title(self) -> str:
        return self.meta.title or self.folder.name

    @property
    def updated_at(self) -> str:
        return self.meta.updated_at


class DeckStore:
    """牌组库。所有路径操作都收在这里，界面不直接拼路径。"""

    def __init__(self, workspace: Optional[Path] = None) -> None:
        self.workspace = workspace or default_workspace()
        self.root = decks_dir(self.workspace)

    # -- 读 ------------------------------------------------------------

    def list(self) -> list[DeckEntry]:
        """列出所有牌组，按更新时间倒序。

        单个牌组读不出来时跳过它而不是整体失败：一个坏文件夹不该让
        整个列表变成空的。
        """
        entries: list[DeckEntry] = []
        if not self.root.exists():
            return entries

        for folder in self.root.iterdir():
            if not folder.is_dir():
                continue
            deck_path = folder / DECK_FILE_NAME
            if not deck_path.exists():
                continue
            try:
                document = load_document(deck_path)
                meta = load_meta(folder, fallback_title=document.deck.title)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            entries.append(
                DeckEntry(folder=folder, meta=meta, card_count=len(document.cards))
            )

        entries.sort(key=lambda e: e.meta.updated_at, reverse=True)
        return entries

    def load(self, folder: Path) -> tuple[AnalysisDocument, DeckMeta]:
        document = load_document(folder / DECK_FILE_NAME)
        meta = load_meta(folder, fallback_title=document.deck.title)
        return document, meta

    # -- 写 ------------------------------------------------------------

    def create(
        self,
        document: AnalysisDocument,
        meta: DeckMeta,
        folder_name_suffix: Optional[str] = None,
    ) -> Path:
        """新建一个牌组文件夹并写盘，返回文件夹路径。

        同名标题不会覆盖已有牌组：文件夹名后面带内容哈希，
        内容不同哈希就不同。
        """
        if not meta.created_at:
            meta.created_at = cards_mod.now_iso8601()
        meta.updated_at = meta.created_at
        meta.title = document.deck.title

        suffix = folder_name_suffix or _short_hash(document.deck.title)
        folder = self.root / safe_folder_name(document.deck.title, suffix)

        # 极端情况：同标题同哈希（同一份文档重复导入）——加序号而不是覆盖
        counter = 2
        base = folder
        while folder.exists():
            folder = base.with_name(f"{base.name}-{counter}")
            counter += 1

        folder.mkdir(parents=True, exist_ok=False)
        try:
            save_document(folder / DECK_FILE_NAME, document)
            save_meta(folder, meta)
        except Exception:
            # 写了一半的文件夹比没有更糟：用户会看到一个点不开的牌组。
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return folder

    def save(self, folder: Path, document: AnalysisDocument, meta: DeckMeta) -> None:
        """覆盖保存。先写临时文件再替换，避免半个 JSON。"""
        meta.title = document.deck.title
        meta.updated_at = cards_mod.now_iso8601()
        save_document(folder / DECK_FILE_NAME, document)
        save_meta(folder, meta)

    def delete(self, folder: Path) -> None:
        """删掉整个牌组文件夹。

        调用方（界面）必须先确认过。这里再挡一次：只允许删
        `decks/` 下的直接子文件夹，防止路径拼错删到别处。
        """
        resolved = folder.resolve()
        root_resolved = self.root.resolve()
        if resolved.parent != root_resolved:
            raise ValueError(f"拒绝删除牌组目录之外的路径：{resolved}")
        shutil.rmtree(resolved)

    # -- 导出 ----------------------------------------------------------

    def export(self, folder: Path, destination: Path) -> Path:
        """把牌组导出成一个独立的 `.pdfreview.json`。

        不是简单复制：导出前重新校验一遍，把不合格的字段修掉或报错，
        免得用户拿到手机上才发现导入失败。
        """
        document = load_document(folder / DECK_FILE_NAME)
        problems = document.validate()
        if problems:
            raise ValueError("这份牌组还有问题，先在电脑上修好：" + "；".join(problems[:5]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document.encoded(), encoding="utf-8")
        return destination


# ---------------------------------------------------------------------------
# 文件读写
# ---------------------------------------------------------------------------


def load_document(path: Path) -> AnalysisDocument:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 的顶层不是对象")
    return AnalysisDocument.from_json(data)


def save_document(path: Path, document: AnalysisDocument) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(document.encoded(), encoding="utf-8")
    os.replace(tmp, path)


def load_meta(folder: Path, fallback_title: str) -> DeckMeta:
    path = folder / META_FILE_NAME
    if not path.exists():
        # 老版本或手工放进去的牌组没 meta.json，用文件名兜底
        return DeckMeta(title=fallback_title)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DeckMeta(title=fallback_title)
    if not isinstance(data, dict):
        return DeckMeta(title=fallback_title)
    return DeckMeta.from_json(data)


def save_meta(folder: Path, meta: DeckMeta) -> None:
    path = folder / META_FILE_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(meta.to_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _opt(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
