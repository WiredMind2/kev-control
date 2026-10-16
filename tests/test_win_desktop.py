import pytest

from kev_control.desktop import Invoke, Performed, SetValue
from kev_control.eyes import observe
from kev_control.slots import SessionId, Utterance, as_text
from kev_control.win_desktop import WinDesktop, claim_per_monitor_v2, element_center, injection_enabled
from tests.owned_window import owned_window


@pytest.mark.windows
def test_ocr_is_not_required_for_the_button_center_to_match_the_window_rect():
    claim_per_monitor_v2()
    with owned_window(button="Save", edit_label="Note") as win:
        center = element_center(win.button_hwnd)
        rect = win.button_rect()
        assert abs(center.x - rect.center.x) <= 2
        assert abs(center.y - rect.center.y) <= 2


def test_pytest_disables_computer_control():
    assert injection_enabled() is False


@pytest.mark.windows
def test_armed_plans_are_withheld_and_do_not_change_the_window():
    claim_per_monitor_v2()
    hello = as_text("hello")
    assert hello is not None
    with owned_window(button="Save", edit_label="Note") as win:
        desktop = WinDesktop()
        button = desktop.inspect(win.button_rect().center)
        edit = desktop.inspect(win.edit_rect().center)
        assert button is not None and edit is not None
        invoke = Invoke(button.ref)
        typing = SetValue(edit.ref, hello)
        assert desktop.perform(invoke, gate=lambda: True) is Performed.DISARMED
        assert desktop.perform(typing, gate=lambda: True) is Performed.DISARMED
        assert desktop.withheld == [invoke, typing]
        assert win.button_presses() == 0
        assert win.edit_text() == ""


@pytest.mark.windows
def test_disarmed_gate_does_not_type():
    claim_per_monitor_v2()
    with owned_window(button="Save", edit_label="Note") as win:
        desktop = WinDesktop()
        edit = desktop.inspect(win.edit_rect().center)
        assert edit is not None
        assert desktop.perform(SetValue(edit.ref, as_text("hello")), gate=lambda: False) is Performed.DISARMED
        assert win.edit_text() == ""


@pytest.mark.windows
def test_scan_sees_the_save_label_and_observe_keeps_it():
    claim_per_monitor_v2()
    with owned_window(button="Save", edit_label="Note") as win:
        win.show_without_activating()
        scan = WinDesktop().scan(None)
        utterance = Utterance.heard(SessionId(1), "click save")
        assert utterance is not None
        observation = observe(scan, utterance, 24)
        assert any(c.name == "Save" for c in observation.candidates)
        assert win.button_presses() == 0
        assert win.edit_text() == ""
