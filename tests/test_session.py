from __future__ import annotations

from kev_control.session import Mailbox
from kev_control.slots import SessionId
from tests.fakes import heard


def test_newer_utterance_replaces_the_one_waiting():
    mailbox = Mailbox(live=lambda session: True)
    mailbox.put(heard("click cancel"))
    mailbox.put(heard("please type a reply"))

    assert mailbox.take().text == "please type a reply"


def test_an_utterance_from_a_dead_session_is_not_offered():
    mailbox = Mailbox(live=lambda session: session == SessionId(2))
    mailbox.put(heard("click send", session=1))

    assert mailbox.peek() is None

    mailbox.put(heard("click cancel", session=2))

    assert mailbox.take().text == "click cancel"
