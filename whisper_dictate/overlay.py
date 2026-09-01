"""Floating pill overlay at the bottom of the screen (Wispr Flow style).

States
------
IDLE        a tiny translucent pill so you know the app is running
LOADING     "Loading model…" with a shimmer
RECORDING   dark pill with a live waveform (white bars) and a red dot
PROCESSING  the waveform fades while a shimmer sweeps across
DONE        green dot + preview of the inserted text
HINT/ERROR  short text messages

The window is an override-redirect popup so it never takes keyboard focus away
from the app you are dictating into.
"""

from __future__ import annotations

import math
import time
from collections import deque

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

IDLE, LOADING, RECORDING, PROCESSING, DONE, HINT, ERROR = range(7)

_BARS = 28
_BAR_W = 3
_BAR_GAP = 3


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class Overlay(Gtk.Window):
    SIZES = {
        IDLE: (64, 8),
        LOADING: (240, 40),
        RECORDING: (220, 44),
        PROCESSING: (220, 44),
        DONE: (300, 40),
        HINT: (320, 40),
        ERROR: (360, 40),
    }

    def __init__(self, show_idle_pill: bool = True):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.show_idle_pill = show_idle_pill
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        self.composited = visual is not None and screen.is_composited()
        if self.composited:
            self.set_visual(visual)
        self.connect("draw", self._on_draw)

        self.levels: deque[float] = deque([0.0] * _BARS, maxlen=_BARS)
        self.smoothed = [0.0] * _BARS
        self.peak = 0.05
        self.state = IDLE
        self.message = ""
        self.hands_free = False
        self._anim_timer = None
        self._auto_timer = None
        self._t0 = time.monotonic()
        self.set_state(IDLE)

    # ------------------------------------------------------------------ levels
    def push_level(self, rms: float) -> None:
        """Thread-safe: called from the audio thread."""
        GLib.idle_add(self._push_level, rms)

    def _push_level(self, rms: float) -> bool:
        self.peak = max(rms, self.peak * 0.995, 0.03)
        self.levels.append(min(1.0, rms / self.peak))
        return False

    # ------------------------------------------------------------------- state
    def set_state(self, state: int, message: str = "", hands_free: bool | None = None, auto_idle_ms: int | None = None):
        if self._auto_timer is not None:
            GLib.source_remove(self._auto_timer)
            self._auto_timer = None
        self.state = state
        self.message = message
        if hands_free is not None:
            self.hands_free = hands_free
        if state == RECORDING and not message:
            self.levels.clear()
            self.levels.extend([0.0] * _BARS)
            self.smoothed = [0.0] * _BARS
        if state != RECORDING:
            self.hands_free = False if state == IDLE else self.hands_free

        w, h = self.SIZES[state]
        if state == RECORDING and self.hands_free:
            w += 90
        # A plain resize() never shrinks a mapped popup window; pinning the
        # minimum size to the target makes GTK allocate exactly w x h.
        self.set_size_request(w, h)
        self.resize(w, h)
        self._place(w, h)

        if state == IDLE and not self.show_idle_pill:
            self.hide()
        else:
            self.show_all()

        animate = state in (RECORDING, PROCESSING, LOADING)
        if animate and self._anim_timer is None:
            self._anim_timer = GLib.timeout_add(33, self._tick)
        elif not animate and self._anim_timer is not None:
            GLib.source_remove(self._anim_timer)
            self._anim_timer = None

        if auto_idle_ms:
            self._auto_timer = GLib.timeout_add(auto_idle_ms, self._back_to_idle)
        self.queue_draw()

    def _back_to_idle(self) -> bool:
        self._auto_timer = None
        self.set_state(IDLE)
        return False

    def _tick(self) -> bool:
        self.queue_draw()
        return True

    def _place(self, w: int, h: int) -> None:
        display = Gdk.Display.get_default()
        monitor = None
        try:
            seat = display.get_default_seat()
            pointer = seat.get_pointer()
            if pointer is not None:
                _, px, py = pointer.get_position()
                monitor = display.get_monitor_at_point(px, py)
        except Exception:
            monitor = None
        if monitor is None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
        wa = monitor.get_workarea()
        x = wa.x + (wa.width - w) // 2
        y = wa.y + wa.height - h - 16
        self.move(x, y)

    # -------------------------------------------------------------------- draw
    def _on_draw(self, _widget, cr: cairo.Context) -> bool:
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        radius = h / 2
        if self.state == IDLE:
            _rounded_rect(cr, 0, 0, w, h, radius)
            cr.set_source_rgba(0.10, 0.10, 0.12, 0.55 if self.composited else 1.0)
            cr.fill()
            return True

        # pill background (+ soft shadow)
        if self.composited:
            _rounded_rect(cr, 1, 2, w - 2, h - 2, radius)
            cr.set_source_rgba(0, 0, 0, 0.25)
            cr.fill()
        _rounded_rect(cr, 0, 0, w, h - 2, radius)
        if self.state == ERROR:
            cr.set_source_rgba(0.45, 0.10, 0.12, 0.96)
        else:
            cr.set_source_rgba(0.10, 0.10, 0.12, 0.94 if self.composited else 1.0)
        cr.fill()

        if self.state == RECORDING:
            self._draw_recording(cr, w, h)
        elif self.state == PROCESSING:
            self._draw_processing(cr, w, h)
        elif self.state == LOADING:
            self._draw_text(cr, w, h, self.message or "Loading model…", dot=(0.9, 0.7, 0.2), shimmer=True)
        elif self.state == DONE:
            self._draw_text(cr, w, h, self.message, dot=(0.25, 0.80, 0.45))
        elif self.state == HINT:
            self._draw_text(cr, w, h, self.message, dot=None)
        elif self.state == ERROR:
            self._draw_text(cr, w, h, self.message, dot=(1.0, 0.45, 0.45))
        return True

    def _bars_geometry(self, w: int, h: int):
        total = _BARS * _BAR_W + (_BARS - 1) * _BAR_GAP
        x0 = (w - total) / 2
        if self.state == RECORDING and self.hands_free:
            x0 -= 45
        return x0, total

    def _draw_recording(self, cr, w, h):
        x0, total = self._bars_geometry(w, h)
        cy = (h - 2) / 2
        max_h = h - 18
        levels = list(self.levels)
        for i, lvl in enumerate(levels):
            # attack fast, release slow
            target = lvl
            cur = self.smoothed[i]
            self.smoothed[i] = cur + (target - cur) * (0.7 if target > cur else 0.35)
            bar_h = max(3.0, self.smoothed[i] * max_h)
            x = x0 + i * (_BAR_W + _BAR_GAP)
            _rounded_rect(cr, x, cy - bar_h / 2, _BAR_W, bar_h, _BAR_W / 2)
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.fill()
        # red recording dot, pulsing
        t = time.monotonic() - self._t0
        pulse = 0.65 + 0.35 * math.sin(t * 4)
        cr.arc(14, cy, 4, 0, 2 * math.pi)
        cr.set_source_rgba(1.0, 0.30, 0.30, pulse)
        cr.fill()
        if self.hands_free:
            self._draw_label(cr, "hands-free", x0 + total + 14, cy, size=9, alpha=0.75)

    def _draw_processing(self, cr, w, h):
        x0, total = self._bars_geometry(w, h)
        cy = (h - 2) / 2
        t = time.monotonic() - self._t0
        for i in range(_BARS):
            self.smoothed[i] *= 0.9
            base = max(3.0, self.smoothed[i] * (h - 18))
            phase = (t * 2.2 - i * 0.22) % (2 * math.pi)
            glow = max(0.0, math.cos(phase)) ** 3
            bar_h = base + 6 * glow
            x = x0 + i * (_BAR_W + _BAR_GAP)
            _rounded_rect(cr, x, cy - bar_h / 2, _BAR_W, bar_h, _BAR_W / 2)
            cr.set_source_rgba(1, 1, 1, 0.35 + 0.6 * glow)
            cr.fill()

    def _draw_label(self, cr, text, x, cy, size=10, alpha=0.95, max_w=None):
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription(f"Sans {size}"))
        layout.set_text(text, -1)
        if max_w:
            layout.set_width(int(max_w * Pango.SCALE))
            layout.set_ellipsize(Pango.EllipsizeMode.END)
        _, logical = layout.get_pixel_extents()
        cr.move_to(x, cy - logical.height / 2)
        cr.set_source_rgba(1, 1, 1, alpha)
        PangoCairo.show_layout(cr, layout)

    def _draw_text(self, cr, w, h, text, dot, shimmer=False):
        cy = (h - 2) / 2
        x = 16
        if dot is not None:
            alpha = 1.0
            if shimmer:
                alpha = 0.5 + 0.5 * math.sin((time.monotonic() - self._t0) * 5)
            cr.arc(x, cy, 4, 0, 2 * math.pi)
            cr.set_source_rgba(*dot, alpha)
            cr.fill()
            x += 12
        self._draw_label(cr, text, x, cy, size=10, max_w=w - x - 14)
