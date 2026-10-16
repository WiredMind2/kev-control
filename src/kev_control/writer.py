from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from kev_control.ending import Ending, Unavailable
from kev_control.slots import Text, as_text

__all__ = ["QwenWriter", "Writer", "clean_draft", "writer_prompt"]


class Writer(Protocol):
    def draft(self, utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> Text | None:
        """None is an empty draft. Raises Unavailable(WRITER_MISSING)."""
        ...


def clean_draft(raw: str, max_chars: int) -> Text | None:
    line = raw.splitlines()[0].strip() if raw.strip() else ""
    if len(line) >= 2 and line[0] == line[-1] and line[0] in "\"'":
        line = line[1:-1].strip()
    return as_text(line[:max_chars])


def writer_prompt(utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> str:
    names = ", ".join(candidate_names)[:2000]
    return (
        f"Utterance: {utterance_text}\n"
        f"Control: {control_name}\n"
        f"On screen: {names}\n"
        "Reply with the text to type and nothing else."
    )


class QwenWriter:
    """Local GGUF writer. The file is loaded on the first draft, never downloaded here."""

    def __init__(self, gguf: Path, max_chars: int) -> None:
        self._gguf = gguf
        self._max_chars = max_chars
        self._llm: object | None = None

    def draft(self, utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> Text | None:
        if self._llm is None:
            if not self._gguf.is_file():
                raise Unavailable(Ending.WRITER_MISSING)
            try:
                from llama_cpp import Llama
            except ImportError as exc:
                raise Unavailable(Ending.WRITER_MISSING) from exc
            self._llm = Llama(model_path=str(self._gguf), n_ctx=2048, verbose=False)
        prompt = writer_prompt(utterance_text, control_name, candidate_names)
        result = self._llm.create_completion(prompt=prompt, max_tokens=80, temperature=0)  # type: ignore[attr-defined]
        text = result["choices"][0]["text"]
        return clean_draft(str(text), self._max_chars)
