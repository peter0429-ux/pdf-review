"""界面常量：字体、配色、间距。

集中在一处是因为 Windows 上 Tk 的默认外观太老，用户第一眼就会觉得
「这是十年前的程序」。改这几十个数字比在每个控件上写一遍可靠。

配色取的是偏中性的深色文字 + 一个蓝色主色，跟 iOS 版的观感靠拢，
但不追求像素级一致——两个平台的控件本来就不一样，硬凑只会两头不像。
"""

from __future__ import annotations

import tkinter.font as tkfont
from typing import Any

# -- 颜色 ---------------------------------------------------------------

BG = "#F5F5F7"          # 窗口底色，比纯白柔和
SURFACE = "#FFFFFF"     # 卡片、列表
BORDER = "#D8D8DE"
TEXT = "#1D1D1F"
MUTED = "#6E6E73"
ACCENT = "#0A84FF"
ACCENT_DARK = "#0066CC"
WARN = "#C77700"
ERROR = "#C0392B"
SUCCESS = "#1E7B34"

# -- 间距 ---------------------------------------------------------------

PAD_XS = 4
PAD_S = 8
PAD_M = 12
PAD_L = 20
PAD_XL = 32

# -- 字体 ---------------------------------------------------------------

#: 界面用的字号。Windows 默认缩放 100% 时 9pt 偏小，10 比较舒服。
BODY_SIZE = 10
SMALL_SIZE = 9
TITLE_SIZE = 16
HEADING_SIZE = 12


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
        "body": tkfont.Font(root=root, family=family, size=BODY_SIZE),
        "small": tkfont.Font(root=root, family=family, size=SMALL_SIZE),
        "title": tkfont.Font(root=root, family=family, size=TITLE_SIZE, weight="bold"),
        "heading": tkfont.Font(root=root, family=family, size=HEADING_SIZE, weight="bold"),
        "mono": tkfont.Font(root=root, family="Consolas", size=SMALL_SIZE),
    }


def apply_theme(root: Any) -> dict[str, tkfont.Font]:
    """把配色与字体套到 ttk 上，返回字体表供各视图复用。"""
    from tkinter import ttk

    fonts = load_fonts(root)
    style = ttk.Style(root)

    # 'vista' 在 Windows 上可用，比默认的 'xpnative' 更接近现代观感。
    # 万一跑在别的系统上（或老 Windows），别抛错，用默认主题继续。
    if "vista" in style.theme_names():
        style.theme_use("vista")

    root.configure(background=BG)

    style.configure("TFrame", background=BG)
    style.configure("Surface.TFrame", background=SURFACE)

    style.configure("TLabel", background=BG, foreground=TEXT, font=fonts["body"])
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=fonts["small"])
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=fonts["title"])
    style.configure("Heading.TLabel", background=BG, foreground=TEXT, font=fonts["heading"])
    style.configure("Error.TLabel", background=BG, foreground=ERROR, font=fonts["body"])
    style.configure("Warn.TLabel", background=BG, foreground=WARN, font=fonts["small"])
    style.configure("Success.TLabel", background=BG, foreground=SUCCESS, font=fonts["body"])

    style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT, font=fonts["body"])
    style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED, font=fonts["small"])

    style.configure("TButton", font=fonts["body"], padding=(PAD_M, PAD_XS + 2))
    style.configure("Accent.TButton", font=fonts["body"], padding=(PAD_M, PAD_XS + 2))

    style.configure("TEntry", font=fonts["body"], padding=PAD_XS)
    style.configure("TCombobox", font=fonts["body"])

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        font=fonts["body"],
        rowheight=28,
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        font=fonts["small"],
        background=BG,
        foreground=MUTED,
        relief="flat",
        padding=(PAD_S, PAD_XS + 2),
    )
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#FFFFFF")])

    style.configure("TLabelframe", background=BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=fonts["small"])

    style.configure(
        "Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor="#E4E4E9",
        borderwidth=0,
        thickness=8,
    )

    return fonts
