"""Process entry. `setup` prints the Kev server command and does not listen or inject."""

from __future__ import annotations

import sys
import threading
import time

from kev_control.arm import Arm
from kev_control.config import Config
from kev_control.decider import KevDecider
from kev_control.ear import Ear
from kev_control.loop import Rig, run_utterance
from kev_control.session import Mailbox
from kev_control.tray import render
from kev_control.win_desktop import WinDesktop, claim_per_monitor_v2
from kev_control.writer import QwenWriter

__all__ = ["Worker", "main"]


class Worker:
    """One thread. Builds the desktop on this thread, then runs each mailbox utterance."""

    def __init__(self, arm: Arm, mailbox: Mailbox, cfg: Config) -> None:
        self._arm = arm
        self._mailbox = mailbox
        self._cfg = cfg
        self.acting = False
        self.last = ""

    def run(self) -> None:
        rig = Rig(
            WinDesktop(),
            KevDecider(self._cfg.kev_url),
            QwenWriter(self._cfg.writer_gguf, self._cfg.writer_max_chars),
        )
        while True:
            utterance = self._mailbox.take()
            self.acting = True
            self.last = utterance.text
            try:
                run_utterance(utterance, rig, self._arm.gate(utterance.session), self._cfg)
            finally:
                self.acting = False


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["setup"]:
        checkpoint = Config().kev_checkpoint
        print(f"python -m kev.serve --run {checkpoint}")
        return 0
    if args:
        print("usage: python -m kev_control [setup]", file=sys.stderr)
        return 2
    claim_per_monitor_v2()
    cfg = Config()
    arm = Arm()
    mailbox = Mailbox(arm.live)
    ear = Ear(arm, mailbox, cfg)
    worker = Worker(arm, mailbox, cfg)
    threading.Thread(target=arm.run, name="kev-arm", daemon=True).start()
    threading.Thread(target=ear.run, name="kev-ear", daemon=True).start()
    threading.Thread(target=worker.run, name="kev-worker", daemon=True).start()
    _tray(arm, ear, worker)
    return 0


def _tray(arm: Arm, ear: Ear, worker: Worker) -> None:
    import pystray
    from PIL import Image

    image = Image.new("RGB", (64, 64), (20, 20, 20))
    icon = pystray.Icon("kev-control", image, "Idle")

    def refresh(icon: pystray.Icon) -> None:
        while True:
            icon.title = render(arm.current() is not None, ear.hearing(), worker.acting, worker.last)
            time.sleep(0.1)

    def setup(icon: pystray.Icon) -> None:
        threading.Thread(target=refresh, args=(icon,), name="kev-tray", daemon=True).start()

    icon.run(setup=setup)
