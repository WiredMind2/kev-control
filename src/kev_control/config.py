from __future__ import annotations

import os
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import get_type_hints

__all__ = ["MODELS_DIR", "Config", "ConfigError", "config_path", "load_config"]

MODELS_DIR = Path.home() / "AppData" / "Local" / "kev-control" / "models"


@dataclass(frozen=True)
class Config:
    """Validated settings. Field names are the TOML keys. Defaults are the spec values."""

    kev_url: str = "http://127.0.0.1:8008"
    kev_checkpoint: str = "jaredpalmer/kev-0.6b"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_language: str = "en"
    writer_gguf: Path = MODELS_DIR / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    confidence_min: float = 0.35
    step_budget: int = 8
    silence_seconds: float = 0.8
    max_candidates: int = 24
    writer_max_chars: int = 200


class ConfigError(Exception):
    """Names the offending key. Raised only by load_config."""


_TYPES: dict[str, object] = get_type_hints(Config)

# done and stuck take two of System One's 255 options, hence 253.
_RANGES: dict[str, tuple[Callable[[float], bool], str]] = {
    "confidence_min": (lambda v: 0.0 <= v <= 1.0, "between 0 and 1"),
    "step_budget": (lambda v: v >= 1, "at least 1"),
    "silence_seconds": (lambda v: v > 0, "above 0"),
    "max_candidates": (lambda v: 1 <= v <= 253, "in 1..253"),
    "writer_max_chars": (lambda v: v >= 1, "at least 1"),
}


def config_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "kev-control" / "config.toml"


def load_config(path: Path) -> Config:
    """Parse TOML into Config. A missing file means all defaults."""
    if not path.exists():
        return Config()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    known = {f.name for f in fields(Config)}
    values: dict[str, object] = {}
    for key, value in raw.items():
        if key not in known:
            raise ConfigError(f"{key}: unknown setting")
        values[key] = _coerce(key, value)
    return Config(**values)  # pyright: ignore[reportArgumentType]


def _coerce(key: str, value: object) -> object:
    expected = _TYPES[key]
    if expected is str and isinstance(value, str):
        return value
    if expected is Path and isinstance(value, str):
        return Path(value).expanduser()
    if expected is int and isinstance(value, int) and not isinstance(value, bool):
        return _in_range(key, value)
    if expected is float and isinstance(value, int | float) and not isinstance(value, bool):
        return _in_range(key, float(value))
    raise ConfigError(f"{key}: expected {getattr(expected, '__name__', expected)}, got {type(value).__name__}")


def _in_range(key: str, value: float) -> float:
    rule = _RANGES.get(key)
    if rule is not None and not rule[0](value):
        raise ConfigError(f"{key}: must be {rule[1]}, got {value}")
    return value
