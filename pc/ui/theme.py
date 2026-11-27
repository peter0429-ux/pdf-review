"""界面常量：配色、间距、字体。

集中在一处是因为 Windows 上 Tk 的默认外观太老，用户第一眼就会觉得
「这是十年前的程序」。

配色是一套中性灰 + 单一蓝色主色。灰阶分得比一般 Tk 程序细，因为界面里
层次一多（窗口底 / 面板 / 面板里的次级块 / 悬停 / 选中 / 边框），只有两三
档灰就会糊成一片，看着「脏」。
"""

from __future__ import annotations

import tkinter.font as tkfont
from typing import Any

# -- 颜色 ---------------------------------------------------------------
# 灰阶由浅到深：BG 是窗口底，SURFACE 是面板，SURFACE_ALT 是面板里的次级块。
BG = "#EEF1F6"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F6F7FA"
HOVER = "#F1F3F8"
SELECTED = "#E9F1FF"

BORDER = "#E3E6ED"
BORDER_STRONG = "#CFD4DE"

TEXT = "#15171C"
TEXT_SOFT = "#424857"
MUTED = "#8B92A3"

ACCENT = "#2F6BFF"
ACCENT_DARK = "#1F55D8"
ACCENT_SOFT = "#EAF0FF"

WARN = "#B26A00"
WARN_SOFT = "#FFF4E3"
ERROR = "#C0392B"
ERROR_SOFT = "#FDECEA"
SUCCESS = "#16794C"
SUCCESS_SOFT = "#E7F6EE"

#: 卡片底下那层「影子」。Tk 没有真阴影，用一层比底色深一点的边框模拟
#: 一个像素的落差，比纯描边看着轻。
SHADOW = "#E7EAF1"

# -- 间距 ---------------------------------------------------------------

PAD_XS = 4
PAD_S = 8
PAD_M = 12
PAD_L = 18
PAD_XL = 28

# -- 缩放 ---------------------------------------------------------------

#: 屏幕缩放系数。下面的间距、行高、圆角半径都是「100% 屏幕下的设计像素」，
#: 实际取值一律过一遍 `px()`。
#:
#: 为什么必须有这个：一旦声明了 DPI 感知（`dpi.py`），Tk 的字体按点数会
#: 自动放大（10pt 在 150% 屏上变成 20 物理像素），但 `padding=12` 这类
#: 整数永远是 12 物理像素。不缩放的话字变大了、间距没变，界面会挤成一团。
SCALE: float = 1.0


def init_scale(root: Any) -> float:
    """量出屏幕缩放系数并记下来。必须在建任何控件之前调用。

    `winfo_fpixels("1i")` 返回「一英寸有多少像素」。DPI 感知打开后，
    150% 缩放下这个值是 144；未声明 DPI 感知时永远是 96（系统在窗口
    外面偷偷拉伸）。所以它同时也是一把「DPI 感知生效了没」的尺子。
    """
    global SCALE
    try:
        ppi = float(root.winfo_fpixels("1i"))
    except Exception:  # noqa: BLE001
        ppi = 96.0
    SCALE = max(1.0, ppi / 96.0)
    return SCALE


def px(value: float) -> int:
    """把设计像素换算成当前屏幕的实际像素。"""
    return int(round(value * SCALE))


# -- 字号 ---------------------------------------------------------------

H1_SIZE = 19
H2_SIZE = 13
BODY_SIZE = 10
SMALL_SIZE = 9

#: 列表行高、按钮高度。集中在这里是因为自绘控件要拿它算坐标。
ROW_HEIGHT = 58
BUTTON_HEIGHT = 34


def load_fonts(root: Any) -> dict[str, tkfont.Font]:
    """按当前系统可用的字体族，挑一套出来。

    「微软雅黑」在中文 Windows 上一定有；英文 Windows 上没有，就退回
    Tk 默认。写死一个名字而它在对方机器上不存在时，Tk 会静默换字体，
    字号和行高全跟着变，排版会散。
    """
    families = set(tkfont.families(root))
    for candidate in ("微软雅黑", "Microsoft YaHei UI", "Microsoft YaHei"):
        if candidate in families:
            family = candidate
            break
    else:
        family = tkfont.nametofont("TkDefaultFont").actual("family")

    return {
        "h1": tkfont.Font(root=root, family=family, size=H1_SIZE, weight="bold"),
        "h2": tkfont.Font(root=root, family=family, size=H2_SIZE, weight="bold"),
        "body": tkfont.Font(root=root, family=family, size=BODY_SIZE),
        "body_bold": tkfont.Font(root=root, family=family, size=BODY_SIZE, weight="bold"),
        "small": tkfont.Font(root=root, family=family, size=SMALL_SIZE),
        "mono": tkfont.Font(root=root, family="Consolas", size=SMALL_SIZE),
        # 下面三个是为了兼容早先按 title/heading 取字体的调用点。
        "title": tkfont.Font(root=root, family=family, size=H1_SIZE, weight="bold"),
        "heading": tkfont.Font(root=root, family=family, size=H2_SIZE, weight="bold"),
    }


def apply_theme(root: Any) -> dict[str, tkfont.Font]:
    """把配色与字体套到还要用的几个 ttk 控件上，返回字体表。

    界面主体是自绘的 `tk` 控件（见 `widgets.py`），ttk 只剩滚动条、下拉框、
    数字框、进度条这几样没有原生替代的。它们必须用 `clam` 主题——`vista`
    主题会把背景色、边框色统统接管，改了也不生效。
    """
    from tkinter import ttk

    # 先量缩放，再建字体：字体按点数走，缩放系数由 Tk 自己管；间距是
    # 物理像素，必须我们手动乘。顺序反了的话第一帧会按 100% 排好再跳一下。
    init_scale(root)
    fonts = load_fonts(root)

    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(background=BG)

    # 滚动条：细、无箭头、悬停加深。默认那条带上下箭头的老式滚动条是
    # 整个界面里最「Windows 98」的一处。
    style.layout(
        "Vertical.TScrollbar",
        [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
        ]})],
    )
    style.configure(
        "Vertical.TScrollbar",
        gripcount=0,
        background=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        troughcolor=SURFACE,
        bordercolor=SURFACE,
        arrowcolor=SURFACE,
        relief="flat",
        width=px(9),
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", MUTED), ("pressed", MUTED)],
        darkcolor=[("active", MUTED)],
        lightcolor=[("active", MUTED)],
    )

    style.configure("TEntry", padding=px(6), fieldbackground=SURFACE)
    style.configure("TCombobox", font=fonts["body"], padding=px(4))
    style.configure("TSpinbox", font=fonts["body"], padding=px(4))
    style.configure(
        "Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor=BG,
        bordercolor=BG,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        borderwidth=0,
        thickness=px(6),
    )

    return fonts
