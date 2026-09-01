"""Whisper Dictate application: state machine tying hotkey, audio, model, UI together.

Interaction model (same as Wispr Flow):
  * hold the hotkey and speak, release to insert the text where your cursor is
  * tap the hotkey twice quickly for hands-free mode; press once more to stop
  * press Esc while recording to discard
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import CONFIG_PATH, HISTORY_PATH, Config, load_config
from .textproc import TextOptions, clean_transcript

log = logging.getLogger("whisper_dictate")

LOADING, IDLE, RECORDING, PROCESSING = "loading", "idle", "recording", "processing"


def notify(summary: str, body: str = "", urgency: str = "normal") -> None:
    try:
        subprocess.Popen(
            ["notify-send", "--app-name=Whisper Dictate", "--icon=audio-input-microphone", f"--urgency={urgency}", summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def xdg_open(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def acquire_single_instance_lock():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    lock_path = runtime / "whisper-dictate.lock"
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


class App:
    def __init__(self, cfg: Config, use_tray: bool = True, use_overlay: bool = True):
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk  # noqa: F401

        from .audio import Recorder
        from .engine import Engine
        from .history import History
        from .hotkey import HotkeyListener, describe_key
        from .inject import Injector
        from .overlay import Overlay

        self.GLib = GLib
        self.Gtk = Gtk
        self.cfg = cfg
        self.state = LOADING
        self.hands_free = False
        self.pending_hands_free = False
        self.last_tap = 0.0
        self.press_time = 0.0
        self.language_mode = "auto"
        self.hotkey_name = describe_key(cfg.hotkey.key)

        self.engine = Engine(
            model_name=cfg.model.name,
            device=cfg.model.device,
            languages=cfg.model.languages,
            beam_size=cfg.model.beam_size,
            initial_prompt=cfg.model.initial_prompt,
        )
        self.history = History(HISTORY_PATH)
        self.overlay = Overlay(show_idle_pill=cfg.ui.show_idle_pill) if use_overlay else None
        self.recorder = Recorder(
            sample_rate=cfg.audio.sample_rate,
            source=cfg.audio.source,
            on_level=self.overlay.push_level if self.overlay else None,
        )
        self.injector = Injector(cfg.inject)

        self.tray = None
        if use_tray and cfg.ui.tray:
            try:
                from . import tray as tray_mod

                if tray_mod.available():
                    self.tray = tray_mod.Tray(
                        languages=cfg.model.languages,
                        on_language=self.set_language_mode,
                        on_hands_free=self.tray_hands_free,
                        on_copy_last=self.copy_last,
                        on_open_config=lambda: xdg_open(CONFIG_PATH),
                        on_open_history=lambda: xdg_open(HISTORY_PATH),
                        on_quit=self.quit,
                    )
                else:
                    log.warning("AppIndicator not available; running without tray icon")
            except Exception:
                log.exception("tray init failed; continuing without it")

        self.hotkey = HotkeyListener(
            cfg.hotkey.key,
            cfg.hotkey.cancel_key,
            on_press=lambda: GLib.idle_add(self._on_press),
            on_release=lambda: GLib.idle_add(self._on_release),
            on_cancel=lambda: GLib.idle_add(self._on_cancel),
        )

    # -------------------------------------------------------------- lifecycle
    def run(self) -> None:
        GLib, Gtk = self.GLib, self.Gtk
        if self.overlay:
            self.overlay.set_state(self.overlay_states().LOADING, "Loading model…")
        threading.Thread(target=self._load_model, name="model-loader", daemon=True).start()
        self.hotkey.start()
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.quit)
        Gtk.main()

    def quit(self, *_args) -> bool:
        log.info("quitting")
        try:
            self.hotkey.stop()
        except Exception:
            pass
        self.recorder.cancel()
        self.Gtk.main_quit()
        return False

    def overlay_states(self):
        from . import overlay as ov

        return ov

    def _load_model(self) -> None:
        try:
            self.engine.load()
        except Exception as e:  # noqa: BLE001
            log.exception("model load failed")
            self.GLib.idle_add(self._fatal, f"Model load failed: {e}")
            return
        self.GLib.idle_add(self._model_ready)

    def _model_ready(self) -> bool:
        self.state = IDLE
        status = f"Ready · {self.cfg.model.name} on {self.engine.device} · hold {self.hotkey_name} to talk"
        log.info(status)
        if self.tray:
            self.tray.set_status(status)
        if self.overlay:
            self.overlay.set_state(self.overlay_states().HINT, f"Ready — hold {self.hotkey_name} and speak", auto_idle_ms=2500)
        if self.cfg.ui.notifications:
            notify("Whisper Dictate is ready", f"Hold {self.hotkey_name} and speak. Tap twice for hands-free.", "low")
        return False

    def _fatal(self, msg: str) -> bool:
        log.error(msg)
        if self.overlay:
            self.overlay.set_state(self.overlay_states().ERROR, msg)
        if self.tray:
            self.tray.set_status(msg)
        notify("Whisper Dictate", msg, "critical")
        return False

    # ------------------------------------------------------------- tray hooks
    def set_language_mode(self, code: str) -> None:
        self.language_mode = code
        log.info("language mode: %s", code)

    def tray_hands_free(self, active: bool) -> None:
        if active and self.state == IDLE:
            self.pending_hands_free = False
            self._start_recording()
            self.hands_free = True
            if self.overlay:
                self.overlay.set_state(self.overlay_states().RECORDING, hands_free=True)
        elif not active and self.state == RECORDING and self.hands_free:
            self._stop_and_transcribe()

    def copy_last(self) -> None:
        if self.history.last:
            self.injector.clipboard.set_text(self.history.last.strip(), -1)

    # ------------------------------------------------------------ hotkey flow
    def _on_press(self) -> bool:
        now = time.monotonic()
        ov = self.overlay_states()
        if self.state == LOADING:
            if self.overlay:
                self.overlay.set_state(ov.LOADING, "Still loading the model…")
            return False
        if self.state == PROCESSING:
            if self.overlay:
                self.overlay.set_state(ov.PROCESSING)
            return False
        if self.state == RECORDING:
            if self.hands_free:
                self._stop_and_transcribe()
            return False
        # IDLE -> start recording
        self.pending_hands_free = (now - self.last_tap) * 1000 < self.cfg.hotkey.double_tap_ms
        self.press_time = now
        self._start_recording()
        return False

    def _on_release(self) -> bool:
        if self.state != RECORDING or self.hands_free:
            return False
        now = time.monotonic()
        held_ms = (now - self.press_time) * 1000
        ov = self.overlay_states()
        if held_ms < self.cfg.hotkey.tap_ms:
            if self.pending_hands_free:
                self.hands_free = True
                self.last_tap = 0.0
                if self.overlay:
                    self.overlay.set_state(ov.RECORDING, hands_free=True)
                if self.tray:
                    self.tray.set_hands_free(True)
                return False
            self.last_tap = now
            self._cancel_recording()
            if self.overlay:
                self.overlay.set_state(ov.HINT, f"Hold {self.hotkey_name} to talk · tap twice for hands-free", auto_idle_ms=1800)
            return False
        self._stop_and_transcribe()
        return False

    def _on_cancel(self) -> bool:
        if self.state == RECORDING:
            self._cancel_recording()
            if self.overlay:
                self.overlay.set_state(self.overlay_states().HINT, "Cancelled", auto_idle_ms=900)
        return False

    # ------------------------------------------------------------- recording
    def _start_recording(self) -> None:
        from .audio import RecorderError

        try:
            self.recorder.start()
        except RecorderError as e:
            self._error(str(e))
            return
        self.state = RECORDING
        self.hands_free = False
        if self.overlay:
            self.overlay.set_state(self.overlay_states().RECORDING)
        if self.tray:
            self.tray.set_recording(True)

    def _cancel_recording(self) -> None:
        self.recorder.cancel()
        self.state = IDLE
        self.hands_free = False
        if self.tray:
            self.tray.set_recording(False)
            self.tray.set_hands_free(False)

    def _stop_and_transcribe(self) -> None:
        from .audio import RecorderError, duration_seconds

        ov = self.overlay_states()
        try:
            audio = self.recorder.stop()
        except RecorderError as e:
            self.state = IDLE
            self._error(str(e))
            return
        self.hands_free = False
        if self.tray:
            self.tray.set_recording(False)
            self.tray.set_hands_free(False)
        seconds = duration_seconds(audio, self.cfg.audio.sample_rate)
        if seconds < self.cfg.audio.min_duration:
            self.state = IDLE
            if self.overlay:
                self.overlay.set_state(ov.IDLE)
            return
        self.state = PROCESSING
        if self.overlay:
            self.overlay.set_state(ov.PROCESSING)
        languages = self.cfg.model.languages if self.language_mode == "auto" else [self.language_mode]
        threading.Thread(
            target=self._transcribe_worker, args=(audio, languages, seconds), name="transcribe", daemon=True
        ).start()

    def _transcribe_worker(self, audio, languages, seconds: float) -> None:
        try:
            result = self.engine.transcribe(audio, languages)
            opts = TextOptions(
                remove_fillers=self.cfg.text.remove_fillers,
                voice_commands=self.cfg.text.voice_commands,
                spoken_punctuation=self.cfg.text.spoken_punctuation,
                capitalize=self.cfg.text.capitalize,
                trailing_space=self.cfg.text.trailing_space,
            )
            text = clean_transcript(result.text, result.language, opts)
            log.info("[%s] %.1fs audio -> %.2fs infer: %r", result.language, seconds, result.seconds, text)
            self.GLib.idle_add(self._finish, text, result, seconds)
        except Exception as e:  # noqa: BLE001
            log.exception("transcription failed")
            self.GLib.idle_add(self._error, f"Transcription failed: {e}")

    def _finish(self, text: str, result, seconds: float) -> bool:
        ov = self.overlay_states()
        self.state = IDLE
        if not text:
            if self.overlay:
                self.overlay.set_state(ov.HINT, "No speech detected", auto_idle_ms=1200)
            return False
        self.injector.inject(text)
        self.history.append(text, result.language, seconds, result.seconds)
        if self.overlay:
            preview = " ".join(text.split())
            self.overlay.set_state(ov.DONE, f"{result.language.upper()} · {preview}", auto_idle_ms=1800)
        return False

    def _error(self, msg: str) -> bool:
        self.state = IDLE if self.engine.ready else LOADING
        log.error(msg)
        if self.overlay:
            self.overlay.set_state(self.overlay_states().ERROR, msg, auto_idle_ms=4000)
        if self.cfg.ui.notifications:
            notify("Whisper Dictate", msg, "critical")
        return False


# ------------------------------------------------------------------------ CLI
def _transcribe_file(cfg: Config, path: str) -> int:
    import whisper

    from .engine import Engine

    engine = Engine(cfg.model.name, cfg.model.device, cfg.model.languages, cfg.model.beam_size, cfg.model.initial_prompt)
    engine.load()
    audio = whisper.load_audio(path)
    result = engine.transcribe(audio)
    print(f"[{result.language}] raw:   {result.text}")
    print(f"[{result.language}] clean: {clean_transcript(result.text, result.language)!r}")
    return 0


def _mic_check(cfg: Config, seconds: float) -> int:
    from .audio import Recorder, duration_seconds
    from .engine import Engine

    engine = Engine(cfg.model.name, cfg.model.device, cfg.model.languages, cfg.model.beam_size, cfg.model.initial_prompt)
    engine.load()
    rec = Recorder(cfg.audio.sample_rate, cfg.audio.source)
    print(f"Recording {seconds:.0f}s from the microphone... speak now.")
    rec.start()
    time.sleep(seconds)
    audio = rec.stop()
    print(f"Captured {duration_seconds(audio):.1f}s, peak {abs(audio).max():.3f}")
    result = engine.transcribe(audio)
    print(f"[{result.language}] {clean_transcript(result.text, result.language)!r} ({result.seconds:.2f}s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whisper-dictate", description="Push-to-talk dictation with local Whisper.")
    parser.add_argument("--version", action="version", version=f"whisper-dictate {__version__}")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="path to config.toml")
    parser.add_argument("--download-only", action="store_true", help="download/load the model and exit")
    parser.add_argument("--print-config-path", action="store_true")
    parser.add_argument("--file", metavar="AUDIO", help="transcribe an audio file and print the result (debug)")
    parser.add_argument("--mic-check", type=float, metavar="SECONDS", help="record N seconds and transcribe (debug)")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--no-overlay", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)

    if args.print_config_path:
        print(args.config)
        return 0
    if args.download_only:
        from .engine import Engine

        Engine(cfg.model.name, cfg.model.device, cfg.model.languages).load()
        print(f"model {cfg.model.name!r} is ready")
        return 0
    if args.file:
        return _transcribe_file(cfg, args.file)
    if args.mic_check:
        return _mic_check(cfg, args.mic_check)

    lock = acquire_single_instance_lock()
    if lock is None:
        print("whisper-dictate is already running", file=sys.stderr)
        return 1
    app = App(cfg, use_tray=not args.no_tray, use_overlay=not args.no_overlay and cfg.ui.overlay)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
