from __future__ import annotations

from kev_control.desktop import Scan, UiaControl, VirtualRect
from kev_control.eyes import OcrCandidate, UiaCandidate, observe
from tests.fakes import OWN_PID, FakeRef, heard, word


def test_observe_merges_named_icons_ranks_and_caps():
    scan = Scan(
        words=(
            word("Save", left=100, top=200, width=40, height=20, line=0),
            word("as", left=145, top=200, width=20, height=20, line=0),
            word("Cancel", left=300, top=200, width=60, height=20, line=0),
            word("Help", left=0, top=400, width=40, height=20),
            word("save", left=600, top=600, width=40, height=20),
        ),
        controls=(
            UiaControl("Save", "Button", VirtualRect(100, 200, 65, 20), pid=7, ref=FakeRef("Save")),
            UiaControl("Settings", "Button", VirtualRect(500, 0, 30, 30), pid=7, ref=FakeRef("Settings")),
            UiaControl("", "Image", VirtualRect(540, 0, 30, 30), pid=7, ref=FakeRef("blank")),
            UiaControl("Tray save", "Button", VirtualRect(700, 0, 30, 30), pid=OWN_PID, ref=FakeRef("tray")),
        ),
        own_pid=OWN_PID,
        own_rects=(VirtualRect(590, 590, 100, 40),),
        focused=None,
        watched=None,
    )

    observation = observe(scan, heard("click save settings"), max_candidates=3)

    assert observation.candidates == (
        OcrCandidate("Save as", VirtualRect(100, 200, 65, 20)),
        UiaCandidate("Settings", "Button", VirtualRect(500, 0, 30, 30), FakeRef("Settings")),
        OcrCandidate("Cancel", VirtualRect(300, 200, 60, 20)),
    )
    assert observation.ocr_text == "Save as Cancel Help"
