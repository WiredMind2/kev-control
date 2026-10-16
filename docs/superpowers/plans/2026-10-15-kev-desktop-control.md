# Kev desktop control implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Windows tray app so that, while Caps Lock is on, a spoken command can click or type a control that is already on screen.

**Architecture:** The pure loop in `src/kev_control/loop.py` already decides and records endings. This plan adds the four edges that loop calls through protocols. `WinDesktop` is the only code that reads the screen or injects input. `QwenWriter` drafts unspoken text. `Ear` turns silence-ended speech into one mailbox slot. `Worker` and `Tray` run that loop while Caps Lock is on. Do not add a second loop, a second miss rule, or a second Caps Lock reader.

**Tech Stack:** Python 3.12+, pytest, httpx (already wired), ctypes and comtypes for UI Automation and SendInput, winrt for Windows OCR, faster-whisper on CPU, llama-cpp-python for the GGUF writer, pystray for the tray.

## Global Constraints

- Caps Lock is the only confirmation. On means listen and act, including send and delete. Off means inert.
- `Arm` in `src/kev_control/arm.py` is the only `GetKeyState(VK_CAPITAL)` reader. Poll period is 0.05 seconds. The toggle bit is `GetKeyState(0x14) & 1`.
- Kev stays at `http://127.0.0.1:8008`, model `kev-latest`, one `POST /v1/systemone`. The body uses `type`, `instructions`, and `criteria`. The cutoff reads `answers.target.probabilities[choice]`, default `0.35`.
- Default checkpoint is `jaredpalmer/kev-0.6b`. `kev_checkpoint` may be `jaredpalmer/kev-4b`. The decider code does not change.
- `max_candidates` default is 24 and `load_config` rejects values outside 1..253. `step_budget` default is 8. `silence_seconds` default is 0.8. `writer_max_chars` default is 200.
- Windows OCR language is `en-US`. Whisper model is `small`, device `cpu`, language `en`.
- The writer is Qwen2.5-1.5B-Instruct, GGUF, on CPU. It does not pick a control and does not see a screenshot.
- Clicks are one left click. No right-click, drag, scroll, shortcut, or shell.
- The running app does not download models. `python -m kev_control setup` does.
- An icon with an empty name is not a candidate. A password element is not typed into.
- Candidate ids `c0`.. stay inside `decider.py`. Do not thread them into `WinDesktop`.
- Tests that move the real cursor or read the real screen are marked `pytest.mark.windows`. Unit tests stay on fakes.

---

## File structure

Already present and not to be rewritten:

- `src/kev_control/loop.py` owns the step budget, the consecutive-miss rule, and `run_utterance`.
- `src/kev_control/decider.py` owns the System One body and `KevDecider`.
- `src/kev_control/hands.py` owns `plan` and `act`.
- `src/kev_control/eyes.py` owns `observe`.
- `src/kev_control/session.py` owns `Mailbox`.
- `src/kev_control/desktop.py` owns `Scan`, `Plan`, `Desktop`, and `VirtualRect`.

This plan creates:

- `src/kev_control/win_desktop.py` owns DPI awareness, capture, OCR, UI Automation, and `perform`. It is the only new module that may import `comtypes`, `winrt`, or call `SendInput`.
- `src/kev_control/writer.py` gains `clean_draft`, `writer_prompt`, and `QwenWriter`. The `Writer` protocol stays.
- `src/kev_control/ear.py` owns the microphone and silence segmentation.
- `src/kev_control/tray.py` owns the icon and `render`.
- `src/kev_control/app.py` owns `main`, `serve`, and `setup`.
- `tests/owned_window.py` owns the Win32 button and edit used by Windows tests.
- `tests/test_win_desktop.py`, `tests/test_writer.py`, `tests/test_ear.py`, `tests/test_app.py`.

`win_desktop.py` is a split from `desktop.py` because the type file is already the contract and the COM implementation would bury it. The import boundary is the file, not a second policy.

## Why one plan

Speech, the writer, the screen, and the tray are separate files, and each task below ends in its own test. They are not separate products. Each one is an adapter of the loop that already shipped in `7f150ff`. A second spec would restate the same endings. Ear and the writer do not import each other, so tasks 4 and 5 can be implemented in either order after task 3.

## Definition of done

`python -m pytest -q` passes, including the `windows` tests on this machine. The owned-window test invokes Save once and sets the Note field to `hello`. A disarmed gate leaves that field unchanged. A second monitor, if none is attached, stays `INCONCLUSIVE` in the decision log and does not block the primary-display tests.

---

### Task 1: Owned window and coordinate agreement

**Files:**
- Create: `tests/owned_window.py`
- Create: `tests/test_win_desktop.py`
- Create: `src/kev_control/win_desktop.py`
- Test: `tests/test_win_desktop.py`

**Interfaces:**
- Consumes: `VirtualRect` and `Point` from `kev_control.desktop`.
- Produces: `owned_window(button: str, edit_label: str)` context manager with `button_hwnd`, `edit_hwnd`, `button_presses() -> int`, `edit_text() -> str`, `button_rect() -> VirtualRect`. Produces `claim_per_monitor_v2() -> None` and `element_center(hwnd: int) -> Point` in `win_desktop.py`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_win_desktop.py::test_ocr_is_not_required_for_the_button_center_to_match_the_window_rect -v`

Expected: FAIL with `ModuleNotFoundError: kev_control.win_desktop` or `ImportError`.

- [ ] **Step 3: Write minimal implementation**

`tests/owned_window.py` creates a `WS_OVERLAPPEDWINDOW` on its own thread, with a `BUTTON` labeled Save and an `EDIT`, pumps messages, and reads `BM_GETSTATE` clicks plus `WM_GETTEXT`. `button_rect` uses `GetWindowRect`, which is virtual-screen pixels after per-monitor v2.

`claim_per_monitor_v2` calls `SetProcessDpiAwarenessContext(-4)` once. A second call is a no-op. `element_center` returns the center of `GetWindowRect`.

```python
def claim_per_monitor_v2() -> None:
    """Must run before any window, COM object, or capture. -4 is PER_MONITOR_AWARE_V2."""
    awareness = ctypes.c_void_p(-4)
    ctypes.windll.user32.SetProcessDpiAwarenessContext(awareness)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_win_desktop.py::test_ocr_is_not_required_for_the_button_center_to_match_the_window_rect -v`

Expected: PASS. If the two centers differ by more than 2 pixels, stop. Do not add a scale factor. Record the two points in the decision log and fix awareness before task 2.

- [ ] **Step 5: Commit**

```powershell
git add tests/owned_window.py tests/test_win_desktop.py src/kev_control/win_desktop.py
$msg = @"
Prove the owned-window button center matches its window rect.
"@
git commit -m $msg
```

---

### Task 2: Inject only while the gate is armed

**Files:**
- Modify: `src/kev_control/win_desktop.py`
- Modify: `tests/test_win_desktop.py`
- Test: `tests/test_win_desktop.py`

**Interfaces:**
- Consumes: `Plan` (`Invoke`, `ClickAt`, `SetValue`, `FocusAndType`), `Performed`, `Gate`, `Text` via `as_text`.
- Produces: `class WinDesktop` with `perform(self, plan: Plan, gate: Gate) -> Performed`. `inspect(self, at: ElementRef | Point) -> ElementInfo | None` for the owned button and edit.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from kev_control.desktop import Invoke, Performed, SetValue
from kev_control.slots import as_text
from kev_control.win_desktop import WinDesktop, claim_per_monitor_v2
from tests.owned_window import owned_window

@pytest.mark.windows
def test_invoke_save_and_set_note_while_armed():
    claim_per_monitor_v2()
    with owned_window(button="Save", edit_label="Note") as win:
        desktop = WinDesktop()
        button = desktop.inspect(win.button_rect().center)
        edit = desktop.inspect(win.edit_rect().center)
        assert button is not None and edit is not None
        assert desktop.perform(Invoke(button.ref), gate=lambda: True) is Performed.INJECTED
        assert desktop.perform(SetValue(edit.ref, as_text("hello")), gate=lambda: True) is Performed.INJECTED
        assert win.button_presses() == 1
        assert win.edit_text() == "hello"


@pytest.mark.windows
def test_disarmed_gate_does_not_type():
    claim_per_monitor_v2()
    with owned_window(button="Save", edit_label="Note") as win:
        desktop = WinDesktop()
        edit = desktop.inspect(win.edit_rect().center)
        assert edit is not None
        assert desktop.perform(SetValue(edit.ref, as_text("hello")), gate=lambda: False) is Performed.DISARMED
        assert win.edit_text() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_win_desktop.py -v`

Expected: FAIL with `WinDesktop` missing or `inspect` missing.

- [ ] **Step 3: Write minimal implementation**

`perform` calls `gate()` immediately before `Invoke`, before `SetCursorPos`, before `SetValue`, and again after focus succeeds and before `SendInput`. A false gate returns `Performed.DISARMED` and sends nothing.

```python
def perform(self, plan: Plan, gate: Gate) -> Performed:
    if not gate():
        return Performed.DISARMED
    match plan:
        case Invoke(element=ref):
            if not gate():
                return Performed.DISARMED
            self._invoke(ref)
        case SetValue(element=ref, text=text):
            if not gate():
                return Performed.DISARMED
            self._set_value(ref, text)
        case ClickAt(point=point):
            if not gate():
                return Performed.DISARMED
            self._click_at(point)
        case FocusAndType(element=ref, text=text):
            if not gate() or not self._focus(ref):
                return Performed.DISARMED if not gate() else Performed.FOCUS_REFUSED
            if not gate():
                return Performed.DISARMED
            self._type_unicode(text)
    return Performed.INJECTED
```

`SetValue` uses the UI Automation value pattern. `FocusAndType` uses `KEYEVENTF_UNICODE` (`0x0004`) so Caps Lock does not change case. `Invoke` uses the invoke pattern. `ClickAt` is `SetCursorPos` plus one left button down and up. `inspect` of a `Point` uses `ElementFromPoint`. An `IsPassword` element is still returned. `hands.plan` already refuses to type into it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_win_desktop.py -v`

Expected: PASS, and `python -m pytest -q -m "not windows"` still passes.

- [ ] **Step 5: Commit**

```powershell
git add src/kev_control/win_desktop.py tests/test_win_desktop.py
$msg = @"
Inject into an owned window only while the gate is armed.
"@
git commit -m $msg
```

---

### Task 3: Scan the screen into the existing eyes function

**Files:**
- Modify: `src/kev_control/win_desktop.py`
- Modify: `tests/test_win_desktop.py`
- Test: `tests/test_win_desktop.py`

**Interfaces:**
- Consumes: `Scan`, `OcrWord`, `UiaControl`, `ICON_CONTROL_TYPES`, `observe` from `kev_control.eyes`.
- Produces: `WinDesktop.scan(self, watch: ElementRef | None) -> Scan`. Raises `Unavailable(Ending.OCR_MISSING)` when the `en-US` OCR engine cannot be created.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from kev_control.eyes import observe
from kev_control.slots import SessionId, Utterance
from kev_control.win_desktop import WinDesktop, claim_per_monitor_v2
from tests.owned_window import owned_window

@pytest.mark.windows
def test_scan_sees_the_save_label_and_observe_keeps_it():
    claim_per_monitor_v2()
    with owned_window(button="Save", edit_label="Note") as win:
        win.focus()
        scan = WinDesktop().scan(None)
        utterance = Utterance.heard(SessionId(1), "click save")
        assert utterance is not None
        observation = observe(scan, utterance, 24)
        assert any(c.name == "Save" for c in observation.candidates)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_win_desktop.py::test_scan_sees_the_save_label_and_observe_keeps_it -v`

Expected: FAIL because `scan` is missing or returns no words.

- [ ] **Step 3: Write minimal implementation**

`scan` captures each monitor in physical pixels, runs Windows OCR `en-US`, and offsets each word by that monitor's virtual origin. It walks UI Automation for the foreground window and the taskbar (`Shell_TrayWnd`). It keeps Button, SplitButton, and Image controls with a non-empty name. It sets `own_pid` to `os.getpid()` and `own_rects` to this process's top-level windows. `watched` is `None` when `watch` is `None`.

Do not rank here. `observe` already ranks, drops this process, and drops icons whose rectangle overlaps an OCR box with IoU above 0.3.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_win_desktop.py::test_scan_sees_the_save_label_and_observe_keeps_it -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/kev_control/win_desktop.py tests/test_win_desktop.py
$msg = @"
Scan the foreground window into the existing observe function.
"@
git commit -m $msg
```

---

### Task 4: Draft unspoken text without choosing a control

**Files:**
- Modify: `src/kev_control/writer.py`
- Create: `tests/test_writer.py`
- Test: `tests/test_writer.py`

**Interfaces:**
- Consumes: `as_text`, `Text`, `Unavailable`, `Ending.WRITER_MISSING`.
- Produces: `clean_draft(raw: str, max_chars: int) -> Text | None`, `writer_prompt(utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> str`, `QwenWriter(gguf: Path, max_chars: int)`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_writer.py -v`

Expected: FAIL with `ImportError` for `clean_draft`.

- [ ] **Step 3: Write minimal implementation**

```python
def clean_draft(raw: str, max_chars: int) -> Text | None:
    line = raw.splitlines()[0].strip() if raw.strip() else ""
    if len(line) >= 2 and line[0] == line[-1] and line[0] in "\"'":
        line = line[1:-1].strip()
    return as_text(line[:max_chars])


def writer_prompt(utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> str:
    names = ", ".join(candidate_names)[:2000]
    return f"Utterance: {utterance_text}\nControl: {control_name}\nOn screen: {names}\nReply with the text to type and nothing else."
```

`QwenWriter.draft` loads the GGUF on first call. A missing file raises `Unavailable(Ending.WRITER_MISSING)`. The model returns one completion. `draft` returns `clean_draft` of that completion. Clicks never construct it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_writer.py -v`

Expected: PASS. Do not download the GGUF in this task.

- [ ] **Step 5: Commit**

```powershell
git add src/kev_control/writer.py tests/test_writer.py
$msg = @"
Clean a writer draft down to one line of text to type.
"@
git commit -m $msg
```

---

### Task 5: One waiting utterance from silence

**Files:**
- Create: `src/kev_control/ear.py`
- Create: `tests/test_ear.py`
- Test: `tests/test_ear.py`

**Interfaces:**
- Consumes: `Mailbox.put`, `Utterance.heard`, `Arm.current`.
- Produces: `segment(pcm: list[bool], silence_frames: int) -> list[bytes]` is not the API. Produces `finish_utterance(transcript: str, session: SessionId, mailbox: Mailbox) -> None` and `frames_until_silence(is_speech: list[bool], hangover: int) -> int`.

- [ ] **Step 1: Write the failing test**

```python
from kev_control.ear import finish_utterance, frames_until_silence
from kev_control.session import Mailbox
from kev_control.slots import SessionId

def test_silence_of_eight_frames_ends_after_speech():
    speech = [True, True, False, False, False, False, False, False, False, False]
    assert frames_until_silence(speech, hangover=8) == 10


def test_newer_transcript_replaces_the_waiting_utterance():
    mailbox = Mailbox(live=lambda session: session == SessionId(1))
    finish_utterance("click cancel", SessionId(1), mailbox)
    finish_utterance("please type a reply", SessionId(1), mailbox)
    assert mailbox.take().text == "please type a reply"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ear.py -v`

Expected: FAIL with `ModuleNotFoundError: kev_control.ear`.

- [ ] **Step 3: Write minimal implementation**

`frames_until_silence` returns the index after `hangover` consecutive `False` frames that follow at least one `True`. The ear thread uses that count with 100 ms frames, so 8 frames are `silence_seconds` of 0.8. `finish_utterance` calls `Utterance.heard` and `mailbox.put` only when the transcript is non-blank. A dead session is dropped by `Mailbox.take`, which already exists.

The microphone callback and faster-whisper call live in `Ear.run`. Tests do not open a device. `Ear.run` is the production body and is not what the unit test calls.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ear.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/kev_control/ear.py tests/test_ear.py
$msg = @"
Keep only the latest silence-ended utterance in the mailbox.
"@
git commit -m $msg
```

---

### Task 6: Tray process around the existing loop

**Files:**
- Create: `src/kev_control/tray.py`
- Create: `src/kev_control/app.py`
- Create: `tests/test_app.py`
- Modify: `pyproject.toml` (add the `kev-control` script and the Windows dependencies)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `run_utterance`, `Rig`, `Mailbox`, `Arm`, `Ending.message`, `Config`.
- Produces: `render(armed: bool, hearing: bool, acting: bool, last: str) -> str` and `main(argv: list[str] | None = None) -> int`. `python -m kev_control setup` prints the `kev.serve --run` command and does not start the server. `python -m kev_control` starts the tray.

- [ ] **Step 1: Write the failing test**

```python
from kev_control.tray import render

def test_render_names_acting_and_the_last_utterance():
    assert render(armed=True, hearing=False, acting=True, last="click save") == "Acting: click save"


def test_setup_prints_the_serve_command_and_does_not_listen(capsys):
    from kev_control.app import main
    assert main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "kev.serve" in out
    assert "jaredpalmer/kev-0.6b" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_app.py -v`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`render` returns `Idle` when not armed, `Hearing` when hearing, `Acting: {last}` when acting, otherwise `Armed`. It does not read Caps Lock. The tray calls `render` on a timer with facts from `Arm`, `Ear`, and `Worker`.

`Worker.run` takes from the mailbox and calls `run_utterance` with a `WinDesktop` created on that thread. It does not parse Kev JSON.

`main(["setup"])` prints `kev.serve --run jaredpalmer/kev-0.6b` using `Config().kev_checkpoint` and returns 0. `main([])` calls `claim_per_monitor_v2` before any window, then starts arm, ear, and worker threads and the tray.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_app.py tests/test_loop.py -q`

Expected: PASS. Then `python -m pytest -q`.

Expected: the full suite passes. The `windows` tests pass on this machine. They are the real-desktop check. A second monitor that is not attached is not a failure.

- [ ] **Step 5: Commit**

```powershell
git add src/kev_control/tray.py src/kev_control/app.py tests/test_app.py pyproject.toml
$msg = @"
Start the tray from the loop that already decides endings.
"@
git commit -m $msg
```

## Manual check after task 6

This is not a pytest and not a commit by itself. Open Notepad. Turn Caps Lock on. Say "type hello in the document". The field contains `hello` and the tray shows Done or the ending text from `Ending.message`. Turn Caps Lock off mid-phrase. The partial audio is dropped and nothing further is typed.

## Self-review notes

The pure loop, the System One body, the mailbox, and the miss rule are already implemented and tested (35 passed, commit `7f150ff`). Tasks 1 through 6 do not re-test those rules except where task 6 calls `run_utterance`. Spec items with no new task, because the code exists: quoted payload, 0.35 cutoff including done, off-target ids, eight injections, consecutive misses, password refusal inside `hands.plan`.
