"""Global push-to-talk hotkey using pynput (works on X11 without root)."""

from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard

log = logging.getLogger(__name__)

_ALIASES = {"<super>": "<cmd>", "<win>": "<cmd>", "<windows>": "<cmd>", "<meta>": "<cmd>", "<control>": "<ctrl>"}


def parse_key_spec(spec: str) -> tuple[set, bool]:
    """Return (set of keys, is_combo).

    ``"ctrl_r"`` -> single raw key (left/right distinction preserved).
    ``"<ctrl>+<super>"`` -> combo of canonical modifier keys.
    """
    spec = spec.strip()
    if not spec:
        raise ValueError("empty hotkey")
    if "+" in spec or spec.startswith("<"):
        lowered = spec.lower()
        for alias, real in _ALIASES.items():
            lowered = lowered.replace(alias, real)
        return set(keyboard.HotKey.parse(lowered)), True
    name = spec.lower()
    if hasattr(keyboard.Key, name):
        return {getattr(keyboard.Key, name)}, False
    if len(spec) == 1:
        return {keyboard.KeyCode.from_char(spec)}, False
    raise ValueError(f"unknown key {spec!r}; use a pynput Key name like ctrl_r, alt_r, pause, f8")


class HotkeyListener:
    """Fires on_press once when the hotkey engages and on_release when it lets go."""

    def __init__(
        self,
        key_spec: str,
        cancel_spec: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_cancel: Callable[[], None],
    ):
        self.required, self.combo = parse_key_spec(key_spec)
        self.cancel_keys, _ = parse_key_spec(cancel_spec) if cancel_spec else (set(), False)
        self.on_press = on_press
        self.on_release = on_release
        self.on_cancel = on_cancel
        self.pressed: set = set()
        self.engaged = False
        self.listener = keyboard.Listener(on_press=self._press, on_release=self._release)

    def start(self) -> None:
        self.listener.start()

    def stop(self) -> None:
        self.listener.stop()

    def _norm(self, key):
        return self.listener.canonical(key) if self.combo else key

    def _press(self, key) -> None:
        try:
            if key in self.cancel_keys:
                self.on_cancel()
                return
            k = self._norm(key)
            if k in self.required:
                self.pressed.add(k)
                if not self.engaged and self.required <= self.pressed:
                    self.engaged = True
                    self.on_press()
        except Exception:
            log.exception("hotkey press handler failed")

    def _release(self, key) -> None:
        try:
            k = self._norm(key)
            self.pressed.discard(k)
            if self.engaged and k in self.required:
                self.engaged = False
                self.on_release()
        except Exception:
            log.exception("hotkey release handler failed")


def describe_key(spec: str) -> str:
    """Human-readable name for the hotkey, e.g. 'Right Ctrl'."""
    names = {
        "ctrl_r": "Right Ctrl",
        "ctrl_l": "Left Ctrl",
        "alt_r": "Right Alt",
        "alt_l": "Left Alt",
        "shift_r": "Right Shift",
        "cmd": "Super",
        "cmd_r": "Right Super",
        "pause": "Pause",
        "scroll_lock": "Scroll Lock",
        "caps_lock": "Caps Lock",
    }
    if spec in names:
        return names[spec]
    return spec.replace("<", "").replace(">", "").replace("cmd", "Super").replace("+", " + ").title()
