from __future__ import annotations

import threading
from collections.abc import Callable

from kev_control.slots import SessionId, Utterance

__all__ = ["Mailbox"]


class Mailbox:
    """One pending utterance between Ear and Worker. A put replaces whatever is waiting.

    take() skips utterances whose session is no longer live, so disarm empties the slot without
    anyone clearing it.
    """

    def __init__(self, live: Callable[[SessionId], bool]) -> None:
        self._live = live
        self._slot: Utterance | None = None
        self._filled = threading.Condition()

    def put(self, utterance: Utterance) -> None:
        with self._filled:
            self._slot = utterance
            self._filled.notify()

    def take(self) -> Utterance:
        with self._filled:
            while True:
                self._filled.wait_for(lambda: self._slot is not None)
                utterance, self._slot = self._slot, None
                if utterance is not None and self._live(utterance.session):
                    return utterance

    def peek(self) -> Utterance | None:
        utterance = self._slot
        return utterance if utterance is not None and self._live(utterance.session) else None
