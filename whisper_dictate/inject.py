"""Insert text into whatever window currently has keyboard focus (X11).

Default strategy mirrors Wispr Flow: place the text on the clipboard, send
Ctrl+V (Ctrl+Shift+V for terminals) and then restore the previous clipboard
text. This is instant and handles Greek characters reliably. Alternatives:
simulated typing (pynput) or ``xdotool type``.

All methods must be called from the GTK main loop thread.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402
from pynput.keyboard import Controller, Key  # noqa: E402

from .config import InjectConfig  # noqa: E402

log = logging.getLogger(__name__)


class FocusInspector:
    """Reads the WM_CLASS of the active X11 window (to detect terminals)."""

    def __init__(self):
        self._display = None
        try:
            from Xlib import X, display  # noqa: F401

            self._X = X
            self._display = display.Display()
            self._root = self._display.screen().root
            self._atom = self._display.intern_atom("_NET_ACTIVE_WINDOW")
        except Exception as e:  # not on X11, or python-xlib missing
            log.info("active-window detection unavailable: %s", e)
            self._display = None

    def active_wm_class(self) -> str:
        if self._display is None:
            return ""
        try:
            prop = self._root.get_full_property(self._atom, self._X.AnyPropertyType)
            if not prop or not prop.value:
                return ""
            win = self._display.create_resource_object("window", int(prop.value[0]))
            cls = win.get_wm_class()
            return " ".join(cls).lower() if cls else ""
        except Exception as e:
            log.debug("active window lookup failed: %s", e)
            return ""


class Injector:
    def __init__(self, cfg: InjectConfig):
        self.cfg = cfg
        self.keyboard = Controller()
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.focus = FocusInspector()

    # ------------------------------------------------------------------ public
    def inject(self, text: str) -> None:
        if not text:
            return
        method = self.cfg.method
        if method == "xdotool":
            if shutil.which("xdotool"):
                self._xdotool(text)
                return
            log.warning("xdotool not installed, falling back to paste")
            method = "paste"
        if method == "type":
            self._type(text)
            return
        if method == "clipboard":
            self.clipboard.set_text(text, -1)
            return
        self._paste(text)

    # ----------------------------------------------------------------- methods
    def _xdotool(self, text: str) -> None:
        subprocess.Popen(["xdotool", "type", "--clearmodifiers", "--delay", "3", "--", text])

    def _type(self, text: str) -> None:
        # pynput's Controller is thread-safe enough for a single writer.
        threading.Thread(target=self.keyboard.type, args=(text,), daemon=True).start()

    def _paste(self, text: str) -> None:
        previous: Optional[str] = None
        if self.cfg.restore_clipboard:
            try:
                previous = self.clipboard.wait_for_text()
            except Exception:
                previous = None
        self.clipboard.set_text(text, -1)

        wm_class = self.focus.active_wm_class()
        use_shift = any(t in wm_class for t in self.cfg.terminal_classes)
        log.debug("pasting into %r (shift=%s)", wm_class, use_shift)

        def press_paste() -> bool:
            try:
                with self.keyboard.pressed(Key.ctrl):
                    if use_shift:
                        with self.keyboard.pressed(Key.shift):
                            self.keyboard.tap("v")
                    else:
                        self.keyboard.tap("v")
            except Exception:
                log.exception("sending Ctrl+V failed")
            return False

        # Give the clipboard owner change a moment to propagate, then paste.
        GLib.timeout_add(60, press_paste)

        if previous is not None:

            def restore() -> bool:
                try:
                    self.clipboard.set_text(previous, -1)
                except Exception:
                    log.exception("restoring clipboard failed")
                return False

            # The target app reads the selection right after Ctrl+V; wait before restoring.
            GLib.timeout_add(700, restore)
