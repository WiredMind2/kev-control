# Module map

Package `kev_control`. Each row is one file. Arrows in "Imports" point down the stack, and nothing imports upward.

| File | Owns | Package imports | Third-party it alone may import | Thread |
| --- | --- | --- | --- | --- |
| `config.py` | `Config`, TOML parsing, the key list (derived from the dataclass) | none | `tomllib` | main, at startup |
| `ending.py` | `Ending` table with every tray string, `Unavailable` | config | none | any |
| `slots.py` | `Text`, `words()`, `payload()`, `Utterance`, `SessionId` type | none | none | any |
| `arm.py` | Caps Lock reads, session ids, `Gate` | slots | `ctypes` (GetKeyState only) | Arm thread |
| `desktop.py` | `VirtualRect` and DPI, capture, OCR, UIA, `Plan`, `perform` | slots, arm, ending | `comtypes`, `winrt`, `ctypes` (user32 input and DPI) | Worker thread |
| `eyes.py` | `Candidate`, `Observation`, phrase building, merge, rank | desktop, slots | none | Worker thread, pure |
| `decider.py` | `Decision`, Kev wire format, candidate ids | eyes, slots, ending | `httpx` | Worker thread |
| `writer.py` | Writer prompt, draft cleaning, llama.cpp lifetime | slots, ending | `llama_cpp` | Worker thread |
| `hands.py` | `Intent`, `Receipt`, the plan table | desktop, eyes, slots, arm | none | Worker thread |
| `loop.py` | `run_utterance`, `judge`, `Progress`, postconditions | eyes, decider, writer, hands, desktop, ending, config, slots | none | Worker thread |
| `session.py` | `Mailbox`, `Worker`, `WorkerFact` | loop, arm, slots, ending, config | none | Worker thread |
| `ear.py` | Microphone lifetime, VAD segmentation, whisper, `EarFact` | arm, slots, session, config | `sounddevice`, `webrtcvad`, `faster_whisper` | Ear thread |
| `tray.py` | `render`, `TrayView`, the pystray icon | arm, ear, session, ending, config | `pystray`, `PIL` | main |
| `setup.py` | Model downloads, `kev.serve` argv | config | `huggingface_hub` | main, CLI only |
| `app.py` | Wiring and the CLI | everything | none | main |

## Who writes what

Every piece of mutable state has one writer. The tray merges at read time and writes nothing.

| State | Writer | Readers |
| --- | --- | --- |
| Current `SessionId` | Arm thread | Ear, Mailbox, Worker, Tray, every `Gate` |
| Pending utterance slot | Ear (put) | Worker (take), Tray (peek) |
| `EarFact` | Ear thread | Tray |
| `WorkerFact` | Worker thread | Tray |
| `WinDesktop` and its COM objects | Worker thread, which created it | nobody else |
| Loop `Progress` | a local inside one `run_utterance` call | nobody else |

## Call chain for one utterance

`Worker.run` takes from `Mailbox` and calls `loop.run_utterance`. That function calls into `eyes.observe`, `decider.decide`, `writer.draft`, and `hands.act`. `hands.act` calls `desktop.perform`, the only injector. Answering "what did the app send and why" takes three files, `loop.py`, `hands.py`, and `desktop.py`.

## Structural checks in CI

- import-linter "forbidden" contracts, one per driver row above. For example, no module except `kev_control.desktop` may import `comtypes` or `winrt`. Reaching UIA from `eyes.py` or `hands.py` then fails the build instead of quietly adding a second coordinate convention.
- import-linter "layers" contract matching the Imports column.
- pyright strict, so every `match` on `Candidate`, `Decision`, `Intent`, `Receipt`, or `Plan` must be exhaustive.
- Private helpers carry a leading underscore and each module declares `__all__`. The forbidden contracts catch the internals that matter, which are the driver imports.

## Test seams

| Seam | Fake | Covers |
| --- | --- | --- |
| `Desktop` | `FakeDesktop(Scene)`, data-only scene that records each `Plan` reaching `perform` | eyes merge and rank, hands plan table, every loop rule |
| `Decider` | `ScriptedDecider`, picks by candidate name and resolves against the live observation | loop rules without Kev |
| Kev HTTP | `httpx.MockTransport` inside a real `KevDecider` | off-target ids, malformed replies, connection refused |
| `Writer` | `NoWriter`, `FixedWriter("text")`, `EmptyWriter` | empty draft miss, writer missing |
| `Gate` | `armed()`, `disarm_after(decider)` | late reply after disarm |
| Real Windows | `owned_window()`, native Win32 BUTTON and EDIT on their own thread | `hands.act` through `WinDesktop` |
