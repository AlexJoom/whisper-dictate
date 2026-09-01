import pytest

pynput = pytest.importorskip("pynput")

from pynput import keyboard  # noqa: E402

from whisper_dictate.hotkey import describe_key, parse_key_spec  # noqa: E402


def test_single_key():
    keys, combo = parse_key_spec("ctrl_r")
    assert keys == {keyboard.Key.ctrl_r}
    assert combo is False


def test_combo_with_super_alias():
    keys, combo = parse_key_spec("<ctrl>+<super>")
    assert combo is True
    assert keyboard.Key.ctrl in keys and keyboard.Key.cmd in keys


def test_unknown_key():
    with pytest.raises(ValueError):
        parse_key_spec("not_a_key")


def test_describe():
    assert describe_key("ctrl_r") == "Right Ctrl"
    assert "Super" in describe_key("<ctrl>+<super>")
