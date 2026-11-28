"""设置窗口：接口地址、模型、API Key、每块要几张卡。

API Key 落地是 DPAPI 加密的（见 `core/settings.py`），所以这里可以放心
让用户填真实的 key —— 文件被拷到别的机器上也解不开。

尺寸都是设计像素，落笔前过 `theme.px()`。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from typing import Optional

from core import ai, settings as settings_mod

from . import anim, theme
from .widgets import Divider, RoundedButton


class _Field:
    """一行输入：标签 + 输入框 + 灰色说明。

    单独抽出来是因为三段几乎一样、只有标签和提示不同；写在 `_build()`
    里会变成三层嵌套循环，改个间距要数行号。
    """

    def __init__(
        self,
        parent: tk.Misc,
        fonts: dict[str, tkfont.Font],
        label: str,
        variable: tk.StringVar,
        hint: str,
        secret: bool = False,
    ) -> None:
        self.frame = tk.Frame(parent, background=theme.SURFACE)
        self.frame.pack(fill="x", pady=(0, theme.px(theme.PAD_M)))

        tk.Label(
            self.frame,
            text=label,
            font=fonts["small"],
            foreground=theme.TEXT_SOFT,
            background=theme.SURFACE,
            anchor="w",
        ).pack(fill="x", pady=(0, theme.px(4)))

        self.entry = ttk.Entry(self.frame, textvariable=variable, font=fonts["body"])
        self.entry.pack(fill="x", ipady=theme.px(6))
        if secret:
            self.entry.configure(show="•")

        tk.Label(
            self.frame,
            text=hint,
            font=fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(theme.px(4), 0))


class SettingsDialog(tk.Toplevel):
    """模态对话框。关掉之后 `saved` 为 True 表示用户点了保存。"""

    def __init__(self, master: tk.Misc, fonts: dict[str, tkfont.Font], current: settings_mod.Settings) -> None:
        super().__init__(master)
        self.title("设置")
        self.configure(background=theme.SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.saved = False
        self._fonts = fonts
        self._original = current

        self._base_url = tk.StringVar(value=current.base_url)
        self._model = tk.StringVar(value=current.model)
        self._api_key = tk.StringVar(value=current.api_key)
        self._cards = tk.IntVar(value=current.cards_per_chunk)
        self._status = tk.StringVar(value="")

        self._build()
        self._center_on(master)

        if current.key_error:
            self._status.set("上次保存的 Key 解不开了（可能换过 Windows 账户），请重新填一次。")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda _e: self._on_cancel())
        self.bind("<Return>", lambda _e: self._on_save())

        # 打开就把光标放到最需要填的那一格
        target_name = "base" if current.api_key else "key"
        self.after(80, lambda: self._focus(target_name))
        # 淡入要等窗口已经映射到屏幕上，否则 Tk 可能忽略 -alpha
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

        tk.Label(
            body,
            text="AI 接口",
            font=self._fonts["h2"],
            foreground=theme.TEXT,
            background=theme.SURFACE,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            body,
            text="填的是 OpenAI 兼容接口。DeepSeek、通义、本地 Ollama 都按这个格式填。",
            font=self._fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
            anchor="w",
        ).pack(fill="x", pady=(theme.px(4), theme.px(theme.PAD_L)))

        self._base_field = _Field(
            body,
            self._fonts,
            "接口地址",
            self._base_url,
            "填到 /v1 为止，不要带 /chat/completions",
        )
        self._model_field = _Field(
            body,
            self._fonts,
            "模型名",
            self._model,
            "例如 gpt-4o-mini、deepseek-chat",
        )
        self._key_field = _Field(
            body,
            self._fonts,
            "API Key",
            self._api_key,
            "只保存在这台电脑上，用 Windows 账户加密",
            secret=True,
        )
        self._entries_by_name: dict[str, ttk.Entry] = {
            "base": self._base_field.entry,
            "model": self._model_field.entry,
            "key": self._key_field.entry,
        }

        divider = Divider(body)
        divider.pack(fill="x", pady=(theme.px(theme.PAD_XS), theme.px(theme.PAD_M)))

        cards_row = tk.Frame(body, background=theme.SURFACE)
        cards_row.pack(fill="x")
        tk.Label(
            cards_row,
            text="每块卡片数",
            font=self._fonts["small"],
            foreground=theme.TEXT_SOFT,
            background=theme.SURFACE,
        ).pack(side="left")
        spin = ttk.Spinbox(cards_row, from_=1, to=12, textvariable=self._cards, width=5)
        spin.pack(
            side="left", padx=(theme.px(theme.PAD_S), theme.px(theme.PAD_S))
        )
        tk.Label(
            cards_row,
            text="6 是个稳妥的默认值",
            font=self._fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
        ).pack(side="left")

        tk.Label(
            body,
            text="每份文件会被切成若干块，一块问一次模型。块越大越省调用，但一次要出的卡越多，题目质量会往下掉。",
            font=self._fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
            anchor="w",
            justify="left",
            wraplength=theme.px(420),
        ).pack(fill="x", pady=(theme.px(4), 0))

        self._test_button = RoundedButton(
            body,
            text="测试连接",
            variant="secondary",
            fonts=self._fonts,
            background=theme.SURFACE,
            command=self._on_test,
        )
        self._test_button.pack(anchor="w", pady=(theme.px(theme.PAD_L), 0))

        tk.Label(
            body,
            textvariable=self._status,
            font=self._fonts["small"],
            foreground=theme.MUTED,
            background=theme.SURFACE,
            anchor="w",
            justify="left",
            wraplength=theme.px(440),
        ).pack(fill="x", pady=(theme.px(theme.PAD_S), 0))

        Divider(self).pack(fill="x")

        footer = tk.Frame(
            self,
            background=theme.SURFACE,
            padx=theme.px(theme.PAD_XL),
            pady=theme.px(theme.PAD_M),
        )
        footer.pack(fill="x")
        RoundedButton(
            footer,
            text="保存",
            variant="primary",
            fonts=self._fonts,
            background=theme.SURFACE,
            command=self._on_save,
        ).pack(side="right")
        RoundedButton(
            footer,
            text="取消",
            variant="ghost",
            fonts=self._fonts,
            background=theme.SURFACE,
            command=self._on_cancel,
        ).pack(side="right", padx=(0, theme.px(theme.PAD_S)))

    def _focus(self, name: str) -> None:
        """把光标放到某一格。窗口可能已经被关掉了，所以要防一手。"""
        entry = self._entries_by_name.get(name)
        if entry is None or not entry.winfo_exists():
            return
        entry.focus_set()
        entry.select_range(0, "end")

    def _center_on(self, master: tk.Misc) -> None:
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = master.winfo_rootx() + (master.winfo_width() - width) // 2
        y = master.winfo_rooty() + (master.winfo_height() - height) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    # -- 动作 ------------------------------------------------------------

    def _collect(self) -> settings_mod.Settings:
        return settings_mod.Settings(
            base_url=self._base_url.get().strip(),
            model=self._model.get().strip(),
            api_key=self._api_key.get().strip(),
            cards_per_chunk=max(1, min(12, int(self._cards.get() or 6))),
            last_project=self._original.last_project,
        )

    def _on_test(self) -> None:
        candidate = self._collect()
        problems = candidate.validate()
        if problems:
            self._status.set("先补全：" + "；".join(problems))
            return

        self._status.set("正在连接…")
        self._test_button.set_enabled(False)
        self.update_idletasks()

        # 连网在主线程里做会卡住窗口；这里用一个小线程，测完用 after 回主线程。
        # 只在设置窗口里这么干——它是一次性的短请求，不值得为此引入整个 Worker。
        import threading

        def run() -> None:
            try:
                reply = ai.test_connection(ai.AIConfig.from_settings(candidate))
            except BaseException as exc:  # noqa: BLE001
                message = str(exc)
                self.after(0, lambda: self._finish_test(None, message))
            else:
                self.after(0, lambda: self._finish_test(reply, None))

        threading.Thread(target=run, daemon=True).start()

    def _finish_test(self, reply: Optional[str], error: Optional[str]) -> None:
        if not self.winfo_exists():
            return
        self._test_button.set_enabled(True)
        if error:
            self._status.set(f"连接失败：{error}")
        else:
            snippet = (reply or "").strip().replace("\n", " ")[:40]
            self._status.set(f"连接成功，模型回了：{snippet or '（空）'}")

    def _on_save(self) -> None:
        candidate = self._collect()
        problems = candidate.validate()
        if problems:
            messagebox.showwarning("还没填完", "\n".join(problems), parent=self)
            return
        try:
            settings_mod.save_settings(candidate)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.saved = True
        self._close_with_fade()

    def _on_cancel(self) -> None:
        self.saved = False
        self._close_with_fade()

    def _close_with_fade(self) -> None:
        """淡出后再销毁。

        先把 grab 放掉：淡出期间窗口还在，抓着 grab 会让底下主窗口的
        点击全被吃掉一百多毫秒，感觉像程序卡了一下。
        """
        try:
            self.grab_release()
        except Exception:  # noqa: BLE001 - 没 grab 过时会抛
            pass
        anim.fade_out_window(self, self.destroy)
