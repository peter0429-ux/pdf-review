"""分析窗口：选文件 → 看进度 → 存成牌组。

这个窗口承担了整个程序最重的一段流程，所以它自己管一个 `Worker`，
关窗时要把后台任务取消掉——不然用户关掉窗口、程序还在后台静静烧 token。

尺寸都是设计像素，落笔前过 `theme.px()`。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from core import ai, analyzer, limits
from core import settings as settings_mod
from core.extract import SUPPORTED_SUFFIXES, ExtractError, Extraction, extract
from core.project import DeckMeta, DeckStore

from . import anim, theme
from .widgets import Divider, RoundedButton, Spinner
from .worker import Worker

#: 文件对话框的过滤器。写在一处，将来加格式改这里。
_FILE_TYPES = [
    ("全部支持的格式", " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_SUFFIXES))),
    ("PDF", "*.pdf"),
    ("Word 文档", "*.docx"),
    ("PowerPoint", "*.pptx"),
    ("Excel 表格", "*.xlsx"),
    ("纯文本 / Markdown", "*.txt *.md"),
    ("网页", "*.html *.htm"),
    ("所有文件", "*.*"),
]


class _Section:
    """带序号的小标题。三步流程用它分段，眼睛好找位置。"""

    def __init__(
        self, parent: tk.Misc, fonts: dict[str, tkfont.Font], index: str, title: str
    ) -> None:
        row = tk.Frame(parent, background=theme.SURFACE)
        row.pack(fill="x", pady=(0, theme.px(theme.PAD_XS)))

        tk.Label(
            row,
            text=index,
            font=fonts["small"],
            foreground=theme.ACCENT,
            background=theme.ACCENT_SOFT,
            width=2,
        ).pack(side="left", ipady=theme.px(1))
        tk.Label(
            row,
            text=title,
            font=fonts["h2"],
            foreground=theme.TEXT,
            background=theme.SURFACE,
        ).pack(side="left", padx=(theme.px(theme.PAD_S), 0))


class AnalyzeDialog(tk.Toplevel):
    """点「新建牌组」开的就是这个。成功建出牌组后 `created_folder` 不为空。"""

    def __init__(
        self,
        master: tk.Misc,
        fonts: dict[str, tkfont.Font],
        settings: settings_mod.Settings,
        store: DeckStore,
    ) -> None:
        super().__init__(master)
        self.title("新建牌组")
        self.configure(background=theme.SURFACE)
        self.minsize(theme.px(600), theme.px(440))
        self.transient(master)

        self.created_folder: Optional[Path] = None
        self._fonts = fonts
        self._settings = settings
        self._store = store
        self._worker = Worker(self)
        self._extraction: Optional[Extraction] = None
        self._source_path: Optional[Path] = None
        self._closed = False
        #: 进度条当前显示的数值。动画在它和目标值之间插值，
        #: 否则模型一块一块回来时进度条是一跳一跳的。
        self._shown_progress = 0.0

        self._path_text = tk.StringVar(value="还没有选文件")
        self._title = tk.StringVar(value="")
        self._progress_text = tk.StringVar(value="")
        self._progress_value = tk.DoubleVar(value=0.0)
        self._hint = tk.StringVar(value="")

        self._build()
        self._center_on(master)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _e: self._on_close())

        self.after(10, lambda: anim.fade_in_window(self))

    # -- 构建 ------------------------------------------------------------

    def _build(self) -> None:
        body = tk.Frame(
            self,
            background=theme.SURFACE,
            padx=theme.px(theme.PAD_XL),
            pady=theme.px(theme.PAD_L),
        )
        body.pack(fill="both", expand=True)

        # 1. 选文件
        _Section(body, self._fonts, "1", "选一份文件")
        picker = tk.Frame(body, background=theme.SURFACE)
        picker.pack(fill="x", pady=(theme.px(theme.PAD_S), 0))
        ttk.Entry(picker, textvariable=self._path_text, state="readonly").pack(
            side="left", fill="x", expand=True, ipady=theme.px(4)
        )
        self._pick_button = RoundedButton(
            picker,
            text="选文件…",
            variant="secondary",
            fonts=self._fonts,
            background=theme.SURFACE,
            command=self._on_pick,
        )
        self._pick_button.pack(side="left", padx=(theme.px(theme.PAD_S), 0))

        # 用「 / 」分隔并留空格：Tk 只在空格处断行，中文连排会被当成一个
        # 超长单词整段挪到下一行，前面只剩「支持」两个字孤零零一行。
        tk.Label(
            body,
            text="支持 PDF / Word（.docx）/ PowerPoint（.pptx）/ Excel（.xlsx）/ 纯文本 / Markdown / 网页",
            font=self._fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
            anchor="w",
            justify="left",
            wraplength=theme.px(520),
        ).pack(fill="x", pady=(theme.px(theme.PAD_XS), 0))
        tk.Label(
            body,
            text="扫描件（只有图片、没有文字层的 PDF）读不出来。",
            font=self._fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
            anchor="w",
            justify="left",
            wraplength=theme.px(520),
        ).pack(fill="x")

        # 2. 牌组名
        tk.Frame(body, background=theme.SURFACE, height=theme.px(theme.PAD_M)).pack(fill="x")
        _Section(body, self._fonts, "2", "起个名字")
        ttk.Entry(body, textvariable=self._title, font=self._fonts["body"]).pack(
            fill="x", pady=(theme.px(theme.PAD_S), 0), ipady=theme.px(4)
        )
        tk.Label(
            body,
            text=f"留空就用文件名。最多 {limits.TITLE_MAX} 个字。",
            font=self._fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
            anchor="w",
        ).pack(fill="x", pady=(theme.px(4), 0))

        # 3. 进度
        tk.Frame(body, background=theme.SURFACE, height=theme.px(theme.PAD_M)).pack(fill="x")
        _Section(body, self._fonts, "3", "开始分析")

        self._progress = ttk.Progressbar(
            body,
            orient="horizontal",
            mode="determinate",
            maximum=1.0,
            variable=self._progress_value,
        )
        self._progress.pack(fill="x", pady=(theme.px(theme.PAD_S), theme.px(theme.PAD_XS)))

        # 进度条第一格还没走完的那段时间（请求模型、等首个 token）看起来像
        # 卡住了。转圈的小弧专门填这段空窗，让人知道程序在等网络而不是死了。
        status_row = tk.Frame(body, background=theme.SURFACE)
        status_row.pack(fill="x")

        self._spinner = Spinner(
            status_row,
            size=theme.px(13),
            thickness=1,
            background=theme.SURFACE,
        )
        self._spinner.pack(side="left", padx=(0, theme.px(6)))

        tk.Label(
            status_row,
            textvariable=self._progress_text,
            font=self._fonts["small"],
            foreground=theme.TEXT_SOFT,
            background=theme.SURFACE,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        tk.Label(
            body,
            textvariable=self._hint,
            font=self._fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
            anchor="w",
            justify="left",
            wraplength=theme.px(520),
        ).pack(fill="x", pady=(theme.px(4), 0))

        Divider(self).pack(fill="x")

        # 底部按钮
        footer = tk.Frame(
            self,
            background=theme.SURFACE,
            padx=theme.px(theme.PAD_XL),
            pady=theme.px(theme.PAD_M),
        )
        footer.pack(fill="x", side="bottom")

        self._start_button = RoundedButton(
            footer,
            text="开始分析",
            variant="primary",
            fonts=self._fonts,
            background=theme.SURFACE,
            command=self._on_start,
        )
        self._start_button.pack(side="right")
        self._cancel_button = RoundedButton(
            footer,
            text="取消",
            variant="ghost",
            fonts=self._fonts,
            background=theme.SURFACE,
            command=self._on_cancel,
        )
        self._cancel_button.pack(side="right", padx=(0, theme.px(theme.PAD_S)))

    def _center_on(self, master: tk.Misc) -> None:
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = master.winfo_rootx() + (master.winfo_width() - width) // 2
        y = master.winfo_rooty() + max(theme.px(40), (master.winfo_height() - height) // 3)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    # -- 选文件 ----------------------------------------------------------

    def _on_pick(self) -> None:
        chosen = filedialog.askopenfilename(
            parent=self,
            title="选一份要分析的文档",
            filetypes=_FILE_TYPES,
        )
        if not chosen:
            return

        path = Path(chosen)
        self._source_path = path
        self._path_text.set(str(path))
        if not self._title.get().strip():
            self._title.set(path.stem[: limits.TITLE_MAX])

        # 先抽一遍看看能不能读：这一步很快（大文件几秒），
        # 也比让用户点了「开始分析」等半天才发现是扫描件强。
        self._hint.set("正在读取文件…")
        self._start_button.set_enabled(False)
        self.update_idletasks()

        try:
            extraction = extract(path)
        except ExtractError as exc:
            self._extraction = None
            self._hint.set(str(exc))
            self._start_button.set_enabled(True)
            return
        except Exception as exc:  # noqa: BLE001
            self._extraction = None
            self._hint.set(f"读取失败：{exc}")
            self._start_button.set_enabled(True)
            return

        self._extraction = extraction
        self._start_button.set_enabled(True)

        if not extraction.has_text_layer:
            self._hint.set(
                "这个 PDF 几乎没有文字层，多半是扫描件或纯图片。当前版本不做图片识别，"
                "换一份带文字层的文件，或者先用别的工具 OCR 一下。"
            )
            return

        estimate = analyzer.estimate_total_cards(extraction, self._settings.cards_per_chunk)
        self._hint.set(
            f"读到 {extraction.page_count} {extraction.unit_label}、约 {extraction.char_count} 字，"
            f"会切成若干块；按每块 {self._settings.cards_per_chunk} 张算，最多约 {estimate} 张卡片。"
        )

    # -- 分析 ------------------------------------------------------------

    def _on_start(self) -> None:
        if self._extraction is None or self._source_path is None:
            messagebox.showinfo("还没选文件", "先点「选文件…」挑一份文档。", parent=self)
            return

        problems = self._settings.validate()
        if problems:
            messagebox.showwarning(
                "还没配置接口",
                "先去「设置」里填好接口地址、模型和 API Key。\n\n" + "\n".join(problems),
                parent=self,
            )
            return

        title = self._title.get().strip()[: limits.TITLE_MAX] or self._extraction.stem_title
        extraction = self._extraction
        source_path = self._source_path
        config = ai.AIConfig.from_settings(self._settings)
        per_chunk = self._settings.cards_per_chunk

        self._start_button.set_enabled(False)
        self._pick_button.set_enabled(False)
        self._cancel_button.set_text("停止")
        self._shown_progress = 0.0
        self._progress_value.set(0.0)
        self._progress_text.set("准备中…")
        self._hint.set("")
        self._spinner.start()

        def job(report):
            return analyzer.analyze_file(
                source_path,
                config=config,
                title=title,
                cards_per_chunk=per_chunk,
                on_progress=report,
                cancel_check=self._worker.is_cancelled,
                extraction=extraction,
            )

        self._worker.start(
            job=job,
            on_progress=self._on_progress,
            on_done=self._on_done,
            on_error=self._on_error,
        )

    def _on_progress(self, progress: analyzer.Progress) -> None:
        self._set_progress(progress.fraction)
        bits = [progress.stage]
        if progress.chunk_total:
            bits.append(f"第 {progress.chunk_index}/{progress.chunk_total} 块")
        if progress.cards_so_far:
            bits.append(f"已出 {progress.cards_so_far} 张")
        self._progress_text.set("  ·  ".join(bits))

        if progress.recent_questions:
            preview = progress.recent_questions[0]
            if len(preview) > 24:
                preview = preview[:24] + "…"
            self._hint.set(f"刚出的卡：{preview}")

    def _set_progress(self, target: float) -> None:
        """把进度条平滑推到目标值。

        每块回来的间隔是几秒到几十秒不等；直接 set 会看到进度条「啪」地
        跳一截再定住，动画补上中间的过渡。
        """
        target = max(0.0, min(1.0, target))
        start = self._shown_progress
        if abs(target - start) < 1e-3 or anim.reduce_motion():
            self._shown_progress = target
            self._progress_value.set(target)
            return

        def frame(value: float) -> None:
            self._shown_progress = value
            self._progress_value.set(value)

        anim.tween_number(self, start, target, 400, frame)

    def _on_done(self, outcome: analyzer.AnalysisOutcome) -> None:
        self._spinner.stop()
        document = outcome.document
        meta = DeckMeta(
            title=document.deck.title,
            source_file=outcome.extraction.file_name,
            source_kind=outcome.extraction.kind,
            page_count=outcome.extraction.page_count,
            text_length=outcome.extraction.char_count,
            chunks_done=len(outcome.chunks),
        )

        try:
            folder = self._store.create(document, meta)
        except OSError as exc:
            self._on_error(exc)
            return

        self.created_folder = folder
        suffix = ""
        if outcome.dropped_duplicates:
            suffix = f"，合并了 {outcome.dropped_duplicates} 张重复卡片"
        messagebox.showinfo(
            "分析完成",
            f"「{document.deck.title}」已存好，共 {len(document.cards)} 张卡片{suffix}。",
            parent=self,
        )
        self._close_with_fade()

    def _on_error(self, error: BaseException) -> None:
        self._spinner.stop()
        self._reset_buttons()
        self._progress_text.set("")
        self._hint.set(f"失败：{error}")

    def _reset_buttons(self) -> None:
        self._start_button.set_enabled(True)
        self._pick_button.set_enabled(True)
        self._cancel_button.set_text("取消")

    def _close_with_fade(self) -> None:
        """淡出后再销毁。先放 grab，否则淡出期间主窗口点不动。"""
        try:
            self.grab_release()
        except Exception:  # noqa: BLE001 - 没 grab 过时会抛
            pass
        self._spinner.stop()
        anim.fade_out_window(self, self.destroy)

    # -- 关窗 ------------------------------------------------------------

    def _on_cancel(self) -> None:
        if self._worker.running:
            self._worker.cancel()
            self._progress_text.set("正在停止…")
            return
        self._close_with_fade()

    def _on_close(self) -> None:
        if self._worker.running:
            if not messagebox.askyesno(
                "正在分析",
                "分析还没结束，关掉窗口会丢弃已经产出的卡片。确定要关吗？",
                parent=self,
            ):
                return
            self._worker.cancel()
        self._close_with_fade()
