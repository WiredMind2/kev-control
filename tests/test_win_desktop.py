import pytest

from kev_control.win_desktop import claim_per_monitor_v2, element_center
from tests.owned_window import owned_window


@pytest.mark.windows
def test_ocr_is_not_required_for_the_button_center_to_match_the_window_rect():
    claim_per_monitor_v2()
    with owned_window(button="Save", edit_label="Note") as win:
        center = element_center(win.button_hwnd)
        rect = win.button_rect()
        assert abs(center.x - rect.center.x) <= 2
        assert abs(center.y - rect.center.y) <= 2
