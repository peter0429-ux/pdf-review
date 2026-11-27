"""主窗口：左边牌组列表，右边卡片预览，上面一排按钮。

布局用 `tk.PanedWindow` 而不是 grid 固定比例——用户会想拖一下分隔条，
尤其是牌组名很长的时候。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from core import export as export_mod
from core import limits
from core.cards import AnalysisDocument
from core.project import DeckEntry, DeckStore, default_workspace

from . import theme
from .analyze_dialog import AnalyzeDialog
from .preview import CardPreview
from .settings_dialog import SettingsDialog

from core import settings as settings_mod


class MainWindow(ttk.Frame):
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
        super().__init__(master, padding=0)
        self.pack(fill="both", expand=True)

        self._fonts = fonts
        self._settings = settings if settings is not None else settings_mod.load_settings()
        self._store = store if store is not None else DeckStore()
        # 只有「设置是从磁盘读的」才自动弹配置窗口。外面明确传进来一份设置时
        # 不弹——那通常意味着调用方已经安排好了，弹窗会打断它（测试里更会直接挂住）。
        self._auto_open_settings = settings is None
        self._entries: dict[str, DeckEntry] = {}
        self._selected_folder: Optional[Path] = None
        self._current_document: Optional[AnalysisDocument] = None

        self._build()
        self.refresh()

        if self._auto_open_settings and not self._settings.is_configured:
            # 第一次启动：直接开设置，省得用户乱点一圈才发现没配 key
            self.after(120, self._on_settings)

    # -- 构建 ------------------------------------------------------------

    def _build(self) -> None:
        # 顶栏
        header = ttk.Frame(self, padding=(theme.PAD_L, theme.PAD_M))
        header.pack(fill="x")

        ttk.Label(header, text="PDF 复习", style="Title.TLabel").pack(side="left")
        self._status = ttk.Label(header, text="", style="Muted.TLabel")
        self._status.pack(side="left", padx=(theme.PAD_M, 0))

        ttk.Button(header, text="设置", command=self._on_settings).pack(side="right")
        self._export_button = ttk.Button(
            header, text="导出给 iPhone", command=self._on_export, state="disabled"
        )
        self._export_button.pack(side="right", padx=(0, theme.PAD_S))
        self._delete_button = ttk.Button(
            header, text="删除", command=self._on_delete, state="disabled"
        )
        self._delete_button.pack(side="right", padx=(0, theme.PAD_S))
        ttk.Button(header, text="新建牌组…", command=self._on_new).pack(side="right", padx=(0, theme.PAD_S))

        # 分割区
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=theme.PAD_L, pady=(0, theme.PAD_S))

        left = ttk.Frame(panes)
        panes.add(left, weight=2)

        right = ttk.Frame(panes)
        panes.add(right, weight=3)

        # 左：列表
        # 用 grid 而不是「tree.pack + scrollbar.place」：place 的滚动条会压在最右一列
        # 上面，把「更新于」的最后一个字盖掉。grid 让它们各占一格，谁也不挡谁。
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            left, columns=("cards", "updated"), show="tree headings", selectmode="browse"
        )
        self._tree.heading("#0", text="牌组")
        self._tree.heading("cards", text="卡片")
        self._tree.heading("updated", text="更新于")
        # 列宽是按 150% 缩放（中文 Windows 的常见设置）算的：10pt「微软雅黑」下
        # 「2026-11-28 02:00」大约要 120 逻辑像素，留 8 像素余量。
        self._tree.column("#0", width=190, minwidth=110, stretch=True)
        self._tree.column("cards", width=52, minwidth=44, anchor="e", stretch=False)
        self._tree.column("updated", width=128, minwidth=116, anchor="w", stretch=False)
        self._tree.grid(row=0, column=0, sticky="nsew")

        tree_scroll = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.grid(row=0, column=1, sticky="ns")

        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>", self._on_double_click)

        # 右：预览
        self._preview = CardPreview(right, self._fonts)
        self._preview.pack(fill="both", expand=True)

        # 底部状态条
        self._footer = ttk.Label(
            self, text="", style="Muted.TLabel", padding=(theme.PAD_L, theme.PAD_XS, theme.PAD_L, theme.PAD_M)
        )
        self._footer.pack(fill="x")

        self._sync_status()

    # -- 列表 ------------------------------------------------------------

    def refresh(self) -> None:
        """重读牌组目录，重建列表，尽量保住当前选中项。"""
        selected = self._selected_folder

        self._tree.delete(*self._tree.get_children())
        self._entries.clear()

        try:
            entries = self._store.list()
        except OSError as exc:
            self._footer.configure(text=f"读不了牌组目录：{exc}")
            return

        for entry in entries:
            key = str(entry.folder)
            self._entries[key] = entry
            self._tree.insert(
                "",
                "end",
                iid=key,
                text=entry.meta.title or entry.folder.name,
                values=(entry.card_count, self._short_time(entry.meta.updated_at)),
            )

        if selected is not None and str(selected) in self._entries:
            self._tree.selection_set(str(selected))
            self._tree.see(str(selected))
        elif entries:
            # 没选中就选第一个：右边空着会让人以为程序没数据
            first = str(entries[0].folder)
            self._tree.selection_set(first)
        else:
            self._on_select(None)

        self._sync_status()

    def _short_time(self, stamp: str) -> str:
        """ISO 时间 → 界面上的短格式。解析不了就原样显示。"""
        if not stamp:
            return "—"
        text = stamp.replace("T", " ")
        # "2026-11-28 02:00:00+08:00" → "2026-11-28 02:00"
        return text[:16]

    def _sync_status(self) -> None:
        count = len(self._entries)
        folder = self._store.root
        self._footer.configure(
            text=f"共 {count} 个牌组  ·  存放位置：{folder}"
        )
        if not self._settings.is_configured:
            self._status.configure(text="还没配置 AI 接口")
        else:
            self._status.configure(text=f"{self._settings.model}")

    # -- 事件 ------------------------------------------------------------

    def _on_select(self, _event: Optional[tk.Event]) -> None:
        selection = self._tree.selection()
        if not selection:
            self._selected_folder = None
            self._current_document = None
            self._preview.show(None)
            self._export_button.configure(state="disabled")
            self._delete_button.configure(state="disabled")
            return

        key = selection[0]
        entry = self._entries.get(key)
        if entry is None:
            return

        self._selected_folder = entry.folder
        try:
            document, _meta = self._store.load(entry.folder)
        except (OSError, ValueError, KeyError) as exc:
            self._current_document = None
            self._preview.show(None)
            self._export_button.configure(state="disabled")
            self._delete_button.configure(state="normal")
            self._footer.configure(text=f"这个牌组读不出来：{exc}")
            return

        self._current_document = document
        self._preview.show(document)
        self._export_button.configure(state="normal")
        self._delete_button.configure(state="normal")

    def _on_double_click(self, _event: tk.Event) -> None:
        if self._current_document is not None:
            self._on_export()

    # -- 动作 ------------------------------------------------------------

    def _on_new(self) -> None:
        dialog = AnalyzeDialog(self.winfo_toplevel(), self._fonts, self._settings, self._store)
        self.wait_window(dialog)
        if dialog.created_folder is not None:
            self._selected_folder = dialog.created_folder
            self.refresh()

    def _on_settings(self) -> None:
        dialog = SettingsDialog(self.winfo_toplevel(), self._fonts, self._settings)
        self.wait_window(dialog)
        if dialog.saved:
            self._settings = settings_mod.load_settings()
            self._sync_status()

    def _on_export(self) -> None:
        document = self._current_document
        if document is None:
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
        entry = self._entries.get(str(self._selected_folder)) if self._selected_folder else None
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

        self._selected_folder = None
        self._current_document = None
        self._preview.show(None)
        self.refresh()


def run() -> None:
    """程序入口。"""
    root = tk.Tk()
    root.title("PDF 复习")
    root.geometry("1000x660")
    root.minsize(820, 520)

    fonts = theme.apply_theme(root)
    MainWindow(root, fonts)

    # 居中
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    root.geometry(f"+{max(0, (screen_w - width) // 2)}+{max(0, (screen_h - height) // 3)}")

    root.mainloop()
