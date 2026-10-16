"""Atheris harness scaffolded by ClusterFuzz (AST fallback)."""
import sys
from pathlib import Path

import atheris

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / 'src'))

from kev_control.loop import judge, compose, succeeded, run_utterance  # noqa: E402


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    try:
        judge(fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)))
    except Exception:
        pass
    try:
        compose(fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)))
    except Exception:
        pass
    try:
        succeeded(fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)))
    except Exception:
        pass
    try:
        run_utterance(fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)), fdp.ConsumeUnicodeNoSurrogates(min(fdp.RemainingBytes(), 4096)))
    except Exception:
        pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
