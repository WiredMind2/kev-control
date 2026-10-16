from __future__ import annotations

import threading
import time

from kev_control.arm import Arm


def test_caps_off_and_on_again_mints_a_new_session_and_kills_the_old_gate():
    caps = [True]
    arm = Arm(read_toggle=lambda: caps[0], period_s=0.001)
    threading.Thread(target=arm.run, daemon=True).start()

    first = arm.wait_armed(timeout_s=1.0)
    assert first == 1
    old_gate = arm.gate(first)
    caps[0] = False
    deadline = time.monotonic() + 1.0
    while arm.current() is not None and time.monotonic() < deadline:
        time.sleep(0.001)
    caps[0] = True
    second = arm.wait_armed(timeout_s=1.0)

    assert second == 2
    assert old_gate() is False
    assert arm.gate(second)() is True
