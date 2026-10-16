# kev-control

A Windows tray app that acts while Caps Lock is on. Speech starts a command. A local [Kev](https://github.com/jaredpalmer/kev) model picks a control that is already on screen. The app clicks it or types into it. Kev is not asked for coordinates or for the characters to type.

## Requirements

- Windows
- Python 3.12 or newer
- A microphone
- English (`en-US`) Windows OCR
- A Kev server listening at `http://127.0.0.1:8008`

The writer is a local Qwen2.5-1.5B-Instruct GGUF. Clicks do not need it. Typing unspoken text does.

## Install

```powershell
git clone https://github.com/WiredMind2/kev-control.git
cd kev-control
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,windows]"
```

## Run

Kev runs in its own process. This app only calls it.

```powershell
python -m kev_control setup
```

That prints the server command for the default checkpoint `jaredpalmer/kev-0.6b`:

```powershell
python -m kev.serve --run jaredpalmer/kev-0.6b
```

Leave that console open. Start the tray in a second one:

```powershell
python -m kev_control
```

Turn Caps Lock on and say `click save`. The tray tooltip moves through Armed, Hearing, and Acting. Turn Caps Lock off to drop a partial recording and to refuse any click or keystroke still in flight.

Speech that finishes while a command is running waits in one slot. A newer utterance replaces the one that is waiting.

## What a command can do

One utterance gets at most eight injections. Each step looks at the screen, asks Kev which on-screen control to use, then clicks or types.

- A click uses the control's Invoke pattern when it has one, otherwise a left click at the center of its box.
- `type hello in the search box` types `hello`. A quoted span is used as-is.
- If the command needs text you did not say, the writer drafts one short line.
- A password field, a pick below 0.35 confidence, or a screen that does not change ends the command with no further input.

The app does not right-click, drag, scroll, send shortcuts, or start a shell. It does not speak, and it does not download models.

## Defaults

The tray process uses the defaults in `src/kev_control/config.py`. It does not read a config file.

| Setting | Default |
| --- | --- |
| `kev_url` | `http://127.0.0.1:8008` |
| `kev_checkpoint` | `jaredpalmer/kev-0.6b` |
| `whisper_model` | `small` (CPU, English) |
| `writer_gguf` | `%LOCALAPPDATA%\kev-control\models\qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| `confidence_min` | `0.35` |
| `step_budget` | `8` |
| `silence_seconds` | `0.8` |

`load_config` can parse `%APPDATA%\kev-control\config.toml`. Wiring that file into the tray is still separate from startup.

## Tests

```powershell
pytest
```

Unit tests use fakes and do not click or type on the real desktop. Tests marked `windows` need a real Windows desktop.

The design notes are in `docs/superpowers/specs/2026-10-15-kev-desktop-control-design.md`.
