from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from kev_control.ending import Ending, Unavailable
from kev_control.eyes import Candidate, Observation
from kev_control.slots import Utterance

__all__ = ["Action", "Decider", "Decision", "Done", "KevDecider", "OffTarget", "Pick", "Stuck", "state_text"]


class Action(enum.Enum):
    CLICK = "click"
    TYPE = "type"


@dataclass(frozen=True)
class Pick:
    candidate: Candidate
    action: Action
    p: float


@dataclass(frozen=True)
class Done:
    p: float


@dataclass(frozen=True)
class Stuck:
    p: float


@dataclass(frozen=True)
class OffTarget:
    raw: str


Decision = Pick | Done | Stuck | OffTarget
"""Resolved against the observation it was asked about. Candidate ids never leave decider.py."""


class Decider(Protocol):
    def decide(self, utterance: Utterance, observation: Observation) -> Decision:
        """Raises Unavailable(KEV_DOWN) or Unavailable(KEV_BAD_REPLY)."""
        ...


def state_text(utterance: Utterance, observation: Observation) -> str:
    """Utterance line, then one `c{i} {source} {role} {name}` line per candidate."""
    lines = [f"utterance: {utterance.text}"]
    lines += [f"c{i} {c.source} {c.role} {c.name}" for i, c in enumerate(observation.candidates)]
    return "\n".join(lines)


class KevDecider:
    """One POST /v1/systemone per decision, model kev-latest. The server picks the checkpoint."""

    def __init__(self, url: str, client: httpx.Client | None = None, timeout_s: float = 30.0) -> None:
        self._endpoint = f"{url.rstrip('/')}/v1/systemone"
        self._client = client or httpx.Client()
        self._timeout_s = timeout_s

    def decide(self, utterance: Utterance, observation: Observation) -> Decision:
        body = _request_body(state_text(utterance, observation), len(observation.candidates))
        try:
            response = self._client.post(self._endpoint, json=body, timeout=self._timeout_s)
        except httpx.TransportError as e:
            raise Unavailable(Ending.KEV_DOWN) from e
        if response.status_code != 200:
            raise Unavailable(Ending.KEV_BAD_REPLY)
        try:
            reply: object = response.json()
        except ValueError as e:
            raise Unavailable(Ending.KEV_BAD_REPLY) from e
        return _parse_reply(reply, observation)


_TARGET_INSTRUCTION = (
    "Which control advances the utterance? Answer done if the goal is already met, "
    "or stuck if none of the controls will do it."
)
_ACTION_INSTRUCTION = "Should the app click that control or type into it?"
_CANDIDATE_ID = re.compile(r"c(0|[1-9][0-9]*)")


def _choice(instructions: str, options: list[str]) -> dict[str, object]:
    return {"type": "choice", "instructions": instructions, "criteria": dict.fromkeys(options)}


def _request_body(state: str, candidate_count: int) -> dict[str, object]:
    targets = [f"c{i}" for i in range(candidate_count)] + ["done", "stuck"]
    return {
        "model": "kev-latest",
        "state": state,
        "questions": {
            "target": _choice(_TARGET_INSTRUCTION, targets),
            "action": _choice(_ACTION_INSTRUCTION, [a.value for a in Action]),
        },
    }


def _parse_reply(body: object, observation: Observation) -> Decision:
    answers = _field(body, "answers")
    target, p = _answer(_field(answers, "target"))
    if target == "done":
        return Done(p)
    if target == "stuck":
        return Stuck(p)
    found = _CANDIDATE_ID.fullmatch(target)
    if found is None or int(found.group(1)) >= len(observation.candidates):
        return OffTarget(target)
    action, _ = _answer(_field(answers, "action"))
    if action not in {a.value for a in Action}:
        raise Unavailable(Ending.KEV_BAD_REPLY)
    return Pick(observation.candidates[int(found.group(1))], Action(action), p)


def _field(obj: object, key: str) -> object:
    if not isinstance(obj, dict) or key not in obj:
        raise Unavailable(Ending.KEV_BAD_REPLY)
    return obj[key]  # pyright: ignore[reportUnknownVariableType]


def _answer(answer: object) -> tuple[str, float]:
    """The chosen option and its probability, read from probabilities[choice]."""
    choice = _field(answer, "choice")
    probabilities = _field(answer, "probabilities")
    if not isinstance(choice, str):
        raise Unavailable(Ending.KEV_BAD_REPLY)
    p = _field(probabilities, choice)
    if isinstance(p, bool) or not isinstance(p, int | float) or not 0.0 <= p <= 1.0:
        raise Unavailable(Ending.KEV_BAD_REPLY)
    return choice, float(p)
