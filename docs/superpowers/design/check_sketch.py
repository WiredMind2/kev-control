"""Re-check the grafted sketch. Run from anywhere: python docs/superpowers/design/check_sketch.py"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_sketch():
    spec = importlib.util.spec_from_file_location("kev_sketch", ROOT / "sketch.py")
    if spec is None or spec.loader is None:
        raise SystemExit("sketch.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    sketch = (ROOT / "sketch.py").read_text(encoding="utf-8")
    usage = (ROOT / "usage.md").read_text(encoding="utf-8")
    rationale = (ROOT / "rationale.md").read_text(encoding="utf-8")
    module = load_sketch()

    config = module.Config()
    assert config.max_candidates == 24, config.max_candidates
    assert config.confidence_min == 0.35, config.confidence_min
    assert config.step_budget == 8, config.step_budget
    assert "probabilities[choice]" in sketch, "cutoff must read the chosen option probability"
    assert "1..253" in sketch, "candidate cap must leave room for done and stuck"
    assert '"" from ValuePattern is the text' in sketch, "empty value read must stop the ladder"
    assert "including \"\"" in sketch, "succeeded() must treat an empty value as the text"
    assert "please type a reply" in usage, "mailbox test for speech during a running command"
    assert "The base is the Opus sketch" in rationale, "synthesis decision missing"
    assert "different control as a fresh try" in rationale, "rejected miss rule missing"
    print("sketch checks passed")


if __name__ == "__main__":
    main()
