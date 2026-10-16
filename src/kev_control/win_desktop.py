"""The only module that may capture the screen or inject input."""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from typing import assert_never

from kev_control.arm import Gate
from kev_control.desktop import (
    ICON_CONTROL_TYPES,
    ClickAt,
    ElementInfo,
    ElementKey,
    ElementRef,
    ElementState,
    FocusAndType,
    Gone,
    Invoke,
    OcrWord,
    Performed,
    Plan,
    Point,
    Scan,
    SetValue,
    UiaControl,
    ValueCap,
    VirtualRect,
)
from kev_control.ending import Ending, Unavailable
from kev_control.slots import Text

__all__ = ["WinDesktop", "claim_per_monitor_v2", "element_center", "injection_enabled", "window_rect"]

_UIA_INVOKE = 10000
_UIA_VALUE = 10002
_UIA_TEXT = 10014
_EDIT = 50004
_DOCUMENT = 50030
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_ICON_NAMES = {50000: "Button", 50031: "SplitButton", 50006: "Image"}
_SRCCOPY = 0x00CC0020
_OWN_WINDOW_CLASS = "KevOwnedWindow"

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


def injection_enabled() -> bool:
    """The app injects only when this is true. Tests set KEV_CONTROL_INJECT=0."""
    return os.environ.get("KEV_CONTROL_INJECT", "1") != "0"


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


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_user32.SetCursorPos.restype = wintypes.BOOL
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT


class _UiaRef:
    """Opaque handle. Only WinDesktop reads the COM pointer inside it."""

    def __init__(self, element: object) -> None:
        self.element = element


def _send(*inputs: _INPUT) -> None:
    if not injection_enabled():
        raise RuntimeError("computer control is disabled")
    packed = (_INPUT * len(inputs))(*inputs)
    sent = _user32.SendInput(len(inputs), packed, ctypes.sizeof(_INPUT))
    if sent != len(inputs):
        raise OSError(ctypes.get_last_error(), "SendInput failed")


def _mouse(flags: int) -> _INPUT:
    event = _INPUT(type=_INPUT_MOUSE)
    event.u.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
    return event


class WinDesktop:
    """One thread's UI Automation client. Create it on the thread that calls it."""

    def __init__(self) -> None:
        import comtypes
        import comtypes.client
        from comtypes.gen import UIAutomationClient as uia

        comtypes.client.GetModule("UIAutomationCore.dll")
        comtypes.CoInitialize()
        self._uia_mod = uia
        self._uia = comtypes.CoCreateInstance(
            uia.CUIAutomation._reg_clsid_,
            interface=uia.IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
        self.withheld: list[Plan] = []

    def scan(self, watch: ElementRef | None) -> Scan:
        words = _ocr_words()
        controls = tuple(self._named_icons(_foreground_hwnd()) + self._named_icons(_taskbar_hwnd()))
        if watch is None:
            watched: ElementState | Gone | None = None
        else:
            info = self.inspect(watch)
            watched = Gone.GONE if info is None else info.state
        return Scan(
            words=tuple(words),
            controls=controls,
            own_pid=os.getpid(),
            own_rects=_own_rects(),
            focused=self._focused_key(),
            watched=watched,
        )

    def inspect(self, at: ElementRef | Point) -> ElementInfo | None:
        element = at.element if isinstance(at, _UiaRef) else self._element_at(at)
        if element is None:
            return None
        return self._info(element)

    def perform(self, plan: Plan, gate: Gate) -> Performed:
        if not gate():
            return Performed.DISARMED
        if not injection_enabled():
            self.withheld.append(plan)
            return Performed.DISARMED
        match plan:
            case Invoke(element=ref):
                if not gate():
                    return Performed.DISARMED
                self._invoke(ref)
            case SetValue(element=ref, text=text):
                if not gate():
                    return Performed.DISARMED
                self._set_value(ref, text)
            case ClickAt(point=point):
                if not gate():
                    return Performed.DISARMED
                self._click_at(point)
            case FocusAndType(element=ref, text=text):
                if not gate():
                    return Performed.DISARMED
                if not self._focus(ref):
                    return Performed.FOCUS_REFUSED
                if not gate():
                    return Performed.DISARMED
                self._type_unicode(text)
            case _:
                assert_never(plan)
        return Performed.INJECTED

    def _named_icons(self, hwnd: int) -> list[UiaControl]:
        if not hwnd:
            return []
        root = self._uia.ElementFromHandle(hwnd)
        if not root:
            return []
        found = root.FindAll(4, self._uia.CreateTrueCondition())  # TreeScope_Descendants
        icons: list[UiaControl] = []
        for index in range(int(found.Length)):
            element = found.GetElement(index)
            name = str(element.CurrentName or "").strip()
            kind = _ICON_NAMES.get(int(element.CurrentControlType))
            if not name or kind not in ICON_CONTROL_TYPES:
                continue
            icons.append(
                UiaControl(name, kind, _bounds(element), int(element.CurrentProcessId), _UiaRef(element))
            )
        return icons

    def _focused_key(self) -> ElementKey | None:
        focused = self._uia.GetFocusedElement()
        if not focused:
            return None
        try:
            return _runtime_id(focused)
        except (OSError, TypeError, ValueError):
            return None

    def _element_at(self, point: Point) -> object | None:
        found = self._uia.ElementFromPoint(self._uia_mod.tagPOINT(point.x, point.y))
        return found or None

    def _info(self, element: object) -> ElementInfo:
        rect = _bounds(element)
        value = _pattern(element, _UIA_VALUE, self._uia_mod.IUIAutomationValuePattern)
        return ElementInfo(
            ref=_UiaRef(element),
            key=_runtime_id(element),
            rect=rect,
            is_password=bool(element.CurrentIsPassword),
            can_invoke=_pattern(element, _UIA_INVOKE, self._uia_mod.IUIAutomationInvokePattern) is not None,
            value=_value_cap(value),
            editable=_editable(element, self._uia_mod),
            state=ElementState(toggle=None, expand=None, selected=None, text=_read_text(element, value, self._uia_mod)),
        )

    def _invoke(self, ref: ElementRef) -> None:
        if not injection_enabled():
            raise RuntimeError("computer control is disabled")
        pattern = _pattern(ref.element, _UIA_INVOKE, self._uia_mod.IUIAutomationInvokePattern)
        if pattern is None:
            raise OSError("element has no invoke pattern")
        pattern.Invoke()

    def _set_value(self, ref: ElementRef, text: Text) -> None:
        if not injection_enabled():
            raise RuntimeError("computer control is disabled")
        pattern = _pattern(ref.element, _UIA_VALUE, self._uia_mod.IUIAutomationValuePattern)
        if pattern is None:
            raise OSError("element has no value pattern")
        pattern.SetValue(str(text))

    def _click_at(self, point: Point) -> None:
        if not injection_enabled():
            raise RuntimeError("computer control is disabled")
        if not _user32.SetCursorPos(point.x, point.y):
            raise OSError(ctypes.get_last_error(), "SetCursorPos failed")
        _send(_mouse(_MOUSEEVENTF_LEFTDOWN), _mouse(_MOUSEEVENTF_LEFTUP))

    def _focus(self, ref: ElementRef) -> bool:
        if not injection_enabled():
            raise RuntimeError("computer control is disabled")
        element = ref.element
        element.SetFocus()
        focused = self._uia.GetFocusedElement()
        return bool(focused is not None and self._uia.CompareElements(element, focused))

    def _type_unicode(self, text: Text) -> None:
        if not injection_enabled():
            raise RuntimeError("computer control is disabled")
        units = str(text).encode("utf-16-le")
        events: list[_INPUT] = []
        for index in range(0, len(units), 2):
            code = int.from_bytes(units[index : index + 2], "little")
            down = _INPUT(type=_INPUT_KEYBOARD)
            down.u.ki = _KEYBDINPUT(0, code, _KEYEVENTF_UNICODE, 0, None)
            up = _INPUT(type=_INPUT_KEYBOARD)
            up.u.ki = _KEYBDINPUT(0, code, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0, None)
            events.extend((down, up))
        if events:
            _send(*events)


def _pattern(element: object, pattern_id: int, interface: type) -> object | None:
    try:
        unknown = element.GetCurrentPattern(pattern_id)
    except OSError:
        return None
    if not unknown:
        return None
    return unknown.QueryInterface(interface)


def _value_cap(value: object | None) -> ValueCap:
    if value is None:
        return ValueCap.NONE
    return ValueCap.READ_ONLY if value.CurrentIsReadOnly else ValueCap.WRITABLE


def _editable(element: object, uia: object) -> bool:
    control = int(element.CurrentControlType)
    if control in (_EDIT, _DOCUMENT) and bool(element.CurrentIsKeyboardFocusable):
        return True
    return _pattern(element, _UIA_TEXT, uia.IUIAutomationTextPattern) is not None


def _read_text(element: object, value: object | None, uia: object) -> str | None:
    if value is not None:
        return str(value.CurrentValue)
    text = _pattern(element, _UIA_TEXT, uia.IUIAutomationTextPattern)
    if text is not None:
        return str(text.DocumentRange.GetText(-1))
    return None


def _runtime_id(element: object) -> ElementKey:
    raw = element.GetRuntimeId()
    return ElementKey(tuple(int(part) for part in raw))


def _bounds(element: object) -> VirtualRect:
    rect = element.CurrentBoundingRectangle
    left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    return VirtualRect(left, top, max(0, right - left), max(0, bottom - top))


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(_RECT), wintypes.LPARAM
)
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.ReleaseDC.restype = ctypes.c_int
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MONITORENUMPROC, wintypes.LPARAM]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
_gdi32.BitBlt.restype = wintypes.BOOL
_gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
]
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteObject.restype = wintypes.BOOL
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_gdi32.DeleteDC.restype = wintypes.BOOL


def _foreground_hwnd() -> int:
    return int(_user32.GetForegroundWindow() or 0)


def _taskbar_hwnd() -> int:
    return int(_user32.FindWindowW("Shell_TrayWnd", None) or 0)


def _own_rects() -> tuple[VirtualRect, ...]:
    """Tray and other windows of this process. The owned test window stays visible to OCR."""
    rects: list[VirtualRect] = []

    def visit(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) != os.getpid():
            return True
        name = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, name, 256)
        if name.value == _OWN_WINDOW_CLASS:
            return True
        rects.append(window_rect(int(hwnd)))
        return True

    callback = _WNDENUMPROC(visit)
    _user32.EnumWindows(callback, 0)
    return tuple(rects)


def _monitors() -> list[VirtualRect]:
    found: list[VirtualRect] = []

    def visit(monitor: int, _hdc: int, _rect: object, _data: int) -> bool:
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.rcMonitor
            found.append(VirtualRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
        return True

    callback = _MONITORENUMPROC(visit)
    _user32.EnumDisplayMonitors(None, None, callback, 0)
    return found


def _capture(rect: VirtualRect) -> bytes:
    screen = _user32.GetDC(None)
    memory = _gdi32.CreateCompatibleDC(screen)
    bitmap = _gdi32.CreateCompatibleBitmap(screen, rect.width, rect.height)
    old = _gdi32.SelectObject(memory, bitmap)
    if not _gdi32.BitBlt(memory, 0, 0, rect.width, rect.height, screen, rect.left, rect.top, _SRCCOPY):
        raise OSError(ctypes.get_last_error(), "BitBlt failed")
    info = _BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    info.biWidth = rect.width
    info.biHeight = -rect.height
    info.biPlanes = 1
    info.biBitCount = 32
    buf = ctypes.create_string_buffer(rect.width * rect.height * 4)
    _gdi32.GetDIBits(memory, bitmap, 0, rect.height, buf, ctypes.byref(info), 0)
    _gdi32.SelectObject(memory, old)
    _gdi32.DeleteObject(bitmap)
    _gdi32.DeleteDC(memory)
    _user32.ReleaseDC(None, screen)
    return buf.raw


def _wait_ocr(operation: object) -> object:
    """STA threads cannot block on IAsyncOperation.get. The completion callback is free to."""
    done = threading.Event()
    holder: dict[str, object] = {}

    def finished(op: object, _status: object) -> None:
        try:
            holder["result"] = op.get_results()  # type: ignore[attr-defined]
        except Exception as exc:
            holder["error"] = exc
        done.set()

    operation.completed = finished  # type: ignore[attr-defined]
    if not done.wait(30):
        raise TimeoutError("Windows OCR did not finish")
    if "error" in holder:
        raise holder["error"]
    return holder["result"]


def _ocr_words() -> list[OcrWord]:
    try:
        from PIL import Image
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter
    except ImportError as exc:
        raise Unavailable(Ending.OCR_MISSING) from exc
    engine = OcrEngine.try_create_from_language(Language("en-US"))
    if engine is None:
        raise Unavailable(Ending.OCR_MISSING)
    words: list[OcrWord] = []
    line_no = 0
    for monitor in _monitors():
        raw = _capture(monitor)
        image = Image.frombuffer("RGBA", (monitor.width, monitor.height), raw, "raw", "BGRA", 0, 1)
        scaled = image.resize((monitor.width * 2, monitor.height * 2), Image.Resampling.LANCZOS)
        writer = DataWriter()
        writer.write_bytes(scaled.tobytes("raw", "BGRA"))
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, scaled.width, scaled.height
        )
        result = _wait_ocr(engine.recognize_async(bitmap))
        for line in result.lines:
            for word in line.words:
                box = word.bounding_rect
                words.append(
                    OcrWord(
                        str(word.text),
                        VirtualRect(
                            monitor.left + int(box.x) // 2,
                            monitor.top + int(box.y) // 2,
                            max(1, int(box.width) // 2),
                            max(1, int(box.height) // 2),
                        ),
                        line_no,
                    )
                )
            line_no += 1
    return words
