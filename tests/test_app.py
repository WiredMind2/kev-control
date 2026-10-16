from kev_control.tray import render


def test_render_names_acting_and_the_last_utterance():
    assert render(armed=True, hearing=False, acting=True, last="click save") == "Acting: click save"


def test_setup_prints_the_serve_command_and_does_not_listen(capsys):
    from kev_control.app import main

    assert main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "kev.serve" in out
    assert "jaredpalmer/kev-0.6b" in out
