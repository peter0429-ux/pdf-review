"""右侧的卡片预览。

只读。要改卡片请回 iOS 版——PC 版的定位是「批量生产 + 导出」，
在这里做编辑器会引出「改了一半直接导出」的责任问题，而这个问题
在手机上本来就是解决了的。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Optional

from core.cards import AnalysisDocument, Card

from . import theme


class CardPreview(ttk.Frame):
    """一张卡一张卡地往下滚。"""

    def __init__(self, master: tk.Misc, fonts: dict[str, tkfont.Font]) -> None:
        super().__init__(master, style="Surface.TFrame")
        self._fonts = fonts
        self._document: Optional[AnalysisDocument] = None

        # 顶部一行：牌组名 + 张数
        head = ttk.Frame(self, style="Surface.TFrame")
        head.pack(fill="x", padx=theme.PAD_M, pady=(theme.PAD_M, theme.PAD_S))
        self._title = ttk.Label(head, text="还没有选择牌组", style="Surface.TLabel", font=fonts["heading"])
        self._title.pack(side="left")
        self._count = ttk.Label(head, text="", style="SurfaceMuted.TLabel")
        self._count.pack(side="right")

        self._summary = ttk.Label(
            self,
            text="",
            style="SurfaceMuted.TLabel",
            wraplength=520,
            justify="left",
        )
        self._summary.pack(fill="x", padx=theme.PAD_M, pady=(0, theme.PAD_S))

        # 卡片区：Canvas + 内嵌 Frame + 纵向滚动条
        body = ttk.Frame(self, style="Surface.TFrame")
        body.pack(fill="both", expand=True)

        # width 给一个小值：Canvas 的默认请求宽度是 378，会把这个窗格撑得比
        # 窗口还宽，结果右边一截被裁掉。窗格的真实宽度由 PanedWindow 分配。
        self._canvas = tk.Canvas(
            body, background=theme.SURFACE, highlightthickness=0, width=320, height=200
        )
        scroll = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scroll.set)

        scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, background=theme.SURFACE)
        self._window = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        #: 文字换行宽度。跟着窗格宽度走，否则窗格变窄时文字会被裁掉。
        self._wrap = 420

        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # 滚轮：Windows 用 delta/120，Linux 用 Button-4/5。两种都接上，
        # 免得换台机器就发现「滚不动」。
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    # -- 对外 ------------------------------------------------------------

    def show(self, document: Optional[AnalysisDocument]) -> None:
        self._document = document
        self._clear()

        if document is None:
            self._title.configure(text="还没有选择牌组")
            self._count.configure(text="")
            self._summary.configure(text="左边选一个牌组看看内容。")
            return

        self._title.configure(text=document.deck.title)
        self._count.configure(text=f"{len(document.cards)} 张卡片")
        self._summary.configure(text=document.deck.summary or "")

        for index, card in enumerate(document.cards, start=1):
            self._render_card(index, card)

        self._canvas.yview_moveto(0)

    # -- 内部 ------------------------------------------------------------

    def _clear(self) -> None:
        for child in self._inner.winfo_children():
            child.destroy()

    def _render_card(self, index: int, card: Card) -> None:
        box = tk.Frame(
            self._inner,
            background="#FAFAFC",
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        box.pack(fill="x", padx=theme.PAD_M, pady=(0, theme.PAD_S))

        top = tk.Frame(box, background="#FAFAFC")
        top.pack(fill="x", padx=theme.PAD_M, pady=(theme.PAD_S, 0))

        tk.Label(
            top,
            text=f"{index}",
            background="#FAFAFC",
            foreground=theme.MUTED,
            font=self._fonts["small"],
            width=3,
            anchor="w",
        ).pack(side="left")

        question = tk.Label(
            top,
            text=card.question,
            background="#FAFAFC",
            foreground=theme.TEXT,
            font=self._fonts["body"],
            wraplength=self._wrap,
            justify="left",
            anchor="w",
        )
        question.pack(side="left", fill="x", expand=True)

        meta_bits: list[str] = []
        if card.source_page:
            meta_bits.append(f"第 {card.source_page} 页")
        if card.tags:
            meta_bits.append("、".join(card.tags[:4]))
        if meta_bits:
            tk.Label(
                box,
                text="  ".join(meta_bits),
                background="#FAFAFC",
                foreground=theme.MUTED,
                font=self._fonts["small"],
                anchor="w",
            ).pack(fill="x", padx=theme.PAD_M, pady=(2, 0))

        tk.Label(
            box,
            text=card.answer,
            background="#FAFAFC",
            foreground=theme.TEXT,
            font=self._fonts["body"],
            wraplength=self._wrap,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=theme.PAD_M, pady=(4, 0))

        if card.detail:
            tk.Label(
                box,
                text=card.detail,
                background="#FAFAFC",
                foreground=theme.MUTED,
                font=self._fonts["small"],
                wraplength=self._wrap,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=theme.PAD_M, pady=(2, 0))

        tk.Frame(box, background="#FAFAFC", height=theme.PAD_S).pack(fill="x")

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # 让内嵌 frame 跟着画布变宽，否则卡片只有一半宽
        self._canvas.itemconfigure(self._window, width=event.width)

        # 换行宽度跟着变。减去的常量是卡片的内边距（左 12 + 序号列 3 字宽
        # + 右边距），不给够的话最后几个字会被卡片边框切掉。
        wrap = max(200, event.width - 90)
        if abs(wrap - self._wrap) > 8:
            self._wrap = wrap
            self._reflow()

    def _reflow(self) -> None:
        """按新的换行宽度重排文字。

        Tk 的 Label 不支持「宽度变了自动重算换行」，只能改 wraplength 再
        让几何管理器重算。逐个子控件找一遍比记录每个 Label 的引用简单，
        而且卡片数量本来就不多（一屏十几张）。
        """
        for card_box in self._inner.winfo_children():
            for child in card_box.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(wraplength=self._wrap)
                elif isinstance(child, tk.Frame):
                    for sub in child.winfo_children():
                        if isinstance(sub, tk.Label):
                            sub.configure(wraplength=self._wrap)

    def _on_wheel(self, event: tk.Event) -> None:
        # 只有指针真的在这个控件上时才滚，否则会抢别的滚动区的滚轮
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return
        target = widget
        while target is not None:
            if target is self:
                break
            target = getattr(target, "master", None)
        else:
            return

        if event.delta:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")
        elif getattr(event, "num", None) == 4:
            self._canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self._canvas.yview_scroll(1, "units")
