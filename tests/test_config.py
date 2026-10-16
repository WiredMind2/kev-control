from __future__ import annotations

from pathlib import Path

import pytest

from kev_control.config import Config, ConfigError, load_config


def test_missing_file_is_all_defaults(tmp_path: Path):
    assert load_config(tmp_path / "absent.toml") == Config()


def test_keys_override_defaults(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('kev_checkpoint = "jaredpalmer/kev-4b"\nconfidence_min = 1\n', encoding="utf-8")

    assert load_config(path) == Config(kev_checkpoint="jaredpalmer/kev-4b", confidence_min=1.0)


@pytest.mark.parametrize(
    ("toml", "key"),
    [
        ("max_candidates = 254", "max_candidates"),
        ('step_budget = "eight"', "step_budget"),
        ("confidence = 0.5", "confidence"),
    ],
)
def test_bad_settings_name_the_key(tmp_path: Path, toml: str, key: str):
    path = tmp_path / "config.toml"
    path.write_text(toml, encoding="utf-8")

    with pytest.raises(ConfigError, match=f"^{key}:"):
        load_config(path)
