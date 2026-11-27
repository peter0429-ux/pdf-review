"""后台任务的通用跑法：一个线程 + 一个队列 + 界面定时取。

tkinter 不是线程安全的——**只有主线程能碰控件**。所以后台线程只把结果
放进队列，由主线程的 `after` 轮询取出来。

为什么不用 `root.after` 直接调度耗时函数：`after` 也只是在主线程里排队，
真让它去读 80 页 PDF，窗口照样卡住不动（用户会以为程序死了，然后强杀）。
"""

from __future__ import annotations

import queue
import threading
import traceback
from typing import Any, Callable, Optional

#: 轮询间隔（毫秒）。50ms 够跟手，又不会空转烧 CPU。
POLL_MS = 50


class Worker:
    """跑一件事，把进度与结果送回主线程。

    用法::

        worker = Worker(root)
        worker.start(
            job=lambda report: do_the_work(report),
            on_progress=lambda p: bar.set(p.fraction),
            on_done=lambda result: show(result),
            on_error=lambda exc: warn(str(exc)),
        )

    `job` 拿到一个 `report` 回调，可以随时调用（它会把值塞进队列）。
    `job` 的返回值就是 `on_done` 的参数。
    """

    def __init__(self, root: Any) -> None:
        self._root = root
        self._queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()

    # -- 对外 ------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        """请求取消。已经被核心层接住的话，它会尽快抛出退出。"""
        self._cancel.set()

    def start(
        self,
        job: Callable[[Callable[[Any], None]], Any],
        on_progress: Optional[Callable[[Any], None]] = None,
        on_done: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> None:
        if self.running:
            raise RuntimeError("上一个任务还没结束，不能同时跑两个。")

        self._cancel.clear()
        self._queue = queue.Queue()

        def report(value: Any) -> None:
            self._queue.put(("progress", value))

        def run() -> None:
            try:
                result = job(report)
            except BaseException as exc:  # noqa: BLE001 - 什么都要送到界面
                # 把 traceback 一起带回去：用户看到的是人话，
                # 但控制台里得留下够查的现场。
                traceback.print_exc()
                self._queue.put(("error", exc))
            else:
                self._queue.put(("done", result))

        self._thread = threading.Thread(target=run, name="pdfreview-worker", daemon=True)
        self._thread.start()
        self._drain(on_progress, on_done, on_error)

    def is_cancelled(self) -> bool:
        """给核心层当 `cancel_check` 用。"""
        return self._cancel.is_set()

    # -- 内部 ------------------------------------------------------------

    def _drain(
        self,
        on_progress: Optional[Callable[[Any], None]],
        on_done: Optional[Callable[[Any], None]],
        on_error: Optional[Callable[[BaseException], None]],
    ) -> None:
        """把队列里的东西搬出来交给界面，直到任务结束。"""
        finished = False
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break

            if kind == "progress":
                if on_progress is not None:
                    on_progress(payload)
            elif kind == "done":
                finished = True
                if on_done is not None:
                    on_done(payload)
            elif kind == "error":
                finished = True
                if on_error is not None:
                    on_error(payload)

        if finished:
            self._thread = None
            return

        # 没收到终态就再排一次——这就是「界面不阻塞」的全部秘密
        self._root.after(POLL_MS, lambda: self._drain(on_progress, on_done, on_error))
