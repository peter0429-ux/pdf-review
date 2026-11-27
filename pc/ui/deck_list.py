"""左边那一列牌组列表。

用自绘的行而不是 `ttk.Treeview`：Treeview 的行高、选中色、字体都能改，
但选中时那整条蓝色（`vista` 主题下还会带上系统高亮）跟这套配色冲突，
而且它不支持「左边一条竖线表示选中」这种标记。一屏最多几十个牌组，
逐个画 Frame 的开销可以忽略。

所有尺寸都是设计像素，落笔前过 `theme.px()`。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable, Optional

from core.project import DeckEntry

from . import anim, theme
from .widgets import ScrollArea, bind_recursive


class DeckRow(tk.Frame):
    """一行：选中竖条 + 标题 + 「N 张 · 时间」。"""

    def __init__(
        self,
        master: tk.Misc,
        entry: DeckEntry,
        fonts: dict[str, tkfont.Font],
        on_click: Callable[[], None],
        on_double_click: Callable[[], None],
    ) -> None:
        super().__init__(
            master, background=theme.SURFACE, height=theme.px(theme.ROW_HEIGHT)
        )
        self.pack_propagate(False)

        self._entry = entry
        self._on_click = on_click
        self._on_double_click = on_double_click
        self._selected = False
        self._hover = False
        #: 当前背景色（动画过程中的中间值）。选中/悬停前先用它画，
        #: 动画再把它推过去。
        self._background = theme.SURFACE

        # 选中标记：左边一条竖线。没选中时也占位（画成底色），
        # 这样切换时文字不会左右挪一下。
        self._marker = tk.Frame(
            self, width=theme.px(3), background=theme.SURFACE
        )
        self._marker.pack(side="left", fill="y")

        body = tk.Frame(self, background=theme.SURFACE)
        body.pack(
            side="left",
            fill="both",
            expand=True,
            padx=(theme.px(10), theme.px(12)),
            pady=theme.px(5),
        )
        self._body = body

        self._title_label = tk.Label(
            body,
            text=entry.meta.title or entry.folder.name,
            background=theme.SURFACE,
            foreground=theme.TEXT,
            font=fonts["body_bold"],
            anchor="w",
            justify="left",
        )
        self._title_label.pack(fill="x")

        meta = self._meta_text(entry)
        self._meta_label = tk.Label(
            body,
            text=meta,
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=fonts["small"],
            anchor="w",
        )
        self._meta_label.pack(fill="x", pady=(theme.px(1), 0))

        bind_recursive(self, "<Enter>", self._on_enter)
        bind_recursive(self, "<Leave>", self._on_leave)
        bind_recursive(self, "<Button-1>", self._on_press)
        bind_recursive(self, "<Double-Button-1>", self._on_double)

    # -- 对外 ------------------------------------------------------------

    @property
    def entry(self) -> DeckEntry:
        return self._entry

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self._repaint()

    # -- 内部 ------------------------------------------------------------

    @staticmethod
    def _meta_text(entry: DeckEntry) -> str:
        stamp = entry.meta.updated_at.replace("T", " ")[:16] if entry.meta.updated_at else "—"
        return f"{entry.card_count} 张  ·  {stamp}"

    def _target(self) -> tuple[str, str]:
        """当前状态该有的 (背景色, 竖条色)。"""
        if self._selected:
            return theme.SELECTED, theme.ACCENT
        if self._hover:
            return theme.HOVER, theme.HOVER
        return theme.SURFACE, theme.SURFACE

    def _repaint(self) -> None:
        target, marker = self._target()
        if target == self._background or anim.reduce_motion():
            self._background = target
            self._apply(target, marker)
            return

        start = self._background

        def frame(t: float) -> None:
            self._apply(anim.lerp_color(start, target, t), marker)

        def done() -> None:
            self._background = target
            self._apply(target, marker)

        anim.animate(self, 110, frame, on_done=done)

    def _apply(self, background: str, marker: str) -> None:
        for widget in (self, self._body, self._title_label, self._meta_label):
            widget.configure(background=background)
        self._marker.configure(background=marker)
        self._title_label.configure(
            foreground=theme.ACCENT_DARK if self._selected else theme.TEXT
        )

    # -- 事件 ------------------------------------------------------------

    def _on_enter(self, _event: tk.Event) -> None:
        if self._selected:
            return
        self._hover = True
        self._repaint()

    def _on_leave(self, _event: tk.Event) -> None:
        if not self._hover:
            return
        self._hover = False
        self._repaint()

    def _on_press(self, _event: tk.Event) -> None:
        self._on_click()

    def _on_double(self, _event: tk.Event) -> None:
        # 双击也会先触发单击，所以选中已经发生过了；这里只补导出。
        self._on_double_click()


class DeckList(tk.Frame):
    """滚动区 + 若干 `DeckRow`。选中态由外面控制（`select`）。"""

    def __init__(
        self,
        master: tk.Misc,
        fonts: dict[str, tkfont.Font],
        on_select: Callable[[Optional[DeckEntry]], None],
        on_export: Callable[[DeckEntry], None],
    ) -> None:
        super().__init__(master, background=theme.SURFACE, highlightthickness=0, bd=0)

        self._fonts = fonts
        self._on_select = on_select
        self._on_export = on_export
        self._rows: dict[str, DeckRow] = {}
        self._selected: Optional[str] = None
        self._entries: list[DeckEntry] = []

        # 顶部小标题：让「这是一列牌组」这件事明确，也顺便把高度撑开一点
        head = tk.Frame(self, background=theme.SURFACE)
        head.pack(
            fill="x", padx=theme.px(14), pady=(theme.px(10), theme.px(6))
        )
        tk.Label(
            head,
            text="牌组",
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=fonts["small"],
            anchor="w",
        ).pack(side="left")
        self._count_label = tk.Label(
            head,
            text="",
            background=theme.SURFACE,
            foreground=theme.MUTED,
            font=fonts["small"],
        )
        self._count_label.pack(side="right")

        self._scroll = ScrollArea(self, background=theme.SURFACE)
        self._scroll.pack(fill="both", expand=True)

    # -- 对外 ------------------------------------------------------------

    def set_entries(self, entries: list[DeckEntry], keep: Optional[Path]) -> Optional[DeckEntry]:
        """重建列表，尽量保住原来选中的那个。返回最终选中的项。"""
        self._scroll.clear()
        self._rows.clear()
        self._entries = entries
        self._count_label.configure(text=f"{len(entries)} 个")

        for entry in entries:
            key = str(entry.folder)
            row = DeckRow(
                self._scroll.inner,
                entry,
                self._fonts,
                on_click=lambda k=key: self._click(k),
                on_double_click=lambda k=key: self._double(k),
            )
            row.pack(fill="x")
            self._rows[key] = row

        target: Optional[str] = None
        if keep is not None and str(keep) in self._rows:
            target = str(keep)
        elif entries:
            target = str(entries[0].folder)

        self.select(target)
        return self.selected_entry

    def select(self, key: Optional[str]) -> None:
        if key == self._selected:
            # 仍然要把回调走一遍：重建列表后外部需要重新载入文档
            self._on_select(self.selected_entry)
            return

        old = self._rows.get(self._selected or "")
        if old is not None:
            old.set_selected(False)

        self._selected = key
        new = self._rows.get(key or "")
        if new is not None:
            new.set_selected(True)

        self._on_select(self.selected_entry)

    @property
    def selected_entry(self) -> Optional[DeckEntry]:
        if self._selected is None:
            return None
        row = self._rows.get(self._selected)
        return row.entry if row is not None else None

    @property
    def count(self) -> int:
        return len(self._entries)

    # -- 事件 ------------------------------------------------------------

    def _click(self, key: str) -> None:
        self.select(key)

    def _double(self, key: str) -> None:
        row = self._rows.get(key)
        if row is not None:
            self._on_export(row.entry)
