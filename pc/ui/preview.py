"""右侧的卡片预览。

只读。要改卡片请回 iOS 版——PC 版的定位是「批量生产 + 导出」，
在这里做编辑器会引出「改了一半直接导出」的责任问题，而这个问题
在手机上本来就是解决了的。

尺寸都是设计像素，落笔前过 `theme.px()`。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Optional

from core.cards import AnalysisDocument, Card

from . import anim, theme
from .widgets import Chip, IndexBadge, ScrollArea, bind_recursive

#: 卡片入场动画的位移量（设计像素）。太大像在「弹」，太小看不出来。
_ENTER_OFFSET = 18
#: 相邻两张卡的入场间隔。整列一起冒出来会显得很吵。
_ENTER_STAGGER_MS = 35


class CardPreview(tk.Frame):
    """一张卡一张卡地往下滚。"""

    def __init__(self, master: tk.Misc, fonts: dict[str, tkfont.Font]) -> None:
        super().__init__(master, background=theme.SURFACE, highlightthickness=0, bd=0)
        self._fonts = fonts
        self._document: Optional[AnalysisDocument] = None
        #: 文字换行宽度，跟着窗格宽度变。
        self._wrap = theme.px(420)
        #: 本次渲染里等待入场的「占位块」，按顺序逐个开始动画。
        self._pending: list[tuple[tk.Frame, int]] = []

        head = tk.Frame(self, background=theme.SURFACE)
        head.pack(
            fill="x", padx=theme.px(theme.PAD_L), pady=(theme.px(theme.PAD_M), theme.px(2))
        )

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
            wraplength=theme.px(520),
            justify="left",
            anchor="w",
        )
        self._summary.pack(
            fill="x", padx=theme.px(theme.PAD_L), pady=(0, theme.px(theme.PAD_M))
        )

        self._scroll = ScrollArea(self, background=theme.SURFACE)
        self._scroll.pack(fill="both", expand=True)
        self._scroll.canvas.bind("<Configure>", self._on_canvas_configure, add="+")

    # -- 对外 ------------------------------------------------------------

    def show(self, document: Optional[AnalysisDocument]) -> None:
        self._document = document
        self._pending.clear()
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
        tk.Frame(
            self._scroll.inner, background=theme.SURFACE, height=theme.px(theme.PAD_L)
        ).pack(fill="x")
        self._scroll.scroll_to_top()
        self._start_enter_animations()

    # -- 入场动画 --------------------------------------------------------

    def _start_enter_animations(self) -> None:
        """卡片一张接一张滑上来。

        做法是在每张卡上方放一个占高度的空 Frame，把它从 `_ENTER_OFFSET`
        压到 0——卡片自己被下面的内容顶着走，视觉上就是「从下面滑上来」。
        直接改卡片的 `pady` 也行，但那样首屏高度会跳，滚动位置也跟着抖。
        """
        pending = list(self._pending)
        self._pending.clear()
        if anim.reduce_motion():
            for spacer, _ in pending:
                self._set_spacer(spacer, 0)
            return

        for order, (spacer, _) in enumerate(pending):
            delay = order * _ENTER_STAGGER_MS
            self.after(delay, lambda s=spacer: self._animate_spacer(s))

    def _animate_spacer(self, spacer: tk.Frame) -> None:
        """占位块从满高压到 0，卡片因此从下方滑上来。

        用 `ease_out_back`：收尾会轻微冲过头再回弹，看起来像「落定」，
        比匀速滑上来有质感。回弹量靠 `_ENTER_OFFSET` 很小，不会真的弹出界。
        """
        if not spacer.winfo_exists():
            return
        full = theme.px(_ENTER_OFFSET)

        def frame(t: float) -> None:
            eased = anim.ease_out_back(t)
            remaining = int(round(full * (1.0 - eased)))
            self._set_spacer(spacer, max(0, remaining))

        anim.animate(spacer, 260, frame, on_done=lambda: self._set_spacer(spacer, 0))

    @staticmethod
    def _set_spacer(spacer: tk.Frame, height: int) -> None:
        if not spacer.winfo_exists():
            return
        spacer.configure(height=max(0, height))

    def _bind_card_hover(self, box: tk.Frame) -> None:
        """鼠标移到卡片上时边框由淡灰渐变成浅蓝。

        预览是只读的，这个高亮不是「可以点」的暗示，只是让人看清自己在
        读哪一张——卡片多的时候眼睛容易串行。

        必须绑到所有子控件（`bind_recursive`）：Tk 把事件先给最深的控件，
        只绑外层的话鼠标压在文字上就收不到 Enter/Leave，高亮会一闪一闪。
        """
        state = {"hover": False}

        def animate_to(target: str) -> None:
            start = box.cget("highlightbackground")
            if start == target:
                return
            if anim.reduce_motion():
                box.configure(highlightbackground=target)
                return

            def frame(t: float) -> None:
                if not box.winfo_exists():
                    return
                box.configure(highlightbackground=anim.lerp_color(start, target, t))

            anim.animate(box, 130, frame, on_done=lambda: box.configure(highlightbackground=target))

        def on_enter(_event: tk.Event) -> None:
            if state["hover"]:
                return
            state["hover"] = True
            animate_to(theme.ACCENT)

        def on_leave(_event: tk.Event) -> None:
            if not state["hover"]:
                return
            state["hover"] = False
            animate_to(theme.BORDER)

        bind_recursive(box, "<Enter>", on_enter)
        bind_recursive(box, "<Leave>", on_leave)

    # -- 内部 ------------------------------------------------------------

    def _render_empty_hint(self) -> None:
        holder = tk.Frame(self._scroll.inner, background=theme.SURFACE)
        holder.pack(fill="both", expand=True, pady=theme.px(60))
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
        # 入场动画用的占位块：先按满高摆着（卡片被推下去），动画过程中压到 0
        spacer = tk.Frame(
            self._scroll.inner, background=theme.SURFACE, height=theme.px(_ENTER_OFFSET)
        )
        spacer.pack(fill="x")

        outer = tk.Frame(self._scroll.inner, background=theme.SURFACE)
        outer.pack(fill="x", padx=theme.px(theme.PAD_L), pady=(0, theme.px(10)))

        card_bg = theme.SURFACE_ALT
        box = tk.Frame(
            outer,
            background=card_bg,
            highlightbackground=theme.BORDER,
            highlightthickness=max(1, theme.px(1)),
        )
        box.pack(fill="x")

        # 鼠标移到卡片上时边框由淡灰渐变成浅蓝。预览是只读的，这个高亮
        # 不是「可以点」的暗示，只是让人看清自己在读哪一张——卡片多的时候
        # 眼睛容易串行。
        self._bind_card_hover(box)

        top = tk.Frame(box, background=card_bg)
        top.pack(fill="x", padx=theme.px(14), pady=(theme.px(12), 0))

        IndexBadge(top, index, self._fonts["small"], parent_background=card_bg).pack(
            side="left", anchor="n", pady=(theme.px(1), 0)
        )

        text_col = tk.Frame(top, background=card_bg)
        text_col.pack(side="left", fill="x", expand=True, padx=(theme.px(10), 0))

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
        chips_row.pack(fill="x", pady=(theme.px(5), 0))

        for bit in meta_bits:
            Chip(
                chips_row,
                bit,
                self._fonts["small"],
                foreground=theme.TEXT_SOFT,
                background=theme.SURFACE,
                parent_background=card_bg,
            ).pack(side="left", padx=(0, theme.px(5)))

        for tag in card.tags[:5]:
            Chip(
                chips_row,
                tag,
                self._fonts["small"],
                foreground=theme.ACCENT_DARK,
                background=theme.ACCENT_SOFT,
                parent_background=card_bg,
            ).pack(side="left", padx=(0, theme.px(5)))

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
        answer.pack(fill="x", padx=theme.px(14), pady=(theme.px(9), 0))

        if card.detail:
            tk.Frame(box, background=theme.BORDER, height=max(1, theme.px(1))).pack(
                fill="x", padx=theme.px(14), pady=(theme.px(9), 0)
            )
            tk.Label(
                box,
                text=card.detail,
                background=card_bg,
                foreground=theme.MUTED,
                font=self._fonts["small"],
                wraplength=self._wrap,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=theme.px(14), pady=(theme.px(7), 0))

        tk.Frame(box, background=card_bg, height=theme.px(12)).pack(fill="x")

        self._pending.append((spacer, index))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # 换行宽度跟着窗格走。减掉的常量是卡片左右内边距 + 序号徽章宽度。
        # 给不够的话最后几个字会被卡片边框切掉。
        wrap = max(theme.px(200), event.width - theme.px(108))
        if abs(wrap - self._wrap) <= theme.px(8):
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
