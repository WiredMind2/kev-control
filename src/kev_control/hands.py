from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import assert_never

from kev_control.arm import Gate
from kev_control.desktop import (
    ClickAt,
    Desktop,
    ElementInfo,
    ElementRef,
    FocusAndType,
    Invoke,
    Performed,
    Plan,
    Point,
    SetValue,
    ValueCap,
)
from kev_control.eyes import Candidate, OcrCandidate, UiaCandidate
from kev_control.slots import Text

__all__ = ["Click", "Decline", "Declined", "Disarmed", "Injected", "Intent", "Receipt", "Type", "act", "plan"]


@dataclass(frozen=True)
class Click:
    candidate: Candidate


@dataclass(frozen=True)
class Type:
    candidate: Candidate
    text: Text


Intent = Click | Type
"""Typed text is non-empty by construction, so an empty draft cannot reach Hands."""


class Decline(enum.Enum):
    PASSWORD = "password"
    CANNOT_ACCEPT_TEXT = "cannot_accept_text"


@dataclass(frozen=True)
class Injected:
    intent: Intent
    plan: Plan
    element: ElementInfo | None  # None only for a click where nothing answered at the point


@dataclass(frozen=True)
class Declined:
    reason: Decline


@dataclass(frozen=True)
class Disarmed:
    pass


Receipt = Injected | Declined | Disarmed


def plan(intent: Intent, element: ElementInfo | None) -> Plan | Decline:
    """Pure decision table.

    A click is Invoke when the element supports it, else ClickAt the candidate's center.
    A type with no element is CANNOT_ACCEPT_TEXT. A password is PASSWORD. A writable value is SetValue.
    An editable element is FocusAndType. Anything else is CANNOT_ACCEPT_TEXT.
    """
    match intent:
        case Click(candidate=c):
            if element is not None and element.can_invoke:
                return Invoke(element.ref)
            return ClickAt(c.rect.center)
        case Type(text=text):
            if element is None:
                return Decline.CANNOT_ACCEPT_TEXT
            if element.is_password:
                return Decline.PASSWORD
            if element.value is ValueCap.WRITABLE:
                return SetValue(element.ref, text)
            if element.editable:
                return FocusAndType(element.ref, element.key, text)
            return Decline.CANNOT_ACCEPT_TEXT
        case _:
            assert_never(intent)


def act(desktop: Desktop, intent: Intent, gate: Gate) -> Receipt:
    """Resolve, plan, perform. Stateless across steps."""
    at: ElementRef | Point
    match intent.candidate:
        case UiaCandidate(ref=ref):
            at = ref
        case OcrCandidate(rect=rect):
            at = rect.center
        case _:
            assert_never(intent.candidate)
    element = desktop.inspect(at)
    chosen = plan(intent, element)
    if isinstance(chosen, Decline):
        return Declined(chosen)
    match desktop.perform(chosen, gate):
        case Performed.INJECTED:
            return Injected(intent, chosen, element)
        case Performed.DISARMED:
            return Disarmed()
        case Performed.FOCUS_REFUSED:
            # Keys would land in whatever control kept focus, so this is a decline, not an injection.
            return Declined(Decline.CANNOT_ACCEPT_TEXT)
