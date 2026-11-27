"""设置窗口：接口地址、模型、API Key、每块要几张卡。

API Key 落地是 DPAPI 加密的（见 `core/settings.py`），所以这里可以放心
让用户填真实的 key —— 文件被拷到别的机器上也解不开。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from typing import Optional

from core import ai, settings as settings_mod

from . import theme


class SettingsDialog(tk.Toplevel):
    """模态对话框。关掉之后 `saved` 为 True 表示用户点了保存。"""

    def __init__(self, master: tk.Misc, fonts: dict[str, tkfont.Font], current: settings_mod.Settings) -> None:
        super().__init__(master)
        self.title("设置")
        self.configure(background=theme.BG)
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

    # -- 构建 ------------------------------------------------------------

    def _build(self) -> None:
        body = ttk.Frame(self, padding=theme.PAD_L)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="AI 接口", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, theme.PAD_M)
        )

        rows = [
            ("接口地址", self._base_url, "填到 /v1 为止，不要带 /chat/completions", "base"),
            ("模型名", self._model, "例如 gpt-4o-mini、deepseek-chat", "model"),
            ("API Key", self._api_key, "只保存在这台电脑上，用 Windows 账户加密", "key"),
        ]

        self._entries_by_name: dict[str, ttk.Entry] = {}

        for offset, (label, variable, hint, name) in enumerate(rows, start=1):
            ttk.Label(body, text=label).grid(row=offset * 2 - 1, column=0, sticky="e", padx=(0, theme.PAD_S), pady=(theme.PAD_S, 0))
            entry = ttk.Entry(body, textvariable=variable, width=46, font=self._fonts["body"])
            entry.grid(row=offset * 2 - 1, column=1, sticky="we", pady=(theme.PAD_S, 0))
            if name == "key":
                entry.configure(show="•")
            self._entries_by_name[name] = entry
            ttk.Label(body, text=hint, style="Muted.TLabel").grid(
                row=offset * 2, column=1, sticky="w", pady=(2, 0)
            )

        # 每块卡片数
        row = len(rows) * 2 + 1
        ttk.Label(body, text="每块卡片数").grid(row=row, column=0, sticky="e", padx=(0, theme.PAD_S), pady=(theme.PAD_M, 0))
        spin = ttk.Spinbox(body, from_=1, to=12, textvariable=self._cards, width=6)
        spin.grid(row=row, column=1, sticky="w", pady=(theme.PAD_M, 0))
        ttk.Label(
            body,
            text="每份文件会被切成若干块，一块问一次模型。6 是个稳妥的默认值。",
            style="Muted.TLabel",
            wraplength=380,
            justify="left",
        ).grid(row=row + 1, column=1, sticky="w", pady=(2, 0))

        # 测试按钮 + 状态
        actions = ttk.Frame(body)
        actions.grid(row=row + 2, column=0, columnspan=2, sticky="we", pady=(theme.PAD_L, 0))

        self._test_button = ttk.Button(actions, text="测试连接", command=self._on_test)
        self._test_button.pack(side="left")

        ttk.Label(
            body, textvariable=self._status, style="Muted.TLabel", wraplength=460, justify="left"
        ).grid(row=row + 3, column=0, columnspan=2, sticky="w", pady=(theme.PAD_S, 0))

        # 底部按钮
        footer = ttk.Frame(self, padding=(theme.PAD_L, 0, theme.PAD_L, theme.PAD_L))
        footer.pack(fill="x")
        ttk.Button(footer, text="取消", command=self._on_cancel).pack(side="right")
        ttk.Button(footer, text="保存", command=self._on_save).pack(side="right", padx=(0, theme.PAD_S))

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
        self._test_button.configure(state="disabled")
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
        self._test_button.configure(state="normal")
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
        self.destroy()

    def _on_cancel(self) -> None:
        self.saved = False
        self.destroy()
