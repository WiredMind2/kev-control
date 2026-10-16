from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from kev_control.slots import Text

__all__ = ["Writer"]


class Writer(Protocol):
    def draft(self, utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> Text | None:
        """None is an empty draft. Raises Unavailable(WRITER_MISSING)."""
        ...
