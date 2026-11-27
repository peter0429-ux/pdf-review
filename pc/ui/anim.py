"""轻量动画：颜色插值 + 位移，全部靠 `after` 逐帧推进。

为什么不用 Canvas 重绘整个界面：Tk 的 Canvas 一帧画几十个元素就开始掉帧，
而这些动效（悬停变色、卡片滑入、对话框淡入）都只需要改一两个属性。
改属性由 Tk 自己做重绘，成本低得多。

所有动画都尊重 Windows 的「在 Windows 中显示动画」开关（`reduce_motion`）。
关掉动画的用户通常是晕动症或老旧机器，硬塞动效只会让人难受。
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from typing import Callable, Optional

#: 一帧的间隔。60fps 在 Tk 上做不到稳定，16ms 排队的实际间隔大约 16~20ms。
FRAME_MS = 16


def reduce_motion() -> bool:
    """Windows 的「在 Windows 中显示动画」被关掉了吗。

    对应 `SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION)`。读不到就
    当作「允许动画」——宁可多一个动效，也不要因为一次系统调用失败把
    界面变成完全静止的。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        SPI_GETCLIENTAREAANIMATION = 0x1042
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
    except Exception:  # noqa: BLE001
        return False
    if not ok:
        return False
    return not enabled.value


# -- 缓动 -----------------------------------------------------------------


def ease_out_cubic(t: float) -> float:
    """起步快、收尾慢。位移类动画用这个，看起来「有惯性」。"""
    t = min(1.0, max(0.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_out_quad(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1.0 - (1.0 - t) ** 2


# -- 颜色 -----------------------------------------------------------------


def _parse(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def lerp_color(start: str, end: str, t: float) -> str:
    """在两个 `#rrggbb` 之间插值。t 会被夹到 0..1。"""
    t = min(1.0, max(0.0, t))
    if t <= 0.0:
        return start
    if t >= 1.0:
        return end
    sr, sg, sb = _parse(start)
    er, eg, eb = _parse(end)
    return "#{:02X}{:02X}{:02X}".format(
        int(round(sr + (er - sr) * t)),
        int(round(sg + (eg - sg) * t)),
        int(round(sb + (eb - sb) * t)),
    )


# -- 驱动 -----------------------------------------------------------------


def animate(
    widget: tk.Misc,
    duration_ms: int,
    on_frame: Callable[[float], None],
    on_done: Optional[Callable[[], None]] = None,
) -> None:
    """在 `duration_ms` 内反复调 `on_frame(t)`，t 从 0 到 1（已缓动过的原始值）。

    调用方自己决定怎么缓动。控件被销毁时自动停，不会抛 TclError。
    同一控件上已有动画时先取消——重复点按钮不该叠出两条动画互相打架。
    """
    _cancel(widget)
    state: dict[str, object] = {}

    def step() -> None:
        if not widget.winfo_exists():
            return
        started = state.get("started")
        if started is None:
            started = time.perf_counter()
            state["started"] = started
        elapsed = (time.perf_counter() - float(started)) * 1000.0
        t = 1.0 if duration_ms <= 0 else min(1.0, elapsed / duration_ms)
        on_frame(t)
        if t >= 1.0:
            state["after"] = None
            if on_done is not None:
                on_done()
            return
        state["after"] = widget.after(FRAME_MS, step)

    step()
    if state.get("after") is not None:
        _ANIMATIONS[widget] = state


def _cancel(widget: tk.Misc) -> None:
    state = _ANIMATIONS.pop(widget, None)
    if not state:
        return
    handle = state.get("after")
    if handle is not None:
        try:
            widget.after_cancel(handle)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            pass


#: 记录正在跑的动画，用来做「同一控件只留一条」和取消。
_ANIMATIONS: dict[tk.Misc, dict[str, object]] = {}


def fade_in_window(window: tk.Toplevel, duration_ms: int = 150) -> None:
    """对话框淡入。Windows 上 Toplevel 支持 `-alpha`。"""
    if reduce_motion():
        return
    try:
        window.attributes("-alpha", 0.0)
    except Exception:  # noqa: BLE001 - 某些窗口管理器不支持
        return

    def frame(t: float) -> None:
        try:
            window.attributes("-alpha", ease_out_quad(t))
        except Exception:  # noqa: BLE001
            pass

    def done() -> None:
        try:
            window.attributes("-alpha", 1.0)
        except Exception:  # noqa: BLE001
            pass

    animate(window, duration_ms, frame, done)


def tween_number(
    widget: tk.Misc,
    start: float,
    end: float,
    duration_ms: int,
    on_frame: Callable[[float], None],
) -> None:
    """把某个数值从 start 平滑推到 end，每帧回调当前值。"""

    def frame(t: float) -> None:
        on_frame(start + (end - start) * ease_out_cubic(t))

    animate(widget, duration_ms, frame)
