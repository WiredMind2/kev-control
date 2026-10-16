from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby

from kev_control.desktop import ElementKey, ElementRef, ElementState, Gone, OcrWord, Scan, VirtualRect
from kev_control.slots import Utterance, words

__all__ = ["Candidate", "Observation", "OcrCandidate", "UiaCandidate", "observe"]

_MAX_ICON_OVERLAP = 0.3


@dataclass(frozen=True)
class OcrCandidate:
    name: str
    rect: VirtualRect

    source = "ocr"
    role = "text"


@dataclass(frozen=True)
class UiaCandidate:
    name: str
    control_type: str
    rect: VirtualRect
    ref: ElementRef

    source = "uia"

    @property
    def role(self) -> str:
        return self.control_type


Candidate = OcrCandidate | UiaCandidate
"""An OCR candidate never carries an element and a UIA candidate always does."""


@dataclass(frozen=True)
class Observation:
    candidates: tuple[Candidate, ...]  # ranked, at most max_candidates. Position i is id c{i}.
    words: tuple[OcrWord, ...]  # every OCR word outside this process's windows, uncapped, for postconditions
    focused: ElementKey | None
    watched: ElementState | Gone | None

    @property
    def ocr_text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(c.name for c in self.candidates)


def observe(scan: Scan, utterance: Utterance, max_candidates: int) -> Observation:
    """Pure. Builds phrases, merges named icons, ranks, caps.

    OCR words whose center falls in scan.own_rects are dropped, so the tray tooltip that echoes the
    utterance can never become the best-scoring candidate. Controls are dropped when the name is empty,
    the pid is scan.own_pid, or IoU with any OCR phrase exceeds 0.3.
    Rank is shared-word count descending, then ocr before uia, then top, then left.
    """
    seen = tuple(w for w in scan.words if not any(r.contains(w.rect.center) for r in scan.own_rects))
    phrases = _phrases(seen)
    icons = [
        UiaCandidate(c.name, c.control_type, c.rect, c.ref)
        for c in scan.controls
        if c.name.strip()
        and c.pid != scan.own_pid
        and all(c.rect.iou(p.rect) <= _MAX_ICON_OVERLAP for p in phrases)
    ]
    wanted = set(words(utterance.text))

    def rank(c: Candidate) -> tuple[int, int, int, int]:
        shared = len(wanted & set(words(c.name)))
        return (-shared, 0 if isinstance(c, OcrCandidate) else 1, c.rect.top, c.rect.left)

    ranked = sorted([*phrases, *icons], key=rank)
    return Observation(tuple(ranked[:max_candidates]), seen, scan.focused, scan.watched)


def _phrases(scan_words: Sequence[OcrWord]) -> list[OcrCandidate]:
    # Words of one OCR line join into a phrase until a horizontal gap wider than the line's median word
    # height. Windows OCR returns "File Edit View" as one line, and its center would click "Edit".
    phrases: list[OcrCandidate] = []
    by_line = sorted(scan_words, key=lambda w: (w.line, w.rect.left))
    for _, line_iter in groupby(by_line, key=lambda w: w.line):
        line = list(line_iter)
        max_gap = statistics.median(w.rect.height for w in line)
        run = [line[0]]
        for prev, word in zip(line, line[1:]):
            if word.rect.left - prev.rect.right > max_gap:
                phrases.append(_join(run))
                run = []
            run.append(word)
        phrases.append(_join(run))
    return phrases


def _join(run: list[OcrWord]) -> OcrCandidate:
    left = min(w.rect.left for w in run)
    top = min(w.rect.top for w in run)
    right = max(w.rect.right for w in run)
    bottom = max(w.rect.bottom for w in run)
    return OcrCandidate(" ".join(w.text for w in run), VirtualRect(left, top, right - left, bottom - top))
