"""主窗口：左边牌组列表，右边卡片预览，上面一排按钮。

布局用 `tk.PanedWindow` 而不是 grid 固定比例——用户会想拖一下分隔条，
尤其是牌组名很长的时候。

顶栏、列表、预览各自是独立的小控件（`deck_list.py` / `preview.py`），
这里只负责把它们拼起来、把事件转给业务层。

所有尺寸都是设计像素，落笔前过 `theme.px()`。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

from core import export as export_mod
from core import settings as settings_mod
from core.cards import AnalysisDocument
from core.project import DeckEntry, DeckStore

from . import anim, dpi, theme
from .analyze_dialog import AnalyzeDialog
from .deck_list import DeckList
from .preview import CardPreview
from .settings_dialog import SettingsDialog
from .widgets import Divider, RoundedButton, round_rect


class MainWindow(tk.Frame):
    """整个程序的主界面。

    `settings` 与 `store` 可以从外面传进来。默认从磁盘读——但这两个参数
    让「指向别的工作区试一下」和「测试里用临时目录」都不必去碰用户真实数据。
    """

    def __init__(
        self,
        master: tk.Tk,
        fonts: dict[str, tkfont.Font],
        settings: Optional[settings_mod.Settings] = None,
        store: Optional[DeckStore] = None,
    ) -> None:
        super().__init__(master, background=theme.BG)
        self.pack(fill="both", expand=True)

        self._fonts = fonts
        self._settings = settings if settings is not None else settings_mod.load_settings()
        self._store = store if store is not None else DeckStore()
        # 只有「设置是从磁盘读的」才自动弹配置窗口。外面明确传进来一份设置时
        # 不弹——那通常意味着调用方已经安排好了，弹窗会打断它（测试里更会直接挂住）。
        self._auto_open_settings = settings is None
        self._current_document: Optional[AnalysisDocument] = None

        self._build()
        self.refresh()

        if self._auto_open_settings and not self._settings.is_configured:
            # 第一次启动：直接开设置，省得用户乱点一圈才发现没配 key
            self.after(120, self._on_settings)

    # -- 构建 ------------------------------------------------------------

    def _build(self) -> None:
        self._build_header()

        Divider(self, background=theme.BORDER).pack(fill="x")

        body = tk.Frame(self, background=theme.BG)
        body.pack(fill="both", expand=True)

        panes = tk.PanedWindow(
            body,
            orient="horizontal",
            background=theme.BG,
            sashwidth=theme.px(10),
            sashrelief="flat",
            bd=0,
        )
        panes.pack(
            fill="both",
            expand=True,
            padx=theme.px(theme.PAD_L),
            pady=(theme.px(theme.PAD_M), 0),
        )

        left_card = _panel(panes)
        panes.add(
            left_card,
            minsize=theme.px(230),
            width=theme.px(330),
            stretch="always",
        )

        right_card = _panel(panes)
        panes.add(right_card, minsize=theme.px(360), stretch="always")

        self._list = DeckList(
            left_card.inner,  # type: ignore[attr-defined]
            self._fonts,
            on_select=self._on_select,
            on_export=self._export_entry,
        )
        self._list.pack(fill="both", expand=True)

        self._preview = CardPreview(right_card.inner, self._fonts)  # type: ignore[attr-defined]
        self._preview.pack(fill="both", expand=True)

        self._build_footer()

    def _build_header(self) -> None:
        header = tk.Frame(self, background=theme.BG)
        header.pack(
            fill="x",
            padx=theme.px(theme.PAD_L),
            pady=(theme.px(theme.PAD_M), theme.px(theme.PAD_M)),
        )

        brand = tk.Frame(header, background=theme.BG)
        brand.pack(side="left")

        # 标题左边放一个小小的圆角方块当 logo，纯装饰。
        logo = theme.px(26)
        mark = tk.Canvas(
            brand,
            width=logo,
            height=logo,
            background=theme.BG,
            highlightthickness=0,
            bd=0,
        )
        mark.pack(side="left", padx=(0, theme.px(9)))
        round_rect(mark, 0, 0, logo, logo, theme.px(8), fill=theme.ACCENT, outline=theme.ACCENT)
        mark.create_text(logo / 2, logo / 2 + 1, text="R", fill="#FFFFFF", font=self._fonts["body_bold"])

        titles = tk.Frame(brand, background=theme.BG)
        titles.pack(side="left")
        tk.Label(
            titles,
            text="PDF 复习",
            background=theme.BG,
            foreground=theme.TEXT,
            font=self._fonts["h1"],
            anchor="w",
        ).pack(anchor="w")
        self._status = tk.Label(
            titles,
            text="",
            background=theme.BG,
            foreground=theme.MUTED,
            font=self._fonts["small"],
            anchor="w",
        )
        self._status.pack(anchor="w")

        actions = tk.Frame(header, background=theme.BG)
        actions.pack(side="right")

        RoundedButton(
            actions, "设置", self._on_settings, self._fonts, variant="ghost"
        ).pack(side="right", padx=(theme.px(6), 0))

        self._export_button = RoundedButton(
            actions, "导出给 iPhone", self._on_export, self._fonts, variant="primary"
        )
        self._export_button.pack(side="right", padx=(theme.px(6), 0))
        self._export_button.set_enabled(False)

        self._delete_button = RoundedButton(
            actions, "删除", self._on_delete, self._fonts, variant="danger"
        )
        self._delete_button.pack(side="right", padx=(theme.px(6), 0))
        self._delete_button.set_enabled(False)

        RoundedButton(
            actions, "新建牌组", self._on_new, self._fonts, variant="secondary"
        ).pack(side="right")

    def _build_footer(self) -> None:
        Divider(self, background=theme.BORDER).pack(fill="x", pady=(theme.px(theme.PAD_M), 0))
        footer = tk.Frame(self, background=theme.BG)
        footer.pack(fill="x", padx=theme.px(theme.PAD_L), pady=(theme.px(7), theme.px(9)))

        self._footer = tk.Label(
            footer,
            text="",
            background=theme.BG,
            foreground=theme.MUTED,
            font=self._fonts["small"],
            anchor="w",
        )
        self._footer.pack(fill="x")

    # -- 列表 ------------------------------------------------------------

    def _refresh_list(self, keep: Optional[Path] = None) -> Optional[DeckEntry]:
        try:
            entries = self._store.list()
        except OSError as exc:
            self._footer.configure(text=f"读不了牌组目录：{exc}")
            return None

        selected = self._list.set_entries(entries, keep)
        self._sync_status(len(entries))
        return selected

    def refresh(self) -> None:
        """重读牌组目录，重建列表，尽量保住当前选中项。"""
        self._refresh_list()

    def _sync_status(self, count: int) -> None:
        self._footer.configure(text=f"共 {count} 个牌组  ·  存放位置：{self._store.root}")
        if not self._settings.is_configured:
            self._set_status("还没配置 AI 接口 — 点右上角「设置」", theme.WARN)
        else:
            self._set_status(self._settings.model, theme.MUTED)

    def _set_status(self, text: str, color: str) -> None:
        """更新顶栏那行小字，并让颜色从浅蓝「落」到目标色。

        这行字在配好接口、切牌组时会变。直接改文字会让人怀疑是不是自己
        眼花——颜色先亮一下再落定，变化才有落点。
        """
        changed = self._status.cget("text") != text
        self._status.configure(text=text)
        if not changed:
            self._status.configure(foreground=color)
            return
        if anim.reduce_motion():
            self._status.configure(foreground=color)
            return

        start = theme.ACCENT

        def frame(t: float) -> None:
            if not self._status.winfo_exists():
                return
            self._status.configure(foreground=anim.lerp_color(start, color, t))

        anim.animate(self._status, 420, frame, on_done=lambda: self._status.configure(foreground=color))

    # -- 事件 ------------------------------------------------------------

    def _on_select(self, entry: Optional[DeckEntry]) -> None:
        if entry is None:
            self._current_document = None
            self._preview.show(None)
            self._export_button.set_enabled(False)
            self._delete_button.set_enabled(False)
            return

        try:
            document, _meta = self._store.load(entry.folder)
        except (OSError, ValueError, KeyError) as exc:
            self._current_document = None
            self._preview.show(None)
            self._export_button.set_enabled(False)
            self._delete_button.set_enabled(True)
            self._footer.configure(text=f"这个牌组读不出来：{exc}")
            return

        self._current_document = document
        self._preview.show(document)
        self._export_button.set_enabled(True)
        self._delete_button.set_enabled(True)

    # -- 动作 ------------------------------------------------------------

    def _on_new(self) -> None:
        dialog = AnalyzeDialog(self.winfo_toplevel(), self._fonts, self._settings, self._store)
        self.wait_window(dialog)
        if dialog.created_folder is not None:
            self._refresh_list(keep=dialog.created_folder)

    def _on_settings(self) -> None:
        dialog = SettingsDialog(self.winfo_toplevel(), self._fonts, self._settings)
        self.wait_window(dialog)
        if dialog.saved:
            self._settings = settings_mod.load_settings()
            self._sync_status(self._list.count)

    def _on_export(self) -> None:
        entry = self._list.selected_entry
        if entry is not None:
            self._export_entry(entry)

    def _export_entry(self, entry: DeckEntry) -> None:
        try:
            document, _meta = self._store.load(entry.folder)
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("读不出来", str(exc), parent=self.winfo_toplevel())
            return

        suggested = export_mod.default_export_name(document)
        chosen = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            title="导出给 iPhone",
            defaultextension=".json",
            initialfile=suggested,
            filetypes=[("PDF 复习牌组", "*.pdfreview.json"), ("JSON", "*.json")],
        )
        if not chosen:
            return

        try:
            path = export_mod.export_to(document, chosen)
        except export_mod.ExportError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.winfo_toplevel())
            return

        messagebox.showinfo(
            "导出好了",
            f"已保存到：\n{path}\n\n"
            "把这个文件传到 iPhone（微信、邮件、iCloud 都行），"
            "在 App 里点「导入」选中它就能复习了。",
            parent=self.winfo_toplevel(),
        )

    def _on_delete(self) -> None:
        entry = self._list.selected_entry
        if entry is None:
            return

        if not messagebox.askyesno(
            "删除牌组",
            f"确定删掉「{entry.meta.title}」吗？\n\n"
            f"这条会连同它下面的 {entry.card_count} 张卡片一起删除，不能撤销。\n"
            f"只是想让手机上也有一份的话，用「导出给 iPhone」就够了。",
            parent=self.winfo_toplevel(),
        ):
            return

        try:
            self._store.delete(entry.folder)
        except (OSError, ValueError) as exc:
            messagebox.showerror("删除失败", str(exc), parent=self.winfo_toplevel())
            return

        self._current_document = None
        self._preview.show(None)
        self._refresh_list()


def _panel(parent: tk.Misc) -> tk.Frame:
    """一块白底面板，外面套 1px 边框。

    Tk 的 Frame 不能只画一边的边框，所以用「外层 Frame 当边框色、内层
    Frame 当白底」的两层结构。调用方把内容放进取回的 `inner` 里。
    """
    shell: tk.Frame = tk.Frame(parent, background=theme.BORDER, bd=0, highlightthickness=0)
    inner = tk.Frame(shell, background=theme.SURFACE, bd=0, highlightthickness=0)
    edge = max(1, theme.px(1))
    inner.pack(fill="both", expand=True, padx=edge, pady=edge)
    shell.inner = inner  # type: ignore[attr-defined]
    return shell


def run() -> None:
    """程序入口。"""
    # 必须在 tk.Tk() 之前：窗口一旦建出来，缩放模式就定下了。
    dpi.enable()

    root = tk.Tk()
    root.title("PDF 复习")

    fonts = theme.apply_theme(root)
    # 尺寸在 apply_theme 之后算：那时才知道 SCALE 是多少
    root.geometry(f"{theme.px(1060)}x{theme.px(700)}")
    root.minsize(theme.px(880), theme.px(560))

    MainWindow(root, fonts)

    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    root.geometry(f"+{max(0, (screen_w - width) // 2)}+{max(0, (screen_h - height) // 3)}")

    root.mainloop()
