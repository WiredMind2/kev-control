"""Kev desktop control package sketch.

One file, one banner per module. modules.md maps each banner to its file, owner, and thread.
Bodies raise NotImplementedError. Comments mark only the logic a signature cannot show.
Target is Python 3.12 under pyright strict, so `match` plus `assert_never` makes sum types exhaustive.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NewType, Protocol

if TYPE_CHECKING:
    import httpx


# =============================================================================
# kev_control/config.py
# =============================================================================

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


def config_path() -> Path:
    raise NotImplementedError


def load_config(path: Path) -> Config:
    """Parse TOML into Config. A missing file means all defaults.

    The accepted keys are derived from Config's dataclass fields, so a new setting is one field.
    Unknown keys, wrong types, and out-of-range numbers raise ConfigError.
    max_candidates is in 1..253. done and stuck take two of System One's 255 options.
    The default stays 24.
    """
    raise NotImplementedError


# =============================================================================
# kev_control/ending.py
# =============================================================================


class Outcome(enum.Enum):
    DONE = "done"
    STUCK = "stuck"
    ABORTED = "aborted"
    STOPPED = "stopped"


class Ending(enum.Enum):
    """Every way one utterance ends, with its tray text. No other module holds tray strings."""

    DONE = (Outcome.DONE, "Done")
    ABORTED = (Outcome.ABORTED, "Caps Lock off")
    NO_CANDIDATES = (Outcome.STUCK, "Nothing on screen to act on")
    NOT_SURE = (Outcome.STUCK, "Not sure")
    KEV_STUCK = (Outcome.STUCK, "No control on screen does that")
    OFF_TARGET = (Outcome.STUCK, "Kev chose a control it was not offered")
    PASSWORD = (Outcome.STUCK, "Password field")
    UNCHANGED = (Outcome.STUCK, "Screen did not change")
    BUDGET = (Outcome.STOPPED, "Stopped after {step_budget} steps")
    OCR_MISSING = (Outcome.STOPPED, "English OCR is unavailable")
    KEV_DOWN = (Outcome.STOPPED, "Kev is not running")
    KEV_BAD_REPLY = (Outcome.STOPPED, "Kev sent a reply the app cannot read")
    WRITER_MISSING = (Outcome.STOPPED, "Writer is unavailable")

    @property
    def outcome(self) -> Outcome:
        return self.value[0]

    def message(self, cfg: Config) -> str:
        return self.value[1].format(step_budget=cfg.step_budget)


class Unavailable(Exception):
    """A required local dependency is missing or unreachable.

    Adapters translate their own failures (connection refused, missing GGUF, missing OCR language)
    into this at their boundary. run_utterance is the only place that catches it.
    """

    def __init__(self, ending: Ending) -> None:
        self.ending = ending


# =============================================================================
# kev_control/slots.py
# =============================================================================

Text = NewType("Text", str)
"""A non-empty string the app may type. Built only by as_text."""

TYPE_VERBS = frozenset({"type", "write", "enter", "put"})
PREPOSITIONS = frozenset({"in", "into", "on", "at"})


def as_text(s: str) -> Text | None:
    raise NotImplementedError


def words(s: str) -> list[str]:
    """Lowercase `[a-z0-9]+` tokens. The one tokenizer for ranking and for OCR read-back."""
    raise NotImplementedError


def payload(utterance_text: str) -> Text | None:
    """The text the user spoke for typing, or None when they did not say it.

    1. The first quoted span, single or double quotes.
    2. Otherwise the words between a leading verb in TYPE_VERBS and the first PREPOSITIONS word after it.
    """
    # A single quote opens a span only at the start or after whitespace and closes only before
    # whitespace, punctuation, or the end, so "type don't panic in notes" is not a quote.
    raise NotImplementedError


SessionId = NewType("SessionId", int)
"""Minted only by Arm. Defined here so slots stays a leaf module."""


@dataclass(frozen=True)
class Utterance:
    session: SessionId
    text: str
    payload: Text | None  # payload(text), computed once here

    @staticmethod
    def heard(session: SessionId, transcript: str) -> Utterance | None:
        """None for a blank transcript, so an empty transcription starts no loop."""
        raise NotImplementedError


# =============================================================================
# kev_control/arm.py
# =============================================================================


class Gate(Protocol):
    """True while the session that minted this gate is still armed."""

    def __call__(self) -> bool: ...


def _caps_toggle_bit() -> bool:
    """GetKeyState(VK_CAPITAL) & 1. Arm is the only caller in the package."""
    raise NotImplementedError


class Arm:
    """Sole reader of Caps Lock and sole writer of the session id.

    Each off-to-on edge seen by the 50 ms poll mints the next SessionId. The next on-to-off edge ends it.
    Work carries the id it started under, so a result from an old session can never act inside a newer
    one, even when Caps Lock went off and on again while a Kev call was in flight.
    """

    def __init__(self, read_toggle: Callable[[], bool] = _caps_toggle_bit, period_s: float = 0.05) -> None:
        raise NotImplementedError

    def run(self) -> None:
        """Thread body. Polls forever."""
        raise NotImplementedError

    def current(self) -> SessionId | None:
        raise NotImplementedError

    def live(self, session: SessionId) -> bool:
        # Re-reads the toggle bit instead of trusting the last poll, so the check Hands makes
        # right before injecting is fresh, not up to 50 ms old.
        raise NotImplementedError

    def gate(self, session: SessionId) -> Gate:
        raise NotImplementedError

    def wait_armed(self, timeout_s: float) -> SessionId | None:
        raise NotImplementedError


# =============================================================================
# kev_control/desktop.py   (the only module that touches UIA, Windows OCR, capture, or SendInput)
# =============================================================================


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class VirtualRect:
    """Physical pixels in virtual-screen space.

    The origin is the primary monitor's top-left, so left and top go negative on monitors placed
    left of or above it. OCR boxes, UIA rectangles, and click points all live in this one space.
    Only desktop.py builds these from Windows data. Tests build them directly.
    """

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center(self) -> Point:
        return Point(self.left + self.width // 2, self.top + self.height // 2)

    def iou(self, other: VirtualRect) -> float:
        raise NotImplementedError

    def near(self, other: VirtualRect, tolerance: int) -> bool:
        """Each of the four edges within tolerance pixels."""
        raise NotImplementedError

    def contains(self, p: Point) -> bool:
        raise NotImplementedError


ElementKey = NewType("ElementKey", tuple[int, ...])
"""UIA RuntimeId. Equal keys mean the same live element."""


class ElementRef(Protocol):
    """Opaque element handle. Only the Desktop that minted it can read or act on it."""


@dataclass(frozen=True)
class OcrWord:
    text: str
    rect: VirtualRect
    line: int  # index of the OCR line this word came from, unique within one scan


@dataclass(frozen=True)
class UiaControl:
    name: str
    control_type: str
    rect: VirtualRect
    pid: int
    ref: ElementRef


@dataclass(frozen=True)
class ElementState:
    """What postconditions compare. None means the element lacks that pattern."""

    toggle: str | None
    expand: str | None
    selected: bool | None
    text: str | None  # ValuePattern, then TextPattern, then LegacyIAccessible. "" from ValuePattern is the text. None means that pattern is absent. OCR is not used here.


class Gone(enum.Enum):
    GONE = "gone"


@dataclass(frozen=True)
class Scan:
    """One raw read of the screen. Eyes turns it into an Observation."""

    words: tuple[OcrWord, ...]
    controls: tuple[UiaControl, ...]  # ICON_CONTROL_TYPES under the foreground window and the taskbar
    own_pid: int
    own_rects: tuple[VirtualRect, ...]  # this process's visible windows, such as the tray tooltip and menu
    focused: ElementKey | None
    watched: ElementState | Gone | None  # state of the element passed as `watch`, None when nothing was watched


ICON_CONTROL_TYPES = frozenset({"Button", "SplitButton", "Image"})


class ValueCap(enum.Enum):
    NONE = "none"
    READ_ONLY = "read_only"
    WRITABLE = "writable"


@dataclass(frozen=True)
class ElementInfo:
    """What Hands needs to choose a plan for one element, read just before acting."""

    ref: ElementRef
    key: ElementKey
    rect: VirtualRect
    is_password: bool
    can_invoke: bool
    value: ValueCap
    editable: bool  # keyboard-focusable Edit or Document, or exposes TextPattern
    state: ElementState


@dataclass(frozen=True)
class Invoke:
    element: ElementRef


@dataclass(frozen=True)
class ClickAt:
    point: Point


@dataclass(frozen=True)
class SetValue:
    element: ElementRef
    text: Text


@dataclass(frozen=True)
class FocusAndType:
    element: ElementRef
    key: ElementKey
    text: Text


Plan = Invoke | ClickAt | SetValue | FocusAndType
"""Every input the app can send. There is no right-click, drag, scroll, shortcut, or shell variant."""


class Performed(enum.Enum):
    INJECTED = "injected"
    DISARMED = "disarmed"
    FOCUS_REFUSED = "focus_refused"


class Desktop(Protocol):
    """The Windows seam. Three calls hide capture, OCR, UIA, DPI, and input injection.

    One instance belongs to one thread, because UIA COM objects are bound to the apartment that made them.
    """

    def scan(self, watch: ElementRef | None) -> Scan:
        """Raises Unavailable(OCR_MISSING) when the en-US OCR engine cannot be created."""
        ...

    def inspect(self, at: ElementRef | Point) -> ElementInfo | None:
        """The element itself, or the element at a point. None when nothing is there."""
        ...

    def perform(self, plan: Plan, gate: Gate) -> Performed:
        """The only code path in the package that changes another app.

        Checks gate immediately before each mutating call, so a disarm between focusing and typing
        still sends no keys.
        """
        ...


def claim_dpi_awareness() -> None:
    """SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2). main() calls it before anything else.

    In that mode capture bitmaps, UIA BoundingRectangle, GetSystemMetrics virtual-screen bounds, and
    SetCursorPos all speak physical pixels, which is what makes VirtualRect one space.
    """
    raise NotImplementedError


class WinDesktop:
    """Desktop over UIA (comtypes), Windows.Media.Ocr (winrt), GDI capture, and SendInput."""

    def __init__(self) -> None:
        # Fails loudly when the process DPI context is not PER_MONITOR_AWARE_V2. Under any other
        # context UIA rectangles and capture pixels disagree on scaled monitors and clicks land wrong.
        raise NotImplementedError

    def scan(self, watch: ElementRef | None) -> Scan:
        # Capture and OCR each monitor separately, offset by that monitor's physical origin. A tile larger
        # than OcrEngine.MaxImageDimension is downscaled and its boxes scaled back up in _to_virtual.
        # OCR runs per monitor so one tile never spans a DPI boundary.
        raise NotImplementedError

    def inspect(self, at: ElementRef | Point) -> ElementInfo | None:
        raise NotImplementedError

    def perform(self, plan: Plan, gate: Gate) -> Performed:
        # ClickAt uses SetCursorPos then one SendInput left down and up, which avoids the rounding of
        # MOUSEEVENTF_ABSOLUTE normalization. FocusAndType calls SetFocus, confirms the focused
        # RuntimeId equals plan.key, checks the gate, then sends the whole string as one SendInput batch
        # of KEYEVENTF_UNICODE events, two per UTF-16 unit.
        raise NotImplementedError


# =============================================================================
# kev_control/ear.py
# =============================================================================


@dataclass(frozen=True)
class Notice:
    text: str
    at: float  # time.monotonic(), so the tray can pick the newest message across actors


@dataclass(frozen=True)
class EarFact:
    hearing: bool
    notice: Notice | None  # "No microphone"


@dataclass(frozen=True)
class Waiting:
    pass


@dataclass(frozen=True)
class Speaking:
    started: float
    last_voice: float


SegmentState = Waiting | Speaking


def segment(state: SegmentState, voiced: bool, now: float, silence_s: float) -> tuple[SegmentState, bool]:
    """Advance utterance segmentation by one 30 ms VAD frame. The bool is True when an utterance just ended."""
    raise NotImplementedError


class Ear:
    """Records only while armed and turns speech into Utterances in the mailbox."""

    def __init__(self, arm: Arm, mailbox: Mailbox, cfg: Config) -> None:
        raise NotImplementedError

    def run(self) -> None:
        """Thread body.

        Waits for a session, opens the microphone for that session only, and closes it on disarm.
        """
        # With no device, publish "No microphone" and retry each second while the session lives.
        # Buffer frames, run webrtcvad per frame, feed segment(). On an ended utterance, transcribe
        # with faster-whisper, then put Utterance.heard(...) unless the session died meanwhile.
        # Whenever arm.current() differs from the recording's session, drop the buffer unheard.
        raise NotImplementedError

    def fact(self) -> EarFact:
        raise NotImplementedError


# =============================================================================
# kev_control/eyes.py
# =============================================================================


@dataclass(frozen=True)
class OcrCandidate:
    name: str
    rect: VirtualRect

    source = "ocr"
    role = "text"


@dataclass(frozen=True)
class UiaCandidate:
    name: str
    control_type: str
    rect: VirtualRect
    ref: ElementRef

    source = "uia"

    @property
    def role(self) -> str:
        return self.control_type


Candidate = OcrCandidate | UiaCandidate
"""An OCR candidate never carries an element and a UIA candidate always does."""


@dataclass(frozen=True)
class Observation:
    candidates: tuple[Candidate, ...]  # ranked, at most max_candidates. Position i is id c{i}.
    words: tuple[OcrWord, ...]  # every OCR word, uncapped, for postconditions
    focused: ElementKey | None
    watched: ElementState | Gone | None

    @property
    def ocr_text(self) -> str:
        raise NotImplementedError

    @property
    def names(self) -> frozenset[str]:
        raise NotImplementedError


def observe(scan: Scan, utterance: Utterance, max_candidates: int) -> Observation:
    """Pure. Builds phrases, merges named icons, ranks, caps.

    OCR words whose center falls in scan.own_rects are dropped, so the tray tooltip that echoes the
    utterance can never become the best-scoring candidate. Controls are dropped when the name is empty,
    the pid is scan.own_pid, or IoU with any OCR phrase exceeds 0.3.
    Rank is shared-word count descending, then ocr before uia, then top, then left.
    """
    raise NotImplementedError


def _phrases(scan_words: Sequence[OcrWord]) -> list[OcrCandidate]:
    # Words of one OCR line join into a phrase until a horizontal gap wider than the line's median word
    # height. Windows OCR returns "File Edit View" as one line, and its center would click "Edit".
    raise NotImplementedError


# =============================================================================
# kev_control/decider.py
# =============================================================================


class Action(enum.Enum):
    CLICK = "click"
    TYPE = "type"


@dataclass(frozen=True)
class Pick:
    candidate: Candidate
    action: Action
    p: float


@dataclass(frozen=True)
class Done:
    p: float


@dataclass(frozen=True)
class Stuck:
    p: float


@dataclass(frozen=True)
class OffTarget:
    raw: str


Decision = Pick | Done | Stuck | OffTarget
"""Resolved against the observation it was asked about. Candidate ids never leave decider.py."""


class Decider(Protocol):
    def decide(self, utterance: Utterance, observation: Observation) -> Decision:
        """Raises Unavailable(KEV_DOWN) or Unavailable(KEV_BAD_REPLY)."""
        ...


def state_text(utterance: Utterance, observation: Observation) -> str:
    """Utterance line, then one `c{i} {source} {role} {name}` line per candidate."""
    raise NotImplementedError


class KevDecider:
    """One POST /v1/systemone per decision, model kev-latest. The server picks the checkpoint."""

    def __init__(self, url: str, client: httpx.Client | None = None, timeout_s: float = 30.0) -> None:
        raise NotImplementedError

    def decide(self, utterance: Utterance, observation: Observation) -> Decision:
        raise NotImplementedError


def _request_body(state: str, candidate_count: int) -> dict[str, object]:
    # Two questions in one request. target choices are c0..c{n-1} plus done and stuck, and
    # action choices are click and type. Field names follow kev.serve and stay private here.
    raise NotImplementedError


def _parse_reply(body: object, observation: Observation) -> Decision:
    # Validate the JSON shape. The cutoff reads answers.target.probabilities[choice],
    # not a separate confidence field. Map c{i} to observation.candidates[i].
    # Any id outside the offered set becomes OffTarget(raw).
    raise NotImplementedError


# =============================================================================
# kev_control/writer.py
# =============================================================================


class Writer(Protocol):
    def draft(self, utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> Text | None:
        """None is an empty draft. Raises Unavailable(WRITER_MISSING)."""
        ...


def writer_prompt(utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> str:
    """Candidate names joined in rank order, truncated to 2000 characters. No screenshot."""
    raise NotImplementedError


def clean_draft(raw: str, max_chars: int) -> Text | None:
    """First line, stripped, one matching pair of surrounding quotes removed, then truncated."""
    raise NotImplementedError


class QwenWriter:
    """Qwen2.5-1.5B-Instruct GGUF on CPU via llama-cpp-python, temperature 0."""

    def __init__(self, gguf: Path, max_chars: int) -> None:
        # Loads lazily on first draft, so a missing file costs nothing until a type step needs it.
        raise NotImplementedError

    def draft(self, utterance_text: str, control_name: str, candidate_names: Sequence[str]) -> Text | None:
        raise NotImplementedError


# =============================================================================
# kev_control/hands.py
# =============================================================================


@dataclass(frozen=True)
class Click:
    candidate: Candidate


@dataclass(frozen=True)
class Type:
    candidate: Candidate
    text: Text


Intent = Click | Type
"""Typed text is non-empty by construction, so an empty draft cannot reach Hands."""


class Decline(enum.Enum):
    PASSWORD = "password"
    CANNOT_ACCEPT_TEXT = "cannot_accept_text"


@dataclass(frozen=True)
class Injected:
    intent: Intent
    plan: Plan
    element: ElementInfo | None  # None only for a click where nothing answered at the point


@dataclass(frozen=True)
class Declined:
    reason: Decline


@dataclass(frozen=True)
class Disarmed:
    pass


Receipt = Injected | Declined | Disarmed


def plan(intent: Intent, element: ElementInfo | None) -> Plan | Decline:
    """Pure decision table.

    A click is Invoke when the element supports it, else ClickAt the candidate's center.
    A type with no element is CANNOT_ACCEPT_TEXT. A password is PASSWORD. A writable value is SetValue.
    An editable element is FocusAndType. Anything else is CANNOT_ACCEPT_TEXT.
    """
    raise NotImplementedError


def act(desktop: Desktop, intent: Intent, gate: Gate) -> Receipt:
    """Resolve, plan, perform. Stateless across steps."""
    # element = desktop.inspect(candidate.ref if UiaCandidate else candidate.rect.center)
    # A FOCUS_REFUSED perform is Declined(CANNOT_ACCEPT_TEXT), since keys would go to the wrong control.
    raise NotImplementedError


# =============================================================================
# kev_control/loop.py
# =============================================================================


@dataclass(frozen=True)
class Rig:
    desktop: Desktop
    decider: Decider
    writer: Writer


@dataclass(frozen=True)
class MissKey:
    """What a miss tried. The next intent that matches it is refused without injecting."""

    action: Action
    text: Text | None
    rect: VirtualRect

    def matches(self, intent: Intent) -> bool:
        """Same action, same text, rectangle within 4 px on each edge."""
        raise NotImplementedError


@dataclass(frozen=True)
class Progress:
    """Loop state between steps.

    attempts counts every step where Kev picked a candidate, injected or not.
    last_miss is set by a miss and cleared by a hit, so a second miss in a row is the only way
    to reach UNCHANGED. The field is both the miss count and the refusal key.
    """

    attempts: int = 0
    last_miss: MissKey | None = None

    def refuses(self, intent: Intent) -> bool:
        raise NotImplementedError

    def record(self, miss: MissKey | None) -> Progress | Ending:
        """attempts + 1. A miss while last_miss is set returns Ending.UNCHANGED."""
        raise NotImplementedError


def judge(decision: Decision, progress: Progress, cfg: Config) -> Pick | Ending:
    """Pure decline table, checked in this order.

    OffTarget is OFF_TARGET. p under confidence_min is NOT_SURE, for done and stuck too.
    Done is DONE. Stuck is KEV_STUCK. A Pick with attempts already at step_budget is BUDGET.
    """
    raise NotImplementedError


def compose(pick: Pick, utterance: Utterance, observation: Observation, writer: Writer) -> Intent | None:
    """Click ignores the payload. Type uses the spoken payload, else a draft. None is an empty draft."""
    raise NotImplementedError


def succeeded(receipt: Injected, before: Observation, after: Observation) -> bool:
    """Pure postcondition.

    A type succeeds when the watched element's read-back text contains the typed string.
    ValuePattern is asked first. A returned string, including "", is the text, and OCR is not consulted.
    None means that pattern is absent. Then TextPattern, then LegacyIAccessible, each with the same rule.
    Only when every pattern is absent does the check use OCR words inside the element's rectangle in `after`.
    The last min(6, n) tokens of the typed string must appear there as a contiguous run, because the caret
    sits at the end of what was typed and the tail is what stays scrolled into view. A string with no
    tokens succeeds when the OCR words in that rectangle changed.
    A click succeeds when the watched state changed or is GONE, focus changed, OCR text changed,
    or the candidate names changed.
    """
    raise NotImplementedError


def run_utterance(utterance: Utterance, rig: Rig, gate: Gate, cfg: Config) -> Ending:
    """Run one utterance to exactly one Ending."""
    # try:
    #   progress, before = Progress(), observe(rig.desktop.scan(None), utterance, cfg.max_candidates)
    #   loop:
    #     if not gate(): return ABORTED
    #     if not before.candidates: return NO_CANDIDATES          # Kev is not called
    #     decision = rig.decider.decide(utterance, before)
    #     if not gate(): return ABORTED                           # late reply discarded before the writer runs
    #     verdict = judge(decision, progress, cfg); return it if it is an Ending
    #     intent = compose(verdict, utterance, before, rig.writer)
    #     watch = None
    #     if intent is None: miss = MissKey(TYPE, None, verdict.candidate.rect)
    #     elif progress.refuses(intent): miss = key of intent
    #     else match hands.act(rig.desktop, intent, gate):
    #       Disarmed: return ABORTED
    #       Declined(PASSWORD): return PASSWORD
    #       Declined(CANNOT_ACCEPT_TEXT): miss = key of intent
    #       Injected as r: watch = r.element.ref if r.element else None; miss decided after the re-read
    #     after = observe(rig.desktop.scan(watch), utterance, cfg.max_candidates)
    #     if injected: miss = None if succeeded(r, before, after) else key of intent
    #     progress = progress.record(miss); return it if it is an Ending
    #     before = after
    # except Unavailable as e: return e.ending
    raise NotImplementedError


# =============================================================================
# kev_control/session.py
# =============================================================================


class Mailbox:
    """One pending utterance between Ear and Worker. A put replaces whatever is waiting.

    take() skips utterances whose session is no longer live, so disarm empties the slot without
    anyone clearing it.
    """

    def __init__(self, live: Callable[[SessionId], bool]) -> None:
        # One threading.Condition guards the single slot. Ear is the only putter, Worker the only taker.
        raise NotImplementedError

    def put(self, utterance: Utterance) -> None:
        raise NotImplementedError

    def take(self) -> Utterance:
        raise NotImplementedError

    def peek(self) -> Utterance | None:
        raise NotImplementedError


@dataclass(frozen=True)
class Finished:
    utterance: Utterance
    ending: Ending
    at: float


@dataclass(frozen=True)
class WorkerFact:
    acting: Utterance | None
    last: Finished | None


class Worker:
    def __init__(self, arm: Arm, mailbox: Mailbox, cfg: Config, make_rig: Callable[[], Rig]) -> None:
        raise NotImplementedError

    def run(self) -> None:
        """Thread body. Builds the rig on this thread, then takes and runs utterances one at a time."""
        raise NotImplementedError

    def fact(self) -> WorkerFact:
        raise NotImplementedError


# =============================================================================
# kev_control/tray.py
# =============================================================================


class TrayMode(enum.Enum):
    IDLE = "Idle"
    ARMED = "Armed"
    HEARING = "Hearing"
    ACTING = "Acting"


@dataclass(frozen=True)
class TrayView:
    mode: TrayMode
    last_utterance: str | None
    message: str | None  # newest of the ear notice and the last ending
    next_utterance: str | None


def render(armed: bool, ear: EarFact, worker: WorkerFact, pending: Utterance | None, cfg: Config) -> TrayView:
    """Pure merge of facts each actor owns. Mode precedence is Idle, Acting, Hearing, Armed."""
    raise NotImplementedError


class Tray:
    """pystray icon on the main thread. Reads facts every 100 ms and redraws when render() changes."""

    def __init__(self, arm: Arm, ear: Ear, worker: Worker, mailbox: Mailbox, cfg: Config) -> None:
        raise NotImplementedError

    def run(self) -> None:
        raise NotImplementedError


# =============================================================================
# kev_control/setup.py
# =============================================================================


def download_models(cfg: Config) -> None:
    """Kev checkpoint, whisper model, and writer GGUF into MODELS_DIR. Skips files already present."""
    raise NotImplementedError


def kev_serve_argv(cfg: Config) -> list[str]:
    """argv for `python -m kev_control serve`, which runs kev.serve --run with cfg.kev_checkpoint."""
    raise NotImplementedError


# =============================================================================
# kev_control/app.py
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    """`python -m kev_control [setup | serve]`. With no subcommand, runs the tray app. See usage.md."""
    raise NotImplementedError
