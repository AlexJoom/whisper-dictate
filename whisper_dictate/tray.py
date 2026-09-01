"""System tray indicator with a small menu (language, hands-free, history, quit)."""

from __future__ import annotations

import logging
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

log = logging.getLogger(__name__)

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
except (ValueError, ImportError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator  # type: ignore # noqa: E402
    except (ValueError, ImportError):
        AppIndicator = None

LANGUAGE_NAMES = {"el": "Ελληνικά", "en": "English"}

ICON_IDLE = "audio-input-microphone-symbolic"
ICON_RECORDING = "media-record"


def available() -> bool:
    return AppIndicator is not None


class Tray:
    def __init__(
        self,
        languages: list[str],
        on_language: Callable[[str], None],
        on_hands_free: Callable[[bool], None],
        on_copy_last: Callable[[], None],
        on_open_config: Callable[[], None],
        on_open_history: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        if AppIndicator is None:
            raise RuntimeError("AppIndicator not available")
        self.indicator = AppIndicator.Indicator.new(
            "whisper-dictate", ICON_IDLE, AppIndicator.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Whisper Dictate")

        menu = Gtk.Menu()
        self.status_item = Gtk.MenuItem(label="Loading model…")
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)
        menu.append(Gtk.SeparatorMenuItem())

        group = None
        auto_label = "Auto (" + "/".join(code.upper() for code in languages) + ")"
        choices = [("auto", auto_label)] + [(code, LANGUAGE_NAMES.get(code, code.upper())) for code in languages]
        self._lang_items: dict[str, Gtk.RadioMenuItem] = {}
        for code, label in choices:
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            group = group or item
            item.connect("toggled", lambda it, c=code: it.get_active() and on_language(c))
            menu.append(item)
            self._lang_items[code] = item
        menu.append(Gtk.SeparatorMenuItem())

        self.hands_free_item = Gtk.CheckMenuItem(label="Hands-free recording")
        self.hands_free_item.connect("toggled", lambda it: on_hands_free(it.get_active()))
        menu.append(self.hands_free_item)
        menu.append(Gtk.SeparatorMenuItem())

        copy_item = Gtk.MenuItem(label="Copy last dictation")
        copy_item.connect("activate", lambda _i: on_copy_last())
        menu.append(copy_item)
        cfg_item = Gtk.MenuItem(label="Open config file")
        cfg_item.connect("activate", lambda _i: on_open_config())
        menu.append(cfg_item)
        hist_item = Gtk.MenuItem(label="Open history")
        hist_item.connect("activate", lambda _i: on_open_history())
        menu.append(hist_item)
        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _i: on_quit())
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)
        self._syncing = False

    def set_status(self, text: str) -> None:
        self.status_item.set_label(text)

    def set_recording(self, recording: bool) -> None:
        self.indicator.set_icon_full(ICON_RECORDING if recording else ICON_IDLE, "Whisper Dictate")

    def set_hands_free(self, active: bool) -> None:
        if self.hands_free_item.get_active() != active:
            self.hands_free_item.set_active(active)

    def set_language(self, code: str) -> None:
        item: Optional[Gtk.RadioMenuItem] = self._lang_items.get(code)
        if item is not None and not item.get_active():
            item.set_active(True)
