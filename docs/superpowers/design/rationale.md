# Kev desktop control design rationale

## Problem

Build a Windows tray app that acts on any app while Caps Lock is on. Speech becomes an utterance. Local Kev picks one of at most 24 on-screen candidates and says click or type. The app injects it, re-reads the screen, and decides from a postcondition whether the step worked. The spec locks the product (Caps Lock arm, local Kev, OCR plus named icons, writer only for unspoken text, tray only, no shell). The shape is non-obvious for four reasons. Three threads (Caps Lock poll, microphone, loop) share one notion of "still armed", and a late result must never act. OCR pixels, UIA rectangles, and click points must agree on one coordinate space across scaled monitors. The postcondition needs state from both the read side (OCR, focus) and the write side (the element that was injected). And the spec leaves six loop rules open, resolved below. The workspace is empty, so Phase A had no existing system to integrate.

## Usage (caller's view)

See `usage.md`. The user runs `python -m kev_control setup`, then `serve`, then the tray app. There are four call sites. `app.main` is the only production wiring. A loop unit test calls `run_utterance(utterance, Rig(FakeDesktop, ScriptedDecider, NoWriter), gate, Config())` and asserts a literal `Ending` plus the literal list of `Plan` values that reached `perform`. A decider test feeds a real `KevDecider` a fake HTTP reply and asserts `OffTarget("c7")`. An integration test drives `hands.act` through a real `WinDesktop` against a native Win32 window the test owns, then reads the window's own state. The sketch was reconciled to these call sites. For example, the refusal assertion in call site 2 is why the loop records plans at the `perform` boundary rather than counting Kev calls.

## Shape

**Data first.** Every domain variant is a sum type, per type-system-discipline. `Candidate = OcrCandidate | UiaCandidate`, so an OCR candidate cannot carry an element and a UIA candidate cannot lack one. `Decision = Pick | Done | Stuck | OffTarget` is resolved inside the decider against the observation it was asked about, so candidate ids (`c0`..`c23`) never leave `decider.py` and stale ids cannot reach the loop. `Intent = Click | Type(text: Text)`, where `Text` is non-empty by construction, so an empty draft cannot reach Hands. `Plan = Invoke | ClickAt | SetValue | FocusAndType` is the complete list of inputs the app can send. Right-click, drag, scroll, shortcuts, and shell have no variant, so "out of scope" is enforced by the type, not a review comment. `Ending` is one enum table that pairs each ending with its `Outcome` and tray string, per model-the-domain, so the decline table lives once.

**Three-call Windows seam.** `Desktop` has `scan(watch)`, `inspect(at)`, and `perform(plan, gate)`. Behind it sit GDI capture, per-monitor Windows OCR, the UIA walk, the DPI convention, the value read-back ladder, SetFocus verification, and SendInput. `perform` is the only function that changes another app, and it checks the gate immediately before each mutating call. Eyes and hands are policy over that seam. `eyes.observe(scan, utterance, n)` and `hands.plan(intent, element)` are pure, per boundary-discipline. This is the deepest interface in the design and the reason it beats the spec-literal split (see Alternatives).

**Sessions as ids, not booleans.** `Arm` is the single writer of the current `SessionId`, minted on each off-to-on edge. Every utterance carries the id it was heard under, and `Gate` compares ids plus a fresh toggle-bit read. A Kev reply that lands after Caps Lock went off and back on belongs to a dead session and cannot inject. A boolean "armed" flag would let it. Disarm needs no cleanup step. The mailbox skips dead-session utterances on take, and the loop's gate fails, so restart and disarm converge on the same state, per make-operations-idempotent.

**Per-actor facts for the tray.** Ear owns `EarFact`, Worker owns `WorkerFact`, Arm owns the session, the mailbox owns the pending slot. `tray.render` merges them on read and writes nothing, per separate-before-serializing-shared-state. No lock guards tray state because no tray state is shared.

**Loop as a fold.** `Progress(attempts, last_miss)` is the whole loop state, local to one call. `judge` is the pure decline table, `compose` picks payload or draft, `succeeded` is the pure postcondition, and `record` advances `Progress`. `run_utterance` is the thin shell that calls ports in order. A reader answers "why did it stop" from `judge` and `record` alone, per minimize-reader-load.

**Gap resolutions.**

- *Speech during a running loop.* It goes to a single-slot mailbox. A newer utterance replaces a waiting one, the running loop is never interrupted, and the tray shows the waiting one as `Next`. Caps Lock off drops it through the session id. A FIFO queue would replay a command the user repeated because nothing seemed to happen, which under Caps Lock can mean sending twice. Dropping speech while busy would lose the correction "no, click cancel". Interrupting would make speech a second abort channel competing with Caps Lock, which the spec makes the only confirmation.
- *Two misses.* Consecutive. A successful postcondition clears the miss. `last_miss: MissKey | None` is both the counter and the refusal key, so the rule falls out of the data. A per-utterance total would end a long, mostly working command for two unrelated hiccups, and the budget of 8 already bounds total work. As a result, after any miss the next step either succeeds or ends `UNCHANGED`.
- *Type read-back without a value pattern.* After the injection, the re-scan reads the watched element's text through ValuePattern, then the TextPattern document range, then the LegacyIAccessible value. A returned string, including an empty one, is the text. An empty value means the typed string is not in the field, so the step is a miss, and OCR is not consulted. `None` means that pattern is absent. Only when every pattern is absent does the check use OCR words inside the element's rectangle. The last min(6, n) tokens of the typed string must appear there as a contiguous run, because the caret ends at the typed tail and that is what stays in view. A string with no `[a-z0-9]` tokens succeeds when the OCR words in that rectangle changed. The same `slots.words` tokenizer serves ranking and read-back. Win11 Notepad's edit exposes TextPattern, so the common case reads real text (inferred from UIA docs, not measured here).
- *One coordinate space.* `main` claims Per-Monitor-V2 DPI awareness before any window, COM object, or capture exists, and `WinDesktop.__init__` refuses to start under any other context. In that mode, GDI capture, UIA `BoundingRectangle`, virtual-screen metrics, and `SetCursorPos` all use physical pixels (inferred from Win32 docs, flagged in risks). OCR runs per monitor, so no bitmap spans a DPI boundary. Each word box is offset by that monitor's physical origin, which may be negative, and scaled back up if the tile was downscaled below `OcrEngine.MaxImageDimension`. Clicks use `SetCursorPos` plus one SendInput down and up, which avoids the rounding in absolute-coordinate normalization. `VirtualRect` is the only rectangle type, and only `desktop.py` builds it from Windows data.
- *Zero candidates.* The loop skips the Kev call and ends `NO_CANDIDATES` (stuck). With no candidates Kev could only answer done or stuck, and the spec's decline table already says stuck. No attempt is counted.
- *What counts toward 8.* Every step where Kev picked a candidate counts. That includes a refused repeat, a control that cannot accept text, and an empty draft, because each is a step the loop committed to and then failed. Observe-only re-reads and terminal answers do not count. The budget is checked in `judge` when Kev picks again, so a goal reached on the eighth injection still ends `DONE` on the next ask. Only a ninth pick ends `BUDGET`. The miss rule runs in `record` first, so a second miss on step 8 reports the real cause, `Screen did not change`.
- *Which probability is the cutoff.* `_parse_reply` reads `answers.target.probabilities[choice]`. It does not read a separate confidence field. `load_config` rejects `max_candidates` above 253, because `done` and `stuck` take two of the 255 options System One allows. The default remains 24.

**Other decisions the spec left open.** The refusal check moved from Hands into `Progress.refuses`, so Hands is stateless and behavior matches the spec. Kev replies that fail to parse end `KEV_BAD_REPLY` (stopped) instead of masquerading as "Kev is not running". OCR lines split into phrases at gaps wider than the line's median word height, because Windows OCR returns a menu bar as one line whose center hits the wrong item. OCR words inside this process's own windows are dropped, because the tray tooltip echoes the utterance and would otherwise rank first. The verb-preposition slot rule uses the first preposition after the verb. Quotes cover the rest.

**Red-flag screen.** These were fixed during the sketch.

- *Information leakage.* The spec-literal Eyes and Hands would both resolve UIA elements and both own the DPI convention, so both moved behind `Desktop`.
- *Split ownership.* Tray status written by three actors became per-actor facts merged in `render`.
- *Hand-synced list.* Tray strings and the decline table became the one `Ending` enum, and config keys derive from `Config`'s fields.
- *Importable internals.* import-linter forbids every module except `desktop.py` from importing `comtypes` or `winrt`, per encode-lessons-in-structure.
- *Pass-through.* No `Eyes` class wraps `Desktop`. `observe` is a pure function over `Scan`.
- *Two ways to do one task.* The loop checks the gate twice only to exit early and skip the writer. `perform` is the single safety check. That is one guarantee plus a fast path, and the docstrings say which is which.
- *Shallow module.* None remain. `WinDesktop` is a large implementation behind three methods, which is the intended deep module.

## Synthesis decision

The base is the Opus sketch. The cross-judge scored it 24 to 17. The same score follows from reading both sketches against the spec. The two-miss rule is consecutive. A second miss ends the utterance even when the control differs. The Grok sketch treated a different control as a fresh try, which lets more than two misses continue. The arm check is an argument of the only injection call. Candidate ids are resolved inside the decider.

Three grafts from the Grok sketch, redesigned into this shape rather than pasted.

- The cutoff reads the chosen option's probability. `max_candidates` cannot exceed 253. The default stays 24.
- An empty value-pattern read is the field's text. OCR is used only when no text pattern exists.
- `usage.md` has a mailbox test. A newer finished utterance replaces the one waiting. The running loop is not a second consumer of that slot.

Rejected from the Grok sketch. A miss fingerprint that clears when the target changes. An arm check that is only a convention inside Hands. Candidate ids that are not bound to the observation that produced them. A command queue. A DPI scale on every rectangle. Calling Kev when the candidate list is empty.

## Tradeoffs accepted

- We accept a large `WinDesktop` behind three methods in exchange for one owner of coordinates, element resolution, and the only injection path.
- We accept that a waiting utterance can be replaced without running (it is visible as `Next`) in exchange for never replaying a stale or repeated command.
- We accept that refusal state lives in the loop rather than in Hands as the spec words it, in exchange for a stateless Hands whose behavior is a pure table.
- We accept OCR read-back only when the element exposes no text pattern, in exchange for not treating a nearby label as a successful type into an empty field.
- We accept two early gate checks in the loop that duplicate what `perform` guarantees, in exchange for not running the CPU writer for seconds after the user disarmed.
- We accept lazy writer loading, which adds first-type latency, in exchange for click-only sessions never paying its RAM.
- We accept that a click moves the user's pointer and leaves it there, because restoring it can close the hover menu the click just opened.

## Alternatives considered

- **Spec-literal Eyes and Hands, each wrapping Windows directly.** It lost on interface depth. Both modules need UIA element resolution and the DPI convention, so one decision lives in two places, Hands must keep refusal history across steps, and every test fake is written twice. Callers gain nothing from the extra surface.
- **Sans-IO loop as a generator that yields effects (observe, decide, draft, inject) to a driver.** The core becomes fully pure. But Python cannot tie each effect to its result type, so every resume needs a narrowing cast, and the driver turns into a pass-through dispatcher. Readers trace a send and yield protocol. The fake-desktop tests already give literal assertions without it.
- **Event bus where Arm, Ear, Loop, and Tray exchange messages and the loop reduces over events.** Abort becomes an event every loop state must handle, and the pre-injection check still needs a synchronous read, so there would be two abort mechanisms. The session-id gate gives the same guarantee with one comparison.

## Open questions and risks

- Does `GetKeyState(VK_CAPITAL) & 1` update on a polling thread that has no message queue? This is a guess, not verified. If it does not, `_caps_toggle_bit` needs a message-only window or `AttachThreadInput` plus `GetKeyboardState`.
- What are the exact request and response fields of `POST /v1/systemone`, and does the reply carry the chosen target's probability directly? The sketch keeps them private to `_request_body` and `_parse_reply` so only those change.
- What is the exact `kev.serve --run` argv? `kev_serve_argv` is the one place it lives.
- Should whisper output with a high no-speech probability or under two words be dropped? A hallucinated "Thank you." under Caps Lock can click something real, and the spec allows send and delete.
- Is the phrase-split gap threshold right on real menus and toolbars? It should be prototyped on a few screens before ranking tests freeze it.
- Do Per-Monitor-V2 capture rectangles and UIA rectangles agree on a scaled second monitor? This is inferred from docs. No capture library that sets its own DPI context should be used.
- Should a refused repeat show a different tray string from an unchanged screen? The spec gives both `Screen did not change`.
- The integration test must run the owned window's message loop on a thread other than the UIA caller's, or UIA calls into the same process deadlock.

## Next implementation step

Spike `WinDesktop.scan` with Per-Monitor-V2 on this laptop plus a scaled external monitor, and confirm that an OCR word's center and the UIA rectangle of the same button agree within 2 pixels, since the `Desktop` seam changes if they do not.
