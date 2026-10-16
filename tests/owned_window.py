"""A Win32 window this project owns, with a button and an edit, on its own thread."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from types import TracebackType

from kev_control.desktop import VirtualRect
from kev_control.win_desktop import window_rect

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_WS_OVERLAPPEDWINDOW = 0x00CF0000
_WS_VISIBLE = 0x10000000
_WS_CHILD = 0x40000000
_WS_BORDER = 0x00800000
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_COMMAND = 0x0111
_WM_GETTEXT = 0x000D
_WM_GETTEXTLENGTH = 0x000E
_BN_CLICKED = 0
_BUTTON_ID = 101
_CLASS = "KevOwnedWindow"

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.DestroyWindow.restype = wintypes.BOOL
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
_user32.DispatchMessageW.restype = ctypes.c_ssize_t
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
_user32.SendMessageW.restype = ctypes.c_ssize_t
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

_clicks: dict[int, int] = {}
_registered = False


def _proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    if msg == _WM_COMMAND and (wparam >> 16) & 0xFFFF == _BN_CLICKED and (wparam & 0xFFFF) == _BUTTON_ID:
        _clicks[int(hwnd)] = _clicks.get(int(hwnd), 0) + 1
        return 0
    if msg == _WM_DESTROY:
        _user32.PostQuitMessage(0)
        return 0
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_PROC = _WNDPROC(_proc)


def _register() -> None:
    global _registered
    if _registered:
        return
    cls = _WNDCLASSW()
    cls.lpfnWndProc = _PROC
    cls.hInstance = _kernel32.GetModuleHandleW(None)
    cls.lpszClassName = _CLASS
    cls.hbrBackground = 6  # COLOR_WINDOW + 1
    if not _user32.RegisterClassW(ctypes.byref(cls)):
        err = ctypes.get_last_error()
        if err != 1410:  # class already exists
            raise OSError(err, "RegisterClassW failed")
    _registered = True


def _create(class_name: str, title: str, style: int, x: int, y: int, w: int, h: int, parent: int, child_id: int) -> int:
    hwnd = _user32.CreateWindowExW(0, class_name, title, style, x, y, w, h, parent or None, child_id or None, _kernel32.GetModuleHandleW(None), None)
    if not hwnd:
        raise OSError(ctypes.get_last_error(), f"CreateWindowExW failed for {class_name}")
    return int(hwnd)


class OwnedWindow:
    def __init__(self, button: str, edit_label: str) -> None:
        self._button_title = button
        self._edit_label = edit_label
        self.hwnd = 0
        self.button_hwnd = 0
        self.edit_hwnd = 0
        self.label_hwnd = 0
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="kev-owned-window", daemon=True)

    def __enter__(self) -> OwnedWindow:
        self._thread.start()
        if not self._ready.wait(5):
            raise TimeoutError("owned window did not open")
        if self._error is not None:
            raise self._error
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, _WM_CLOSE, 0, 0)
        self._thread.join(5)

    def _run(self) -> None:
        try:
            _register()
            self.hwnd = _create(_CLASS, "Kev test", _WS_OVERLAPPEDWINDOW | _WS_VISIBLE, 200, 200, 420, 220, 0, 0)
            child = _WS_CHILD | _WS_VISIBLE
            self.button_hwnd = _create("BUTTON", self._button_title, child, 16, 16, 100, 32, self.hwnd, _BUTTON_ID)
            self.label_hwnd = _create("STATIC", self._edit_label, child, 16, 60, 80, 24, self.hwnd, 103)
            self.edit_hwnd = _create("EDIT", "", child | _WS_BORDER, 100, 56, 220, 28, self.hwnd, 102)
            _user32.ShowWindow(self.hwnd, 5)
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        msg = _MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def button_presses(self) -> int:
        return _clicks.get(self.hwnd, 0)

    def edit_text(self) -> str:
        length = int(_user32.SendMessageW(self.edit_hwnd, _WM_GETTEXTLENGTH, 0, None))
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.SendMessageW(self.edit_hwnd, _WM_GETTEXT, length + 1, ctypes.addressof(buf))
        return buf.value

    def button_rect(self) -> VirtualRect:
        return window_rect(self.button_hwnd)

    def edit_rect(self) -> VirtualRect:
        return window_rect(self.edit_hwnd)

    def focus(self) -> None:
        _user32.ShowWindow(self.hwnd, 9)  # SW_RESTORE
        _user32.SetForegroundWindow(self.hwnd)


def owned_window(button: str, edit_label: str) -> OwnedWindow:
    return OwnedWindow(button, edit_label)
