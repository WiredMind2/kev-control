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
