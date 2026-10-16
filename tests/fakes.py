from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field

from kev_control.arm import Gate
from kev_control.decider import Action, Decider, Decision, OffTarget, Pick
from kev_control.desktop import (
    ClickAt,
    ElementInfo,
    ElementKey,
    ElementRef,
    ElementState,
    FocusAndType,
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
from kev_control.eyes import Observation, OcrCandidate
from kev_control.slots import SessionId, Text, Utterance, as_text

_lines = itertools.count()


def heard(text: str, session: int = 1) -> Utterance:
    utterance = Utterance.heard(SessionId(session), text)
    assert utterance is not None
    return utterance


def word(text: str, left: int, top: int, width: int, height: int, line: int | None = None) -> OcrWord:
    """Each word is its own OCR line unless a line is given."""
    return OcrWord(text, VirtualRect(left, top, width, height), next(_lines) if line is None else line)


@dataclass(frozen=True)
class FakeRef:
    name: str


@dataclass
class FakeElement:
    name: str
    rect: VirtualRect
    is_password: bool = False
    can_invoke: bool = False
    value: ValueCap = ValueCap.NONE
    editable: bool = False
    text: str | None = None
    toggle: str | None = None

    @property
    def ref(self) -> FakeRef:
        return FakeRef(self.name)

    @property
    def state(self) -> ElementState:
        return ElementState(self.toggle, None, None, self.text)


@dataclass
class Scene:
    words: list[OcrWord] = field(default_factory=lambda: [])
    controls: list[UiaControl] = field(default_factory=lambda: [])
    elements: list[FakeElement] = field(default_factory=lambda: [])


OWN_PID = 1


class FakeDesktop:
    """Data-only desktop. `performed` lists every plan that was actually sent."""

    def __init__(self, scene: Scene, changes_on_every_click: bool = False) -> None:
        self.scene = scene
        self.changes_on_every_click = changes_on_every_click
        self.performed: list[Plan] = []
        self._clicks = 0
        self._focused: ElementKey | None = None

    def scan(self, watch: ElementRef | None) -> Scan:
        extra = (word(f"page{self._clicks}", left=900, top=900, width=40, height=20),) if self._clicks else ()
        watched = self._element(watch).state if watch is not None else None
        return Scan(
            words=(*self.scene.words, *extra),
            controls=tuple(self.scene.controls),
            own_pid=OWN_PID,
            own_rects=(),
            focused=self._focused,
            watched=watched,
        )

    def inspect(self, at: ElementRef | Point) -> ElementInfo | None:
        if isinstance(at, Point):
            found = next((e for e in self.scene.elements if e.rect.contains(at)), None)
        else:
            found = self._element(at)
        if found is None:
            return None
        return ElementInfo(
            ref=found.ref,
            key=self._key(found),
            rect=found.rect,
            is_password=found.is_password,
            can_invoke=found.can_invoke,
            value=found.value,
            editable=found.editable,
            state=found.state,
        )

    def perform(self, plan: Plan, gate: Gate) -> Performed:
        if not gate():
            return Performed.DISARMED
        self.performed.append(plan)
        match plan:
            case SetValue(element=ref, text=text):
                self._element(ref).text = text
            case FocusAndType(element=ref, text=text):
                target = self._element(ref)
                target.text = (target.text or "") + text
                self._focused = self._key(target)
            case Invoke(element=ref):
                target = self._element(ref)
                if target.toggle is not None:
                    target.toggle = "off" if target.toggle == "on" else "on"
                self._clicked()
            case ClickAt():
                self._clicked()
        return Performed.INJECTED

    def _clicked(self) -> None:
        if self.changes_on_every_click:
            self._clicks += 1

    def _element(self, ref: ElementRef) -> FakeElement:
        return next(e for e in self.scene.elements if e.ref == ref)

    def _key(self, element: FakeElement) -> ElementKey:
        return ElementKey((self.scene.elements.index(element),))


@dataclass(frozen=True)
class PickByName:
    name: str
    action: Action
    p: float


def pick(name: str, action: str, p: float) -> PickByName:
    return PickByName(name, Action(action), p)


class ScriptedDecider:
    """Answers from a script. A pick by name resolves against the observation it is asked about."""

    def __init__(self, steps: Sequence[PickByName | Decision]) -> None:
        self._steps = list(steps)
        self.asked: list[tuple[str, ...]] = []

    def decide(self, utterance: Utterance, observation: Observation) -> Decision:
        self.asked.append(tuple(c.name for c in observation.candidates))
        step = self._steps.pop(0)
        if not isinstance(step, PickByName):
            return step
        for candidate in observation.candidates:
            if candidate.name == step.name:
                return Pick(candidate, step.action, step.p)
        return OffTarget(step.name)


@dataclass
class _DisarmingDecider:
    inner: Decider
    armed: bool = True

    def decide(self, utterance: Utterance, observation: Observation) -> Decision:
        decision = self.inner.decide(utterance, observation)
        self.armed = False
        return decision


def disarm_after(inner: Decider) -> tuple[Gate, Decider]:
    """A gate that goes false the moment the decider answers, as if Caps Lock went off mid-call."""
    decider = _DisarmingDecider(inner)
    return (lambda: decider.armed), decider


def armed() -> Gate:
    return lambda: True


class NoWriter:
    def draft(self, utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> Text | None:
        raise Unavailable(Ending.WRITER_MISSING)


class FixedWriter:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def draft(self, utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> Text | None:
        self.calls.append((utterance_text, control_name, tuple(candidate_names)))
        return as_text(self.text)


def observation_with(names: Sequence[str]) -> Observation:
    candidates = tuple(OcrCandidate(n, VirtualRect(i * 100, 0, 40, 20)) for i, n in enumerate(names))
    return Observation(candidates, (), None, None)


def kev_reply(target: str, p: float, action: str) -> dict[str, object]:
    return {
        "answers": {
            "target": {"choice": target, "probabilities": {target: p}},
            "action": {"choice": action, "probabilities": {action: 1.0}},
        }
    }
