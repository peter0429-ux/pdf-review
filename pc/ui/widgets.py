"""自绘的小控件。

ttk 在 Windows 上只有 `vista` 一套像样的主题，而它把背景色、边框、圆角
全锁死了——改 style 也不生效（试过，`vista` 会覆盖回去）。想要圆角按钮、
卡片行、标签胶囊这类形状，只能自己用 Canvas 画。

这个文件里都是「画出来」的控件，没有业务含义。它们对外只暴露很少的方法，
免得把 Tk 的细节漏到界面代码里。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable, Optional

from . import theme


def round_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    **kwargs: object,
) -> int:
    """在 Canvas 上画一个圆角矩形，返回 item id。

    Tk 没有原生圆角矩形。用多边形 + `smooth=True` 是常见做法：把每个角
    拆成两个点，样条会把拐角磨圆。半径给到超过半宽时会被夹住，不会画歪。
    """
    r = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def bind_recursive(widget: tk.Misc, sequence: str, callback: Callable) -> None:
    """把事件绑到 widget 和它所有子控件上。

    Tk 里事件先给最深的那个控件。一行卡片由好几个 Label 拼成，只绑外层
    的话鼠标压在文字上就收不到 Enter/Leave，悬停效果会一闪一闪。
    """
    widget.bind(sequence, callback)
    for child in widget.winfo_children():
        bind_recursive(child, sequence, callback)


class ScrollArea(tk.Frame):
    """带细滚动条的纵向滚动区。往 `.inner` 里塞内容。

    滚轮用 `bind_all` 注册，但每个实例都先判断指针是不是真在自己身上。
    不这么做的话，左边列表和右边预览会一起滚——用户滚的是列表，预览
    却在背后动，很难受。
    """

    def __init__(self, master: tk.Misc, background: str = theme.SURFACE) -> None:
        super().__init__(master, background=background, highlightthickness=0, bd=0)

        self._bg = background
        # width/height 给的是「最小请求尺寸」，真正的尺寸由 pack 决定。
        # 不给的话 Canvas 默认 378 宽，会把窗格撑得比窗口还宽。
        self.canvas = tk.Canvas(
            self, background=background, highlightthickness=0, bd=0, width=80, height=80
        )
        self._bar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview, style="Vertical.TScrollbar"
        )
        self.canvas.configure(yscrollcommand=self._bar.set)

        self._bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, background=background)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

        #: 是否正在显示滚动条。内容装得下时藏起来——clam 主题的滚动条在
        #: 不需要滚动时滑块会占满整条槽，变成一道常驻的灰色竖杠，很难看。
        self._bar_visible = True

    # -- 对外 ------------------------------------------------------------

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0)

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()

    # -- 内部 ------------------------------------------------------------

    def _sync_bar(self) -> None:
        first, last = self.canvas.yview()
        needed = not (first <= 0.0 and last >= 1.0)
        if needed == self._bar_visible:
            return
        self._bar_visible = needed
        if needed:
            self._bar.pack(side="right", fill="y")
        else:
            self._bar.pack_forget()

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_bar()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        # 内层跟着画布一起变宽，否则卡片只占左边一半
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync_bar()

    def _on_wheel(self, event: tk.Event) -> None:
        widget = self.canvas.winfo_containing(event.x_root, event.y_root)
        probe = widget
        while probe is not None:
            if probe is self.canvas or probe is self.inner:
                break
            probe = getattr(probe, "master", None)
        else:
            return

        if not event.delta:
            return
        # Windows 一格是 120；高精度触控板会给更小的值，这里最多滚 3 行，
        # 否则轻轻一划就飞到底。
        steps = int(-event.delta / 120) or (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(max(-3, min(3, steps)), "units")


class RoundedButton(tk.Canvas):
    """圆角按钮。四种样式：primary / secondary / danger / ghost。

    ttk.Button 在 clam 主题下是方的、灰的；在 vista 主题下不接受自定义
    颜色。想让「新建牌组」看起来像主操作，只能自己画。
    """

    _PADDING_X = 14

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], None],
        fonts: dict[str, tkfont.Font],
        variant: str = "secondary",
        width: Optional[int] = None,
        height: int = theme.BUTTON_HEIGHT,
        background: str = theme.BG,
    ) -> None:
        self._font = fonts["body"]
        self._text = text
        self._command = command
        self._variant = variant
        self._enabled = True
        self._hover = False
        self._pressed = False
        self._background = background

        measured = self._font.measure(text) + self._PADDING_X * 2
        super().__init__(
            master,
            width=width or measured,
            height=height,
            background=background,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )

        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # -- 对外 ------------------------------------------------------------

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self.configure(width=self._font.measure(text) + self._PADDING_X * 2)
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def set_variant(self, variant: str) -> None:
        if variant == self._variant:
            return
        self._variant = variant
        self._draw()

    # -- 外观 ------------------------------------------------------------

    def _palette(self) -> tuple[str, str, str, str]:
        """返回 (填充, 边框, 文字, 悬停时的填充)。"""
        disabled = not self._enabled
        if self._variant == "primary":
            if disabled:
                return theme.ACCENT_SOFT, theme.ACCENT_SOFT, "#9DAEE0", theme.ACCENT_SOFT
            fill = theme.ACCENT_DARK if self._pressed else (theme.ACCENT_DARK if self._hover else theme.ACCENT)
            return fill, fill, "#FFFFFF", fill
        if self._variant == "danger":
            if disabled:
                return self._background, self._background, "#CDB4B0", self._background
            fill = theme.ERROR_SOFT if self._hover else self._background
            return fill, fill, theme.ERROR, fill
        if self._variant == "ghost":
            if disabled:
                return self._background, self._background, "#BFC4CF", self._background
            fill = theme.HOVER if self._hover else self._background
            return fill, fill, theme.TEXT_SOFT, fill
        # secondary
        if disabled:
            return theme.SURFACE_ALT, theme.BORDER, "#BFC4CF", theme.SURFACE_ALT
        fill = theme.HOVER if self._hover else theme.SURFACE
        return fill, theme.BORDER_STRONG, theme.TEXT, fill

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width() or int(self["width"])
        height = self.winfo_height() or int(self["height"])
        if width <= 1 or height <= 1:
            return

        fill, outline, text_color, _ = self._palette()
        round_rect(self, 1, 1, width - 1, height - 1, 7, fill=fill, outline=outline, width=1)
        self.create_text(
            width / 2,
            height / 2 + 1,
            text=self._text,
            fill=text_color,
            font=self._font,
        )

    # -- 事件 ------------------------------------------------------------

    def _on_enter(self, _event: tk.Event) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event: tk.Event) -> None:
        if not self._enabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _event: tk.Event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if self._enabled and was_pressed:
            self._command()


class Chip(tk.Canvas):
    """标签胶囊。宽度按文字算，高度固定。"""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        font: tkfont.Font,
        foreground: str = theme.TEXT_SOFT,
        background: str = theme.SURFACE_ALT,
        parent_background: str = theme.SURFACE,
        height: int = 21,
    ) -> None:
        self._font = font
        self._text = text
        width = font.measure(text) + 16
        super().__init__(
            master,
            width=width,
            height=height,
            background=parent_background,
            highlightthickness=0,
            bd=0,
        )
        self._foreground = foreground
        self._chip_background = background
        self._height = height
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width() or int(self["width"])
        height = self.winfo_height() or self._height
        if width <= 1:
            return
        round_rect(
            self,
            0.5,
            0.5,
            width - 0.5,
            height - 0.5,
            height / 2,
            fill=self._chip_background,
            outline=self._chip_background,
        )
        self.create_text(width / 2, height / 2 + 1, text=self._text, fill=self._foreground, font=self._font)


class IndexBadge(tk.Canvas):
    """卡片前的圆形序号。"""

    def __init__(
        self,
        master: tk.Misc,
        number: int,
        font: tkfont.Font,
        parent_background: str = theme.SURFACE,
        size: int = 24,
    ) -> None:
        super().__init__(
            master,
            width=size,
            height=size,
            background=parent_background,
            highlightthickness=0,
            bd=0,
        )
        self._number = number
        self._font = font
        self._size = size
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        size = self.winfo_width() or self._size
        if size <= 1:
            return
        self.create_oval(0.5, 0.5, size - 0.5, size - 0.5, fill=theme.ACCENT_SOFT, outline="")
        self.create_text(
            size / 2,
            size / 2 + 1,
            text=str(self._number),
            fill=theme.ACCENT,
            font=self._font,
        )


class Divider(tk.Frame):
    """一条淡分隔线。Tk 的 Separator 在 clam 下是凹槽，看着脏。"""

    def __init__(self, master: tk.Misc, background: str = theme.BORDER) -> None:
        super().__init__(master, background=background, height=1, bd=0, highlightthickness=0)
