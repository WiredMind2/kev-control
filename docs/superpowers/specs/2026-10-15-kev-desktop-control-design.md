# Kev desktop control

A Windows tray app that controls the computer while Caps Lock is on. Speech starts a command. Local Kev picks a control that is already on screen. The app clicks it or types into it. Kev does not invent coordinates, buttons, or the characters that get typed.

This machine is a Windows laptop with an RTX 4050 (about 6 GB). The app is Python. The workspace starts empty. This document is the design. It does not include an implementation plan.

## Locked decisions

- The target is any Windows app, observed from the full virtual screen.
- Caps Lock is the only confirmation the user gives. On means listen and act, including send and delete. Off means inert.
- Kev stays local. The first checkpoint is `jaredpalmer/kev-0.6b`. Switching to Kev-4B is a config change and a server restart. The decider code stays the same.
- Perception is Windows OCR first. UI Automation adds icon and image buttons that OCR did not cover.
- A small local writer drafts text only when the command needs characters the user did not say.
- The only interface is a tray icon. The app does not speak.

## Session

`Arm` is the only reader of Caps Lock. It polls `GetKeyState(VK_CAPITAL)` every 50 ms and reads the toggle bit, so the key still lights the LED and still changes the OS caps state.

Caps Lock on starts an armed session. `Ear` listens for the whole session. `silence_seconds` (0.8) of silence ends one utterance. An empty transcription starts no loop. When that utterance finishes, listening continues until Caps Lock goes off.

Caps Lock off ends the session immediately:

- A partial recording is discarded.
- A Kev response that arrives after disarm is discarded.
- `Hands` checks the arm switch again immediately before every injection. A disarmed check injects nothing.

## Loop

Each utterance runs at most 8 steps. One step is one injection attempt. A re-read without an injection does not count.

1. `Eyes` observes the screen and returns at most 24 candidates.
2. `Decider` asks Kev for a target and an action.
3. The loop applies the decline rules. An immediate decline ends the utterance with no injection.
4. If the action is `type` and the utterance has no typed payload, `Writer` drafts the string.
5. `Hands` injects the action, or records a miss when the control cannot accept text.
6. The loop observes again. The postcondition decides whether that injection succeeded. Every injection attempt counts toward the budget of 8.

The utterance then ends in exactly one of these states: done, stuck, aborted, or stopped. The tray shows which one. Listening continues while Caps Lock stays on. Aborted means Caps Lock went off. Stopped means the budget ran out or a required model was unavailable. Stuck means the app had no legal action.

## Eyes

`Eyes.observe(utterance) -> list[Candidate]` reads the screen in two passes.

**OCR.** Capture the full virtual screen, including every monitor and negative coordinates. Run Windows OCR in `en-US`. Each recognized text box becomes a candidate with source `ocr`, the recognized string as its name, role `text`, and a rectangle in virtual-screen pixels.

**Icons.** Walk UI Automation for the foreground window and the taskbar. Keep controls whose type is Button, SplitButton, or Image, that have a bounding rectangle, and that have a non-empty accessible name. Drop a control when its rectangle overlaps an OCR box with intersection-over-union above 0.3. Drop any window that belongs to this process. Surviving controls become candidates with source `uia`, the accessible name, the control type as the role, and the rectangle.

**Rank.** Tokenize the utterance and each candidate name into lowercase `[a-z0-9]+` words. Score is the count of tokens that appear in both. Sort by score descending, then source `ocr` before `uia`, then top to bottom, then left to right. Keep the first 24.

Candidate ids are `c0` through `c23` in that order. They are valid for that observation only.

```text
Candidate
  id: str
  name: str
  role: str
  source: ocr | uia
  rect: x, y, width, height
```

An icon with neither OCR text nor an accessible name is not a candidate, so it cannot be targeted. Password detection happens later, on the element `Hands` resolves, because password fields are edits and this pass does not add edits.

If the `en-US` OCR language is missing, observation fails, the tray shows `English OCR is unavailable`, and the utterance ends with no click.

## Decider

`Decider` sends one `POST /v1/systemone` to `http://127.0.0.1:8008`. The model field is `kev-latest`. The running server determines the checkpoint.

The state text is the utterance plus the candidate list. Each line is the id, source, role, and name.

Two questions go in that single request:

- `target`: a choice among the candidate ids plus `done` and `stuck`. The instruction asks which control advances the utterance, whether the goal is already met (`done`), or whether none of the controls will do it (`stuck`).
- `action`: a choice of `click` or `type`. The instruction asks whether to click that control or type into it. The loop ignores `action` when `target` is `done` or `stuck`.

Kev returns a choice and a probability for each question. The loop reads the probability of the chosen target. Kev is not asked for coordinates or for the string to type.

```text
Decision
  target_id: candidate id | done | stuck
  action: click | type
  probability: float
```

A target id that was not in the offered set ends the utterance as stuck, with no injection.

If Kev is not running at the start of a step, the tray shows `Kev is not running`, the utterance ends, and the session stays armed so the next utterance tries again.

The checkpoint switch lives in config as `kev_checkpoint`. The setup command starts the server with that checkpoint. The decider keeps calling `kev-latest`.

## Typed text

`slots` extracts a payload from the utterance before the writer is considered.

1. The first quoted span, single or double quotes, is the payload.
2. Otherwise the words between a leading verb and a preposition are the payload. The verb is `type`, `write`, `enter`, or `put`. The preposition is `in`, `into`, `on`, or `at`. The match is case-insensitive.

`type hello in the search box` yields `hello`. `type "see you at 5" in Notes` yields `see you at 5` by the quote rule. `reply saying I will be late` yields no payload.

When the action is `click`, the payload is ignored and the writer stays idle. When the action is `type` and a payload exists, that payload is the text and the writer stays idle. When the action is `type` and no payload exists, `Writer` drafts the text.

## Writer

The writer is Qwen2.5-1.5B-Instruct, GGUF, on CPU. It runs only for unspoken text on a `type` action.

Its input is the utterance, the chosen control's name, and the names of the current candidates joined in rank order, truncated to 2000 characters. It does not receive a screenshot and it does not choose a control.

The drafted string is the first line of the model output, with surrounding quotes removed, truncated to 200 characters. An empty draft is a miss: nothing is typed, and the miss rule applies. A missing writer model shows `Writer is unavailable` on the tray and ends the utterance as stopped. Clicks do not require the writer.

## Hands

`Hands` checks `Arm` immediately before it injects. Disarmed means status `aborted` and no input.

**Click, UIA candidate.** Use the Invoke pattern when the element supports it. Otherwise left-click the center of its rectangle.

**Click, OCR candidate.** Ask UI Automation for the element at the rectangle center. Use Invoke when that element supports it. Otherwise left-click the center.

**Type.** Resolve a UI Automation element the same way: the candidate's element for a UIA candidate, otherwise the element at the rectangle center. A password element (`IsPassword`) ends the utterance as stuck and types nothing; the tray shows `Password field`. When the element supports a value pattern, set the value to the whole string. When the element is editable and has no value pattern, focus it and send the string with Unicode key events (`KEYEVENTF_UNICODE`), which leave Caps Lock's letter case alone. When the element cannot accept text, nothing is injected and the attempt is a miss.

Clicks are one left click at virtual-screen coordinates. The app does not right-click, drag, scroll, send shortcuts, or start a shell.

## Postconditions

After an injection the loop observes again.

- A `type` step succeeds when the resolved element's value contains the injected string.
- A `click` step succeeds when any of these changed: the invoked element's toggle, expand, or selection state; the focused element; the virtual screen's OCR text; the set of candidate names.
- An OCR-only click with no element state succeeds when the OCR text changed.

An unchanged screen is a miss. A `type` attempt that injects nothing because the control cannot accept text is also a miss. The loop observes again and asks Kev again. `Hands` refuses a second injection that matches the miss: same action, same text, and a rectangle within 4 pixels on each edge. That refusal is the second miss. Two misses end the utterance as stuck. The tray shows `Screen did not change`. The utterance is not done.

Eight injection attempts without `done` end the utterance as stopped. The tray shows `Stopped after 8 steps`.

`done` from Kev, with probability at or above the cutoff, ends the utterance with no injection. The tray shows the utterance as done.

## Decline rules

Caps Lock is the only confirmation the user gives. The app still stops itself when it has nothing legal to do:

| Condition | Result |
| --- | --- |
| Microphone missing | Tray `No microphone`. No utterance starts. Session stays armed. |
| English OCR missing | Tray `English OCR is unavailable`. Utterance stopped. |
| Kev not running | Tray `Kev is not running`. Utterance stopped. Session stays armed. |
| No candidates | Utterance stuck. No click. |
| Chosen target probability under 0.35 | Utterance stuck. Tray `Not sure`. No click. This applies to `done` as well. |
| Password field | Utterance stuck. Tray `Password field`. No typing. |
| Target id not offered to Kev | Utterance stuck. No click. |
| `type` where the control cannot accept text | Miss. Nothing is clicked instead. |
| Writer model missing | Utterance stopped. Tray `Writer is unavailable`. |
| Writer draft empty | Miss. Nothing is typed. |

The cutoff `0.35` is `confidence_min` in config.

## Tray

The tray icon is the only UI. It shows one of: Idle (Caps Lock off), Armed, Hearing, Acting. It also shows the last utterance and the latest error or ending state from the rules above.

## Configuration

```text
kev_url            http://127.0.0.1:8008
kev_checkpoint     jaredpalmer/kev-0.6b
whisper_model      small
whisper_device     cpu
whisper_language   en
writer_gguf        path to Qwen2.5-1.5B-Instruct
confidence_min     0.35
step_budget        8
silence_seconds    0.8
max_candidates     24
writer_max_chars   200
```

`kev_checkpoint` may be set to `jaredpalmer/kev-4b`. The user restarts the Kev server after changing it. The setup command passes `kev_checkpoint` to `kev.serve --run`.

## Setup

A documented setup command downloads the Kev checkpoint, the whisper model, and the writer weights. The running app does not download them. The user starts the Kev server separately. The app only checks that the server answers.

## Modules

Each module has one job. Tests substitute fakes at these boundaries.

| Module | Job |
| --- | --- |
| `arm` | Report whether Caps Lock is on, and signal abort. |
| `ear` | Yield utterance strings while armed. |
| `slots` | Extract a typed payload from an utterance. |
| `eyes` | Return ranked candidates for one observation. |
| `decider` | Turn an utterance and candidates into one Kev decision. |
| `writer` | Draft unspoken text for one control. |
| `hands` | Inject one click or one type, after the arm check. |
| `loop` | Run the step budget, postconditions, and decline rules. |
| `tray` | Show the session state and the last utterance. |

## Tests

Unit tests use fakes for the arm state, OCR boxes, UI Automation icons, and the Kev HTTP response. They do not touch the user's real apps. They cover:

- Merging OCR boxes with non-overlapping named icon buttons, dropping overlapping buttons, dropping icons with an empty name, excluding this process, and capping at 24.
- Ranking by shared words, with OCR winning a tie, then reading order.
- The quote rule and the verb-preposition rule, including an utterance with no payload.
- Rejection of a target id that was not offered to Kev.
- The 0.35 cutoff, including a low-probability `done`.
- Password refusal with no injection.
- One re-ask after an unchanged screen, and a stop when the second decision repeats the same click.
- A stop at 8 injection attempts.
- Disarm checked before injection, including a decision that arrives after disarm.

One integration test creates a window this project owns, with a button labeled Save and a text field labeled Note. A scripted decision, not live Kev, drives `Hands` against that window: the button is invoked, and the field's value becomes the injected string.

Live microphone, Kev's judgment on other applications, and the wording the writer produces are a manual smoke test in Notepad. They are not part of CI.

## Out of scope

No wake word, no fine-tune of Kev, no shell, no per-action confirm dialog, no speech output, no right-click, no drag, no scroll, and no keyboard shortcuts. The app does not download models by itself.
