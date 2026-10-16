"""The Windows seam's types. The only module allowed to touch UIA, Windows OCR, capture, or SendInput."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import NewType, Protocol

from kev_control.arm import Gate
from kev_control.slots import Text

__all__ = [
    "ICON_CONTROL_TYPES",
    "ClickAt",
    "Desktop",
    "ElementInfo",
    "ElementKey",
    "ElementRef",
    "ElementState",
    "FocusAndType",
    "Gone",
    "Invoke",
    "OcrWord",
    "Performed",
    "Plan",
    "Point",
    "Scan",
    "SetValue",
    "UiaControl",
    "ValueCap",
    "VirtualRect",
]


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class VirtualRect:
    """Physical pixels in virtual-screen space.

    The origin is the primary monitor's top-left, so left and top go negative on monitors placed
    left of or above it. OCR boxes, UIA rectangles, and click points all live in this one space.
    """

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center(self) -> Point:
        return Point(self.left + self.width // 2, self.top + self.height // 2)

    def iou(self, other: VirtualRect) -> float:
        overlap_w = max(0, min(self.right, other.right) - max(self.left, other.left))
        overlap_h = max(0, min(self.bottom, other.bottom) - max(self.top, other.top))
        overlap = overlap_w * overlap_h
        union = self.width * self.height + other.width * other.height - overlap
        return overlap / union if union > 0 else 0.0

    def near(self, other: VirtualRect, tolerance: int) -> bool:
        """Each of the four edges within tolerance pixels."""
        return (
            abs(self.left - other.left) <= tolerance
            and abs(self.top - other.top) <= tolerance
            and abs(self.right - other.right) <= tolerance
            and abs(self.bottom - other.bottom) <= tolerance
        )

    def contains(self, p: Point) -> bool:
        return self.left <= p.x < self.right and self.top <= p.y < self.bottom


ElementKey = NewType("ElementKey", tuple[int, ...])
"""UIA RuntimeId. Equal keys mean the same live element."""


class ElementRef(Protocol):
    """Opaque element handle. Only the Desktop that minted it can read or act on it."""


@dataclass(frozen=True)
class OcrWord:
    text: str
    rect: VirtualRect
    line: int  # index of the OCR line this word came from, unique within one scan


@dataclass(frozen=True)
class UiaControl:
    name: str
    control_type: str
    rect: VirtualRect
    pid: int
    ref: ElementRef


@dataclass(frozen=True)
class ElementState:
    """What postconditions compare. None means the element lacks that pattern."""

    toggle: str | None
    expand: str | None
    selected: bool | None
    text: str | None  # first of ValuePattern, TextPattern, LegacyIAccessible that exists. "" is the text.


class Gone(enum.Enum):
    GONE = "gone"


@dataclass(frozen=True)
class Scan:
    """One raw read of the screen. Eyes turns it into an Observation."""

    words: tuple[OcrWord, ...]
    controls: tuple[UiaControl, ...]  # ICON_CONTROL_TYPES under the foreground window and the taskbar
    own_pid: int
    own_rects: tuple[VirtualRect, ...]  # this process's visible windows, such as the tray tooltip and menu
    focused: ElementKey | None
    watched: ElementState | Gone | None  # state of the element passed as `watch`, None when nothing was watched


ICON_CONTROL_TYPES = frozenset({"Button", "SplitButton", "Image"})


class ValueCap(enum.Enum):
    NONE = "none"
    READ_ONLY = "read_only"
    WRITABLE = "writable"


@dataclass(frozen=True)
class ElementInfo:
    """What Hands needs to choose a plan for one element, read just before acting."""

    ref: ElementRef
    key: ElementKey
    rect: VirtualRect
    is_password: bool
    can_invoke: bool
    value: ValueCap
    editable: bool  # keyboard-focusable Edit or Document, or exposes TextPattern
    state: ElementState


@dataclass(frozen=True)
class Invoke:
    element: ElementRef


@dataclass(frozen=True)
class ClickAt:
    point: Point


@dataclass(frozen=True)
class SetValue:
    element: ElementRef
    text: Text


@dataclass(frozen=True)
class FocusAndType:
    element: ElementRef
    key: ElementKey
    text: Text


Plan = Invoke | ClickAt | SetValue | FocusAndType
"""Every input the app can send. There is no right-click, drag, scroll, shortcut, or shell variant."""


class Performed(enum.Enum):
    INJECTED = "injected"
    DISARMED = "disarmed"
    FOCUS_REFUSED = "focus_refused"


class Desktop(Protocol):
    """The Windows seam. One instance belongs to one thread, because UIA COM objects are apartment-bound."""

    def scan(self, watch: ElementRef | None) -> Scan:
        """Raises Unavailable(OCR_MISSING) when the en-US OCR engine cannot be created."""
        ...

    def inspect(self, at: ElementRef | Point) -> ElementInfo | None:
        """The element itself, or the element at a point. None when nothing is there."""
        ...

    def perform(self, plan: Plan, gate: Gate) -> Performed:
        """The only code path in the package that changes another app.

        Checks gate immediately before each mutating call, so a disarm between focusing and typing
        still sends no keys.
        """
        ...
