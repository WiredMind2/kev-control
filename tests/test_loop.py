from __future__ import annotations

import pytest

from kev_control.config import Config
from kev_control.decider import Decision, Done
from kev_control.desktop import ClickAt, Invoke, Point, SetValue, ValueCap, VirtualRect
from kev_control.ending import Ending
from kev_control.loop import Rig, run_utterance
from tests.fakes import (
    FakeDesktop,
    FakeElement,
    FakeRef,
    FixedWriter,
    NoWriter,
    PickByName,
    Scene,
    ScriptedDecider,
    armed,
    disarm_after,
    heard,
    pick,
    word,
)


def test_repeat_click_on_unchanged_screen_is_refused_and_ends_stuck():
    desktop = FakeDesktop(Scene(words=[word("Save", left=100, top=200, width=40, height=20)]))
    decider = ScriptedDecider([pick("Save", "click", 0.9), pick("Save", "click", 0.9)])

    ending = run_utterance(heard("click save"), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is Ending.UNCHANGED
    assert desktop.performed == [ClickAt(Point(120, 210))]
    assert decider.asked == [("Save",), ("Save",)]


def test_decision_that_arrives_after_disarm_injects_nothing():
    desktop = FakeDesktop(Scene(words=[word("Send", left=0, top=0, width=40, height=20)]))
    gate, decider = disarm_after(ScriptedDecider([pick("Send", "click", 0.99)]))

    ending = run_utterance(heard("click send"), Rig(desktop, decider, NoWriter()), gate, Config())

    assert ending is Ending.ABORTED
    assert desktop.performed == []


def test_eight_attempts_then_a_ninth_pick_stops():
    desktop = FakeDesktop(
        Scene(words=[word("Next", left=0, top=0, width=40, height=20)]), changes_on_every_click=True
    )
    decider = ScriptedDecider([pick("Next", "click", 0.9)] * 9)

    ending = run_utterance(heard("keep clicking next"), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is Ending.BUDGET
    assert len(desktop.performed) == 8
    assert ending.message(Config()) == "Stopped after 8 steps"


def _note_scene() -> Scene:
    rect = VirtualRect(10, 10, 60, 20)
    return Scene(
        words=[word("Note", left=10, top=10, width=60, height=20)],
        elements=[FakeElement("Note", rect, value=ValueCap.WRITABLE, text="")],
    )


def test_quoted_utterance_types_the_spoken_characters_without_the_writer():
    desktop = FakeDesktop(_note_scene())
    writer = FixedWriter("a drafted reply")
    decider = ScriptedDecider([pick("Note", "type", 0.9), Done(0.9)])

    ending = run_utterance(heard('type "see you at 5" in note'), Rig(desktop, decider, writer), armed(), Config())

    assert ending is Ending.DONE
    assert desktop.performed == [SetValue(FakeRef("Note"), "see you at 5")]
    assert writer.calls == []


def test_unspoken_text_is_drafted_by_the_writer():
    desktop = FakeDesktop(_note_scene())
    writer = FixedWriter("I will be late")
    decider = ScriptedDecider([pick("Note", "type", 0.9), Done(0.9)])

    ending = run_utterance(heard("reply saying I will be late"), Rig(desktop, decider, writer), armed(), Config())

    assert ending is Ending.DONE
    assert desktop.performed == [SetValue(FakeRef("Note"), "I will be late")]
    assert writer.calls == [("reply saying I will be late", "Note", ("Note",))]


def test_password_field_is_refused_and_nothing_is_typed():
    rect = VirtualRect(10, 10, 80, 20)
    desktop = FakeDesktop(
        Scene(
            words=[word("Password", left=10, top=10, width=80, height=20)],
            elements=[FakeElement("Password", rect, is_password=True, value=ValueCap.WRITABLE, text="")],
        )
    )
    decider = ScriptedDecider([pick("Password", "type", 0.9)])

    ending = run_utterance(heard('type "hunter2" in password'), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is Ending.PASSWORD
    assert desktop.performed == []


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (pick("Save", "click", 0.34), Ending.NOT_SURE),
        (Done(0.34), Ending.NOT_SURE),
        (Done(0.35), Ending.DONE),
    ],
)
def test_confidence_under_the_cutoff_ends_not_sure(decision: PickByName | Decision, expected: Ending):
    desktop = FakeDesktop(Scene(words=[word("Save", left=100, top=200, width=40, height=20)]))
    decider = ScriptedDecider([decision])

    ending = run_utterance(heard("click save"), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is expected
    assert desktop.performed == []


def test_zero_candidates_ends_without_asking_kev():
    desktop = FakeDesktop(Scene())
    decider = ScriptedDecider([pick("Save", "click", 0.9)])

    ending = run_utterance(heard("click save"), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is Ending.NO_CANDIDATES
    assert decider.asked == []
    assert desktop.performed == []


def test_a_miss_on_a_different_target_still_ends_unchanged():
    desktop = FakeDesktop(
        Scene(
            words=[
                word("Save", left=100, top=200, width=40, height=20),
                word("Cancel", left=300, top=200, width=60, height=20),
            ]
        )
    )
    decider = ScriptedDecider([pick("Save", "click", 0.9), pick("Cancel", "click", 0.9)])

    ending = run_utterance(heard("click save"), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is Ending.UNCHANGED
    assert desktop.performed == [ClickAt(Point(120, 210)), ClickAt(Point(330, 210))]


def test_a_success_clears_the_miss():
    toggle_rect = VirtualRect(300, 200, 60, 20)
    desktop = FakeDesktop(
        Scene(
            words=[
                word("Save", left=100, top=200, width=40, height=20),
                word("Toggle", left=300, top=200, width=60, height=20),
            ],
            elements=[FakeElement("Toggle", toggle_rect, can_invoke=True, toggle="off")],
        )
    )
    decider = ScriptedDecider(
        [pick("Save", "click", 0.9), pick("Toggle", "click", 0.9), pick("Save", "click", 0.9), Done(0.9)]
    )

    ending = run_utterance(heard("click save"), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is Ending.DONE
    assert desktop.performed == [ClickAt(Point(120, 210)), Invoke(FakeRef("Toggle")), ClickAt(Point(120, 210))]
