"""让窗口在高 DPI 屏幕上按原生分辨率绘制。

Windows 上如果程序不声明 DPI 感知，系统会把整个窗口当成一张位图放大
到系统缩放比例再贴到屏幕上。150% 缩放下，所有文字和 1px 细线都会被
强行插值，看起来就是「糊」——这不是配色或字体的问题，改样式也救不了。

必须在 `tk.Tk()` 之前调用，晚了窗口已经按旧模式创建好了。
"""

from __future__ import annotations

import sys


def enable() -> bool:
    """声明进程 DPI 感知。返回是否真的设置成功。

    优先用 `SetProcessDpiAwareness(2)`（per-monitor v2 之前的 per-monitor），
    老系统退回 `SetProcessDPIAware()`。两个都失败也不抛错——最坏情况就是
    维持原来的拉伸行为，不该因为一行系统调用挂掉整个程序。
    """
    if sys.platform != "win32":
        return False

    import ctypes

    try:
        # 1 = system aware, 2 = per monitor aware
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except Exception:  # noqa: BLE001 - Win7 没有 shcore
        pass

    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return True
    except Exception:  # noqa: BLE001
        pass

    return False
