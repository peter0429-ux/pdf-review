"""右侧的卡片预览。

只读。要改卡片请回 iOS 版——PC 版的定位是「批量生产 + 导出」，
在这里做编辑器会引出「改了一半直接导出」的责任问题，而这个问题
在手机上本来就是解决了的。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Optional

from core.cards import AnalysisDocument, Card

from . import theme
from .widgets import Chip, IndexBadge, ScrollArea, round_rect


class CardPreview(tk.Frame):
    """一张卡一张卡地往下滚。"""

    def __init__(self, master: tk.Misc, fonts: dict[str, tkfont.Font]) -> None:
        super().__init__(master, background=theme.SURFACE, highlightthickness=0, bd=0)
        self._fonts = fonts
        self._document: Optional[AnalysisDocument] = None
        #: 文字换行宽度，跟着窗格宽度变。
        self._wrap = 420

        head = tk.Frame(self, background=theme.SURFACE)
        head.pack(fill="x", padx=theme.PAD_L, pady=(theme.PAD_M, 2))

        self._title = tk.Label(
            head,
            text="还没有选择牌组",
            background=theme.SURFACE,
            foreground=theme.TEXT,
            font=fonts["h2"],
            anchor="w",
        )
        self._title.pack(side="left")

        self._count = tk.Label(
            head,
            text="",
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=fonts["small"],
        )
        self._count.pack(side="right")

        self._summary = tk.Label(
            self,
            text="",
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=fonts["small"],
            wraplength=520,
            justify="left",
            anchor="w",
        )
        self._summary.pack(fill="x", padx=theme.PAD_L, pady=(0, theme.PAD_M))

        self._scroll = ScrollArea(self, background=theme.SURFACE)
        self._scroll.pack(fill="both", expand=True)
        self._scroll.canvas.bind("<Configure>", self._on_canvas_configure, add="+")

    # -- 对外 ------------------------------------------------------------

    def show(self, document: Optional[AnalysisDocument]) -> None:
        self._document = document
        self._scroll.clear()

        if document is None:
            self._title.configure(text="还没有选择牌组")
            self._count.configure(text="")
            self._summary.configure(text="左边选一个牌组看看内容。")
            self._render_empty_hint()
            return

        self._title.configure(text=document.deck.title)
        self._count.configure(text=f"{len(document.cards)} 张卡片")
        self._summary.configure(text=document.deck.summary or "")

        if not document.cards:
            self._render_empty_hint()
            return

        for index, card in enumerate(document.cards, start=1):
            self._render_card(index, card)

        # 底部留一段空白，最后一张卡不要贴着窗口边
        tk.Frame(self._scroll.inner, background=theme.SURFACE, height=theme.PAD_L).pack(fill="x")
        self._scroll.scroll_to_top()

    # -- 内部 ------------------------------------------------------------

    def _render_empty_hint(self) -> None:
        holder = tk.Frame(self._scroll.inner, background=theme.SURFACE)
        holder.pack(fill="both", expand=True, pady=60)
        tk.Label(
            holder,
            text="这个牌组里还没有卡片",
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=self._fonts["body"],
        ).pack()

    def _render_card(self, index: int, card: Card) -> None:
        """一张卡片：圆角底 + 序号徽章 + 题面 + 元信息胶囊 + 答案 + 补充说明。

        用 Canvas 画圆角底再往里塞控件是行不通的（控件会盖住画布），所以
        这里用「外层 Frame 当 1px 边距、内层 Frame 当底色」的土办法模拟
        圆角卡片：视觉上是一个带细边框的白块，配合浅灰底色足够像一张卡。
        """
        outer = tk.Frame(self._scroll.inner, background=theme.SURFACE)
        outer.pack(fill="x", padx=theme.PAD_L, pady=(0, 10))

        card_bg = theme.SURFACE_ALT
        box = tk.Frame(
            outer,
            background=card_bg,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        box.pack(fill="x")

        top = tk.Frame(box, background=card_bg)
        top.pack(fill="x", padx=14, pady=(12, 0))

        IndexBadge(top, index, self._fonts["small"], parent_background=card_bg).pack(
            side="left", anchor="n", pady=(1, 0)
        )

        text_col = tk.Frame(top, background=card_bg)
        text_col.pack(side="left", fill="x", expand=True, padx=(10, 0))

        question = tk.Label(
            text_col,
            text=card.question,
            background=card_bg,
            foreground=theme.TEXT,
            font=self._fonts["body_bold"],
            wraplength=self._wrap,
            justify="left",
            anchor="w",
        )
        question.pack(fill="x")

        meta_bits: list[str] = []
        if card.source_page:
            meta_bits.append(f"第 {card.source_page} 页")
        if card.difficulty and card.difficulty != 3:
            meta_bits.append(f"难度 {card.difficulty}")
        if card.importance and card.importance != 3:
            meta_bits.append(f"重要 {card.importance}")

        chips_row = tk.Frame(text_col, background=card_bg)
        chips_row.pack(fill="x", pady=(5, 0))

        for bit in meta_bits:
            Chip(
                chips_row,
                bit,
                self._fonts["small"],
                foreground=theme.TEXT_SOFT,
                background=theme.SURFACE,
                parent_background=card_bg,
            ).pack(side="left", padx=(0, 5))

        for tag in card.tags[:5]:
            Chip(
                chips_row,
                tag,
                self._fonts["small"],
                foreground=theme.ACCENT_DARK,
                background=theme.ACCENT_SOFT,
                parent_background=card_bg,
            ).pack(side="left", padx=(0, 5))

        answer = tk.Label(
            box,
            text=card.answer,
            background=card_bg,
            foreground=theme.TEXT_SOFT,
            font=self._fonts["body"],
            wraplength=self._wrap,
            justify="left",
            anchor="w",
        )
        answer.pack(fill="x", padx=14, pady=(9, 0))

        if card.detail:
            tk.Frame(box, background=theme.BORDER, height=1).pack(fill="x", padx=14, pady=(9, 0))
            tk.Label(
                box,
                text=card.detail,
                background=card_bg,
                foreground=theme.MUTED,
                font=self._fonts["small"],
                wraplength=self._wrap,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=14, pady=(7, 0))

        tk.Frame(box, background=card_bg, height=12).pack(fill="x")

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # 换行宽度跟着窗格走。减掉的常量是卡片左右内边距 + 序号徽章宽度。
        # 给不够的话最后几个字会被卡片边框切掉。
        wrap = max(200, event.width - 108)
        if abs(wrap - self._wrap) <= 8:
            return
        self._wrap = wrap
        self._reflow()

    def _reflow(self) -> None:
        """按新的换行宽度重排文字。

        Tk 的 Label 不会因为父容器变宽就重算换行，只能改 wraplength 再让
        几何管理器重算。逐层找一遍比给每个 Label 存引用简单，一屏也就
        十几个卡片。
        """
        def walk(widget: tk.Misc) -> None:
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(wraplength=self._wrap)
                walk(child)

        walk(self._scroll.inner)
