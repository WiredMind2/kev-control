from kev_control.writer import clean_draft, writer_prompt


def test_clean_draft_keeps_the_first_line_and_drops_wrapping_quotes():
    assert clean_draft('  "see you at 5"\nmore', 200) == "see you at 5"


def test_clean_draft_of_blank_is_none():
    assert clean_draft("   \n", 200) is None


def test_prompt_contains_the_control_and_not_a_screenshot_marker():
    prompt = writer_prompt("reply saying I will be late", "Notes", ["Notes", "Send"])
    assert "Notes" in prompt
    assert "reply saying I will be late" in prompt
    assert "screenshot" not in prompt.lower()
