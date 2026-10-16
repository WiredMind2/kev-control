"""Tray tooltip text. The icon reads this; tests call `render` and never open a window."""

from __future__ import annotations

__all__ = ["render"]


def render(armed: bool, hearing: bool, acting: bool, last: str) -> str:
    if not armed:
        return "Idle"
    if acting:
        return f"Acting: {last}"
    if hearing:
        return "Hearing"
    return "Armed"
