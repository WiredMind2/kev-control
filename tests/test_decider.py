from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from kev_control.config import Config
from kev_control.decider import Action, KevDecider, OffTarget, Pick
from kev_control.ending import Ending
from kev_control.eyes import OcrCandidate
from kev_control.desktop import VirtualRect
from kev_control.loop import Rig, run_utterance
from tests.fakes import FakeDesktop, NoWriter, Scene, armed, heard, kev_reply, observation_with, word

Handler = Callable[[httpx.Request], httpx.Response]


def _decider(handler: Handler) -> KevDecider:
    return KevDecider("http://kev.test", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_target_id_not_offered_is_off_target():
    sent: list[object] = []

    def kev(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=kev_reply(target="c7", p=0.9, action="click"))

    decision = _decider(kev).decide(heard("click save"), observation_with(["Save", "Cancel"]))

    assert decision == OffTarget("c7")
    assert sent == [
        {
            "model": "kev-latest",
            "state": "utterance: click save\nc0 ocr text Save\nc1 ocr text Cancel",
            "questions": {
                "target": {
                    "type": "choice",
                    "instructions": "Which control advances the utterance? Answer done if the goal is already met, "
                    "or stuck if none of the controls will do it.",
                    "criteria": {"c0": None, "c1": None, "done": None, "stuck": None},
                },
                "action": {
                    "type": "choice",
                    "instructions": "Should the app click that control or type into it?",
                    "criteria": {"click": None, "type": None},
                },
            },
        }
    ]


def test_cutoff_reads_the_chosen_target_probability_not_a_confidence_field():
    reply = {
        "confidence": 0.99,
        "answers": {
            "target": {"choice": "c1", "probabilities": {"c0": 0.3, "c1": 0.6, "done": 0.05, "stuck": 0.05}},
            "action": {"choice": "type", "probabilities": {"click": 0.2, "type": 0.8}},
        },
    }

    decision = _decider(lambda _: httpx.Response(200, json=reply)).decide(
        heard("type hi in cancel"), observation_with(["Save", "Cancel"])
    )

    assert decision == Pick(OcrCandidate("Cancel", VirtualRect(100, 0, 40, 20)), Action.TYPE, 0.6)


def _refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (_refused, Ending.KEV_DOWN),
        (lambda _: httpx.Response(200, text="not json"), Ending.KEV_BAD_REPLY),
        (lambda _: httpx.Response(200, json={"answers": {"target": {"choice": "c0"}}}), Ending.KEV_BAD_REPLY),
        (lambda _: httpx.Response(200, json=kev_reply(target="c0", p=0.9, action="scroll")), Ending.KEV_BAD_REPLY),
        (lambda _: httpx.Response(500, json={}), Ending.KEV_BAD_REPLY),
    ],
)
def test_kev_failures_end_the_utterance_stopped(handler: Handler, expected: Ending):
    desktop = FakeDesktop(Scene(words=[word("Save", left=0, top=0, width=40, height=20)]))

    ending = run_utterance(heard("click save"), Rig(desktop, _decider(handler), NoWriter()), armed(), Config())

    assert ending is expected
    assert desktop.performed == []
