from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import NewType

__all__ = ["PREPOSITIONS", "TYPE_VERBS", "SessionId", "Text", "Utterance", "as_text", "payload", "words"]

Text = NewType("Text", str)
"""A non-blank string the app may type. Built only by as_text."""

TYPE_VERBS = frozenset({"type", "write", "enter", "put"})
PREPOSITIONS = frozenset({"in", "into", "on", "at"})

_TOKEN = re.compile(r"[a-z0-9]+")
_DOUBLE_QUOTED = re.compile(r'"([^"]*)"')
# A single quote opens only at the start or after whitespace and closes only before a non-word
# character or the end, so the apostrophe in "type don't panic in notes" is not a quote.
_SINGLE_QUOTED = re.compile(r"(?<!\S)'(.*?)'(?!\w)")


def as_text(s: str) -> Text | None:
    return Text(s) if s.strip() else None


def words(s: str) -> list[str]:
    """Lowercase `[a-z0-9]+` tokens. The one tokenizer for ranking and for OCR read-back."""
    return _TOKEN.findall(s.lower())


def payload(utterance_text: str) -> Text | None:
    """The text the user spoke for typing, or None when they did not say it.

    1. The first quoted span, single or double quotes.
    2. Otherwise the words between a leading verb in TYPE_VERBS and the first PREPOSITIONS word after it.
    """
    quoted = [m for m in (_DOUBLE_QUOTED.search(utterance_text), _SINGLE_QUOTED.search(utterance_text)) if m]
    if quoted:
        return as_text(min(quoted, key=lambda m: m.start()).group(1).strip())
    tokens = utterance_text.split()
    if not tokens or _bare(tokens[0]) not in TYPE_VERBS:
        return None
    for i, token in enumerate(tokens[1:], start=1):
        if _bare(token) in PREPOSITIONS:
            return as_text(" ".join(tokens[1:i]))
    return None


def _bare(token: str) -> str:
    return token.lower().strip(string.punctuation)


SessionId = NewType("SessionId", int)
"""Minted only by Arm. Defined here so slots stays a leaf module."""


@dataclass(frozen=True)
class Utterance:
    session: SessionId
    text: str
    payload: Text | None

    @staticmethod
    def heard(session: SessionId, transcript: str) -> Utterance | None:
        """None for a blank transcript, so an empty transcription starts no loop."""
        text = transcript.strip()
        return Utterance(session, text, payload(text)) if text else None
