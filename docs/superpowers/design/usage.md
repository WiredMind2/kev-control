# Kev desktop control usage

## Quickstart (the user)

```powershell
pip install kev-control
python -m kev_control setup     # downloads the Kev checkpoint, whisper small, and the Qwen2.5-1.5B GGUF
python -m kev_control serve     # runs kev.serve --run <kev_checkpoint> in this console; leave it open
python -m kev_control           # starts the tray app in a second console
```

Turn Caps Lock on and say "click save". The tray goes Armed, then Hearing, then Acting, then shows `Done` or the reason it stopped. Turn Caps Lock off to abort anything in flight.

Config lives at `%APPDATA%\kev-control\config.toml`. Every key is optional and defaults to the spec value.

```toml
kev_checkpoint = "jaredpalmer/kev-4b"   # then restart `python -m kev_control serve`
confidence_min = 0.35
```

Speech that finishes while a command is still running waits in a single slot. A newer utterance replaces a waiting one. The tray shows the waiting utterance as `Next`. Caps Lock off drops it.

## Call site 1. The app entry

The only production caller. It wires concrete adapters and starts three threads. Nothing else constructs `WinDesktop`, `KevDecider`, or `QwenWriter`.

```python
# kev_control/__main__.py
from kev_control.app import main

raise SystemExit(main())
```

```python
# kev_control/app.py
def main(argv: list[str] | None = None) -> int:
    claim_dpi_awareness()                      # before any window, COM object, or capture exists
    cfg = load_config(config_path())
    arm = Arm()
    mailbox = Mailbox(arm.live)
    ear = Ear(arm, mailbox, cfg)
    worker = Worker(arm, mailbox, cfg, make_rig=lambda: Rig(
        desktop=WinDesktop(),
        decider=KevDecider(cfg.kev_url),
        writer=QwenWriter(cfg.writer_gguf, cfg.writer_max_chars),
    ))
    for body in (arm.run, ear.run, worker.run):
        threading.Thread(target=body, daemon=True).start()
    Tray(arm, ear, worker, mailbox, cfg).run()  # main thread, returns on Quit
    return 0
```

## Call site 2. A loop unit test

Tests call `run_utterance` the way `Worker` does. The fake desktop is data. It records every plan that reached `perform`, so assertions are literal values.

```python
from kev_control.loop import run_utterance, Rig
from kev_control.ending import Ending
from kev_control.desktop import ClickAt, Point
from tests.fakes import FakeDesktop, Scene, word, ScriptedDecider, pick, NoWriter, armed, disarm_after

def test_repeat_click_on_unchanged_screen_is_refused_and_ends_stuck():
    desktop = FakeDesktop(Scene(words=[word("Save", left=100, top=200, width=40, height=20)]))
    decider = ScriptedDecider([pick("Save", "click", 0.9), pick("Save", "click", 0.9)])

    ending = run_utterance(heard("click save"), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is Ending.UNCHANGED
    assert desktop.performed == [ClickAt(Point(120, 210))]   # the second click was refused, never sent

def test_decision_that_arrives_after_disarm_injects_nothing():
    desktop = FakeDesktop(Scene(words=[word("Send", left=0, top=0, width=40, height=20)]))
    gate, decider = disarm_after(ScriptedDecider([pick("Send", "click", 0.99)]))

    ending = run_utterance(heard("click send"), Rig(desktop, decider, NoWriter()), gate, Config())

    assert ending is Ending.ABORTED
    assert desktop.performed == []

def test_eight_attempts_then_a_ninth_pick_stops():
    desktop = FakeDesktop(Scene(words=[word("Next", left=0, top=0, width=40, height=20)]), changes_on_every_click=True)
    decider = ScriptedDecider([pick("Next", "click", 0.9)] * 9)

    ending = run_utterance(heard("keep clicking next"), Rig(desktop, decider, NoWriter()), armed(), Config())

    assert ending is Ending.BUDGET
    assert len(desktop.performed) == 8
```

Speech that finishes while a command is running does not enter that command. The mailbox keeps one slot. A newer utterance replaces the waiting one. The running loop is not asked again.

```python
from kev_control.session import Mailbox

def test_newer_utterance_replaces_the_one_waiting():
    mailbox = Mailbox(live=lambda session: True)
    mailbox.put(heard("click cancel"))
    mailbox.put(heard("please type a reply"))

    assert mailbox.take().text == "please type a reply"
```

## Call site 3. The decider against a fake Kev HTTP response

The only test that sees Kev's wire format. Everything above it gets a resolved `Decision`.

```python
import httpx
from kev_control.decider import KevDecider, OffTarget

def test_target_id_not_offered_is_off_target():
    kev = httpx.MockTransport(lambda req: httpx.Response(200, json=kev_reply(target="c7", p=0.9, action="click")))
    decider = KevDecider("http://kev.test", client=httpx.Client(transport=kev))

    decision = decider.decide(heard("click save"), observation_with(["Save", "Cancel"]))

    assert decision == OffTarget("c7")
```

## Call site 4. Hands against a window this project owns

Real Windows, scripted intent, no Kev. The window is native Win32 (`BUTTON` and `EDIT` classes) on its own thread so the system UIA proxies give the button Invoke and the edit a Value pattern. Assertions read the window through its own Win32 state, not through UIA.

```python
from kev_control.desktop import WinDesktop
from kev_control.eyes import OcrCandidate
from kev_control.hands import act, Click, Type, Injected
from kev_control.slots import as_text

@pytest.mark.windows
def test_hands_invokes_save_and_types_into_note():
    with owned_window(button="Save", edit_label="Note") as win:
        desktop = WinDesktop()

        clicked = act(desktop, Click(OcrCandidate("Save", win.button_rect)), gate=lambda: True)
        typed = act(desktop, Type(OcrCandidate("Note", win.edit_rect), as_text("hello")), gate=lambda: True)

        assert isinstance(clicked, Injected) and win.button_presses() == 1
        assert isinstance(typed, Injected) and win.edit_text() == "hello"
```
