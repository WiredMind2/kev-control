"""The only module that may capture the screen or inject input."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from kev_control.desktop import Point, VirtualRect

__all__ = ["claim_per_monitor_v2", "element_center"]

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_claimed = False


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


_user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL


def claim_per_monitor_v2() -> None:
    """Must run before any window, COM object, or capture. -4 is PER_MONITOR_AWARE_V2."""
    global _claimed
    if _claimed:
        return
    _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    _claimed = True


def window_rect(hwnd: int) -> VirtualRect:
    rect = _RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "GetWindowRect failed")
    return VirtualRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def element_center(hwnd: int) -> Point:
    return window_rect(hwnd).center
