"""Speech in, one utterance out. Tests call the segment helpers and never open a microphone."""

from __future__ import annotations

import threading
import time

from kev_control.arm import Arm
from kev_control.config import Config
from kev_control.session import Mailbox
from kev_control.slots import SessionId, Utterance

__all__ = ["Ear", "finish_utterance", "frames_until_silence"]

_FRAME_MS = 100


def frames_until_silence(is_speech: list[bool], hangover: int) -> int:
    """Index just after `hangover` quiet frames that follow speech. One past the end if still open."""
    voiced = False
    quiet = 0
    for index, frame in enumerate(is_speech):
        if frame:
            voiced = True
            quiet = 0
            continue
        if not voiced:
            continue
        quiet += 1
        if quiet >= hangover:
            return index + 1
    return len(is_speech) + 1


def finish_utterance(transcript: str, session: SessionId, mailbox: Mailbox) -> None:
    utterance = Utterance.heard(session, transcript)
    if utterance is not None:
        mailbox.put(utterance)


class Ear:
    """Production listener. `run` is the thread body; unit tests do not call it."""

    def __init__(self, arm: Arm, mailbox: Mailbox, cfg: Config) -> None:
        self._arm = arm
        self._mailbox = mailbox
        self._cfg = cfg
        self._hearing = False
        self._lock = threading.Lock()

    def hearing(self) -> bool:
        with self._lock:
            return self._hearing

    def run(self) -> None:
        while True:
            session = self._arm.wait_armed(0.2)
            if session is None:
                self._set_hearing(False)
                continue
            self._listen(session)

    def _set_hearing(self, hearing: bool) -> None:
        with self._lock:
            self._hearing = hearing

    def _listen(self, session: SessionId) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            time.sleep(1)
            return
        rate = 16000
        frame_samples = rate * _FRAME_MS // 1000
        hangover = max(1, round(self._cfg.silence_seconds / (_FRAME_MS / 1000)))
        frames: list[bool] = []
        pcm = bytearray()
        try:
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="int16", blocksize=frame_samples)
            stream.start()
        except Exception:
            time.sleep(1)
            return
        try:
            self._set_hearing(True)
            while self._arm.current() == session:
                data, _overflowed = stream.read(frame_samples)
                samples = data[:, 0]
                frames.append(float(np.abs(samples).mean()) > 400)
                pcm.extend(samples.astype("int16").tobytes())
                end = frames_until_silence(frames, hangover)
                if end <= len(frames):
                    self._transcribe(bytes(pcm), rate, session)
                    return
        finally:
            self._set_hearing(False)
            stream.stop()
            stream.close()

    def _transcribe(self, pcm: bytes, rate: int, session: SessionId) -> None:
        if self._arm.current() != session:
            return
        try:
            import numpy as np
            from faster_whisper import WhisperModel
        except ImportError:
            return
        samples = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0
        model = WhisperModel(self._cfg.whisper_model, device=self._cfg.whisper_device, local_files_only=True)
        segments, _info = model.transcribe(samples, language=self._cfg.whisper_language)
        text = " ".join(segment.text.strip() for segment in segments)
        if self._arm.current() == session:
            finish_utterance(text, session, self._mailbox)
