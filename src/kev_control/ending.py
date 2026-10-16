from __future__ import annotations

import enum

from kev_control.config import Config

__all__ = ["Ending", "Outcome", "Unavailable"]


class Outcome(enum.Enum):
    DONE = "done"
    STUCK = "stuck"
    ABORTED = "aborted"
    STOPPED = "stopped"


class Ending(enum.Enum):
    """Every way one utterance ends, with its tray text. No other module holds tray strings."""

    DONE = (Outcome.DONE, "Done")
    ABORTED = (Outcome.ABORTED, "Caps Lock off")
    NO_CANDIDATES = (Outcome.STUCK, "Nothing on screen to act on")
    NOT_SURE = (Outcome.STUCK, "Not sure")
    KEV_STUCK = (Outcome.STUCK, "No control on screen does that")
    OFF_TARGET = (Outcome.STUCK, "Kev chose a control it was not offered")
    PASSWORD = (Outcome.STUCK, "Password field")
    UNCHANGED = (Outcome.STUCK, "Screen did not change")
    BUDGET = (Outcome.STOPPED, "Stopped after {step_budget} steps")
    OCR_MISSING = (Outcome.STOPPED, "English OCR is unavailable")
    KEV_DOWN = (Outcome.STOPPED, "Kev is not running")
    KEV_BAD_REPLY = (Outcome.STOPPED, "Kev sent a reply the app cannot read")
    WRITER_MISSING = (Outcome.STOPPED, "Writer is unavailable")

    @property
    def outcome(self) -> Outcome:
        return self.value[0]

    def message(self, cfg: Config) -> str:
        return self.value[1].format(step_budget=cfg.step_budget)


class Unavailable(Exception):
    """A required local dependency is missing or unreachable.

    Adapters translate their own failures into this at their boundary.
    run_utterance is the only place that catches it.
    """

    def __init__(self, ending: Ending) -> None:
        super().__init__(ending.name)
        self.ending = ending
