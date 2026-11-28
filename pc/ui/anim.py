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


def ease_in_out_cubic(t: float) -> float:
    """两头慢、中间快。来回式的动画（呼吸、脉冲）用这个更自然。"""
    t = min(1.0, max(0.0, t))
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def ease_out_back(t: float) -> float:
    """冲过一点再回弹。用于「卡片落下」这种要有一点弹性的动作。"""
    t = min(1.0, max(0.0, t))
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * ((t - 1.0) ** 3) + c1 * ((t - 1.0) ** 2)


# -- 颜色 -----------------------------------------------------------------


def _parse(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def lerp_color(start: str, end: str, t: float) -> str:
    """在两个 `#rrggbb` 之间插值。t 会被夹到 0..1。"""
    t = min(1.0, max(0.0, t))
    sr, sg, sb = _parse(start)
    er, eg, eb = _parse(end)
    return "#{:02X}{:02X}{:02X}".format(
        int(round(sr + (er - sr) * t)),
        int(round(sg + (eg - sg) * t)),
        int(round(sb + (eb - sb) * t)),
    )


def lerp(start: float, end: float, t: float) -> float:
    """数值插值。t 夹 0..1。"""
    t = min(1.0, max(0.0, t))
    return start + (end - start) * t


# -- 驱动 -----------------------------------------------------------------

#: 记录正在跑的动画，用来做「同一控件只留一条」和取消。
_ANIMATIONS: dict[tk.Misc, dict[str, object]] = {}


def animate(
    widget: tk.Misc,
    duration_ms: int,
    on_frame: Callable[[float], None],
    on_done: Optional[Callable[[], None]] = None,
) -> None:
    """在 `duration_ms` 内把进度从 0 推到 1，每帧回调。

    同一个控件上再启动新动画会先取消旧的——否则鼠标快速划过一排按钮时，
    每个按钮上都会残留一条往回跑的动画，颜色会乱闪。
    """
    _cancel(widget)
    if duration_ms <= 0:
        on_frame(1.0)
        if on_done is not None:
            on_done()
        return

    start = time.perf_counter()
    state: dict[str, object] = {"after": None}

    def step() -> None:
        if not widget.winfo_exists():
            _ANIMATIONS.pop(widget, None)
            return
        elapsed = (time.perf_counter() - start) * 1000.0
        t = min(1.0, elapsed / duration_ms)
        try:
            on_frame(t)
        except tk.TclError:
            _ANIMATIONS.pop(widget, None)
            return
        if t >= 1.0:
            state["after"] = None
            _ANIMATIONS.pop(widget, None)
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


def stop(widget: tk.Misc) -> None:
    """停掉某个控件上正在跑的动画。控件要被销毁前调一下更干净。"""
    _cancel(widget)


def fade_in_window(window: tk.Misc, duration_ms: int = 150) -> None:
    """窗口淡入。Windows 上 Toplevel 与 Tk 都支持 `-alpha`。"""
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


def fade_out_window(
    window: tk.Misc,
    on_done: Callable[[], None],
    duration_ms: int = 120,
) -> None:
    """窗口淡出，结束后调用 `on_done`（通常是 `destroy`）。

    关窗时直接消失会显得很生硬，尤其是刚点完「保存」那种需要确认结果的
    场景。淡出期间窗口仍在，但已经不吃点击了（调用方负责 `grab_release`）。

    系统关掉动画、或者窗口管理器不支持 alpha 时，直接执行 `on_done`。
    """
    if reduce_motion():
        on_done()
        return
    try:
        window.attributes("-alpha", 1.0)
    except Exception:  # noqa: BLE001 - 某些窗口管理器不支持
        on_done()
        return

    def frame(t: float) -> None:
        try:
            window.attributes("-alpha", 1.0 - ease_out_quad(t))
        except Exception:  # noqa: BLE001
            pass

    def done() -> None:
        on_done()

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


def pulse(
    widget: tk.Misc,
    on_frame: Callable[[float], None],
    period_ms: int = 1600,
) -> None:
    """无限循环的呼吸效果，`on_frame` 收到 0→1→0 的三角波。

    用户关掉系统动画时什么都不做（不是让步进一次，是彻底静止）。
    """
    if reduce_motion():
        return

    start = time.perf_counter()
    state: dict[str, object] = {"after": None}

    def step() -> None:
        if not widget.winfo_exists():
            _ANIMATIONS.pop(widget, None)
            return
        elapsed = (time.perf_counter() - start) * 1000.0
        phase = (elapsed % period_ms) / period_ms
        # 0→1→0：前半程升，后半程降
        t = phase * 2.0 if phase < 0.5 else (1.0 - phase) * 2.0
        try:
            on_frame(ease_in_out_cubic(t))
        except tk.TclError:
            _ANIMATIONS.pop(widget, None)
            return
        state["after"] = widget.after(FRAME_MS, step)

    step()
    _ANIMATIONS[widget] = state
