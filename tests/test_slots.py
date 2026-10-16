from __future__ import annotations

import pytest

from kev_control.slots import payload


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("type hello in the search box", "hello"),
        ('type "see you at 5" in Notes', "see you at 5"),
        ("write 'on my way' into chat", "on my way"),
        ("type don't panic in notes", "don't panic"),
        ("Enter Hunter Smith at the name field", "Hunter Smith"),
        ("reply saying I will be late", None),
        ("type in the box", None),
    ],
)
def test_payload(utterance: str, expected: str | None):
    assert payload(utterance) == expected
