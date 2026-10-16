from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from kev_control.arm import Gate
from kev_control.config import Config
from kev_control.decider import Action, Decider, Decision, Done, OffTarget, Pick, Stuck
from kev_control.desktop import Desktop, ElementState, Gone, OcrWord, VirtualRect
from kev_control.ending import Ending, Unavailable
from kev_control.eyes import Observation, observe
from kev_control.hands import Click, Decline, Declined, Disarmed, Injected, Intent, Type, act
from kev_control.slots import Text, Utterance, words
from kev_control.writer import Writer

__all__ = ["MissKey", "Progress", "Rig", "compose", "judge", "run_utterance", "succeeded"]

_REPEAT_TOLERANCE_PX = 4
_READ_BACK_TAIL = 6


@dataclass(frozen=True)
class Rig:
    desktop: Desktop
    decider: Decider
    writer: Writer


@dataclass(frozen=True)
class MissKey:
    """What a miss tried. The next intent that matches it is refused without injecting."""

    action: Action
    text: Text | None
    rect: VirtualRect

    def matches(self, intent: Intent) -> bool:
        """Same action, same text, rectangle within 4 px on each edge."""
        other = _key(intent)
        return (
            other.action is self.action
            and other.text == self.text
            and other.rect.near(self.rect, _REPEAT_TOLERANCE_PX)
        )


def _key(intent: Intent) -> MissKey:
    match intent:
        case Click(candidate=c):
            return MissKey(Action.CLICK, None, c.rect)
        case Type(candidate=c, text=text):
            return MissKey(Action.TYPE, text, c.rect)
        case _:
            assert_never(intent)


@dataclass(frozen=True)
class Progress:
    """Loop state between steps.

    attempts counts every step where Kev picked a candidate, injected or not.
    last_miss is set by a miss and cleared by a hit, so a second miss in a row is the only way
    to reach UNCHANGED. The field is both the miss count and the refusal key.
    """

    attempts: int = 0
    last_miss: MissKey | None = None

    def refuses(self, intent: Intent) -> bool:
        return self.last_miss is not None and self.last_miss.matches(intent)

    def record(self, miss: MissKey | None) -> Progress | Ending:
        """attempts + 1. A miss while last_miss is set returns Ending.UNCHANGED."""
        if miss is not None and self.last_miss is not None:
            return Ending.UNCHANGED
        return Progress(self.attempts + 1, miss)


def judge(decision: Decision, progress: Progress, cfg: Config) -> Pick | Ending:
    """Pure decline table, checked in this order.

    OffTarget is OFF_TARGET. p under confidence_min is NOT_SURE, for done and stuck too.
    Done is DONE. Stuck is KEV_STUCK. A Pick with attempts already at step_budget is BUDGET.
    """
    match decision:
        case OffTarget():
            return Ending.OFF_TARGET
        case Pick(p=p) | Done(p=p) | Stuck(p=p) if p < cfg.confidence_min:
            return Ending.NOT_SURE
        case Done():
            return Ending.DONE
        case Stuck():
            return Ending.KEV_STUCK
        case Pick() if progress.attempts >= cfg.step_budget:
            return Ending.BUDGET
        case Pick():
            return decision


def compose(pick: Pick, utterance: Utterance, observation: Observation, writer: Writer) -> Intent | None:
    """Click ignores the payload. Type uses the spoken payload, else a draft. None is an empty draft."""
    match pick.action:
        case Action.CLICK:
            return Click(pick.candidate)
        case Action.TYPE:
            text = utterance.payload or writer.draft(
                utterance.text, pick.candidate.name, [c.name for c in observation.candidates]
            )
            return Type(pick.candidate, text) if text is not None else None


def succeeded(receipt: Injected, before: Observation, after: Observation) -> bool:
    """Pure postcondition.

    A type succeeds when the watched element's read-back text contains the typed string. Only when the
    element exposes no text pattern does the check fall back to OCR words inside the element's rectangle,
    where the last min(6, n) tokens of the typed string must appear as a contiguous run. A string with
    no tokens succeeds when the OCR words in that rectangle changed.
    A click succeeds when the watched state changed or is GONE, focus changed, OCR text changed,
    or the candidate names changed.
    """
    watched = after.watched
    match receipt.intent:
        case Type(candidate=c, text=text):
            if isinstance(watched, ElementState) and watched.text is not None:
                return text in watched.text
            rect = receipt.element.rect if receipt.element is not None else c.rect
            shown = _words_in(after.words, rect)
            typed = words(text)
            if not typed:
                return shown != _words_in(before.words, rect)
            # The caret ends at the typed tail, so the tail is what stays scrolled into view.
            tail = typed[-_READ_BACK_TAIL:]
            seen = words(" ".join(w.text for w in shown))
            return any(seen[i : i + len(tail)] == tail for i in range(len(seen) - len(tail) + 1))
        case Click():
            state_changed = watched is Gone.GONE or (
                isinstance(watched, ElementState)
                and receipt.element is not None
                and watched != receipt.element.state
            )
            return (
                state_changed
                or before.focused != after.focused
                or before.ocr_text != after.ocr_text
                or before.names != after.names
            )
        case _:
            assert_never(receipt.intent)


def _words_in(all_words: tuple[OcrWord, ...], rect: VirtualRect) -> tuple[OcrWord, ...]:
    return tuple(w for w in all_words if rect.contains(w.rect.center))


def run_utterance(utterance: Utterance, rig: Rig, gate: Gate, cfg: Config) -> Ending:
    """Run one utterance to exactly one Ending."""
    try:
        return _run(utterance, rig, gate, cfg)
    except Unavailable as e:
        return e.ending


def _run(utterance: Utterance, rig: Rig, gate: Gate, cfg: Config) -> Ending:
    progress = Progress()
    before = observe(rig.desktop.scan(None), utterance, cfg.max_candidates)
    while True:
        if not gate():
            return Ending.ABORTED
        if not before.candidates:
            return Ending.NO_CANDIDATES
        decision = rig.decider.decide(utterance, before)
        # perform() re-checks the gate before injecting. This check only skips the writer after disarm.
        if not gate():
            return Ending.ABORTED
        verdict = judge(decision, progress, cfg)
        if isinstance(verdict, Ending):
            return verdict
        intent = compose(verdict, utterance, before, rig.writer)
        injected: Injected | None = None
        miss: MissKey | None = None
        if intent is None:
            miss = MissKey(Action.TYPE, None, verdict.candidate.rect)
        elif progress.refuses(intent):
            miss = _key(intent)
        else:
            match act(rig.desktop, intent, gate):
                case Disarmed():
                    return Ending.ABORTED
                case Declined(reason=Decline.PASSWORD):
                    return Ending.PASSWORD
                case Declined(reason=Decline.CANNOT_ACCEPT_TEXT):
                    miss = _key(intent)
                case Injected() as receipt:
                    injected = receipt
        watch = injected.element.ref if injected is not None and injected.element is not None else None
        after = observe(rig.desktop.scan(watch), utterance, cfg.max_candidates)
        if injected is not None and not succeeded(injected, before, after):
            miss = _key(injected.intent)
        recorded = progress.record(miss)
        if isinstance(recorded, Ending):
            return recorded
        progress, before = recorded, after
