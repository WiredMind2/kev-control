"""Atheris harness scaffolded by ClusterFuzz (AST fallback)."""
import sys
from pathlib import Path

import atheris

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / 'src'))

from kev_control.win_desktop import injection_enabled, claim_per_monitor_v2, window_rect, element_center  # noqa: E402


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    try:
        injection_enabled()
    except Exception:
        pass
    try:
        claim_per_monitor_v2()
    except Exception:
        pass
    try:
        window_rect(fdp.ConsumeIntInRange(-10**6, 10**6))
    except Exception:
        pass
    try:
        element_center(fdp.ConsumeIntInRange(-10**6, 10**6))
    except Exception:
        pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
