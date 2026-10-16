from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from typing import Protocol

from kev_control.slots import SessionId

__all__ = ["Arm", "Gate"]

_VK_CAPITAL = 0x14


class Gate(Protocol):
    """True while the session that minted this gate is still armed."""

    def __call__(self) -> bool: ...


def _caps_toggle_bit() -> bool:
    return bool(ctypes.windll.user32.GetKeyState(_VK_CAPITAL) & 1)


class Arm:
    """Sole reader of Caps Lock and sole writer of the session id.

    Each off-to-on edge seen by the poll mints the next SessionId. The next on-to-off edge ends it.
    Work carries the id it started under, so a result from an old session can never act inside a newer
    one, even when Caps Lock went off and on again while a Kev call was in flight.
    """

    def __init__(self, read_toggle: Callable[[], bool] = _caps_toggle_bit, period_s: float = 0.05) -> None:
        self._read = read_toggle
        self._period_s = period_s
        self._changed = threading.Condition()
        self._session: SessionId | None = None
        self._minted = 0

    def run(self) -> None:
        """Thread body. Polls forever."""
        while True:
            self._observe(self._read())
            time.sleep(self._period_s)

    def _observe(self, on: bool) -> None:
        with self._changed:
            if on and self._session is None:
                self._minted += 1
                self._session = SessionId(self._minted)
                self._changed.notify_all()
            elif not on:
                self._session = None

    def current(self) -> SessionId | None:
        return self._session

    def live(self, session: SessionId) -> bool:
        # Re-reads the toggle bit instead of trusting the last poll, so the check right before
        # injecting is fresh, not up to one period old.
        return self._read() and self._session == session

    def gate(self, session: SessionId) -> Gate:
        return lambda: self.live(session)

    def wait_armed(self, timeout_s: float) -> SessionId | None:
        with self._changed:
            self._changed.wait_for(lambda: self._session is not None, timeout_s)
            return self._session
