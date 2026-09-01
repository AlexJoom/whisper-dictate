"""User configuration (TOML) with sane defaults.

The config file lives at ``~/.config/whisper-dictate/config.toml``. It is created
with the defaults below the first time the app starts, so users can edit it.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "whisper-dictate"
CONFIG_PATH = CONFIG_DIR / "config.toml"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "whisper-dictate"
HISTORY_PATH = DATA_DIR / "history.jsonl"

DEFAULT_CONFIG = """\
# Whisper Dictate configuration.
# Edit and restart the app (tray menu -> Quit, then launch again).

[hotkey]
# Key to hold while you speak. Single pynput key names ("ctrl_r", "alt_r",
# "pause", "f8", "scroll_lock") or combos ("<ctrl>+<super>", "<alt>+<space>").
key = "ctrl_r"
# Two quick taps of the hotkey within this window start hands-free mode
# (recording continues until you press the hotkey again).
double_tap_ms = 400
# A press shorter than this is a "tap", not a dictation.
tap_ms = 300
# Press this while recording to discard the recording.
cancel_key = "esc"

[model]
# Whisper checkpoint: tiny, base, small, medium, large-v3, turbo ...
# "turbo" (large-v3-turbo) is fast, multilingual and fits in 4 GB of VRAM.
name = "turbo"
# "auto" picks CUDA when available, otherwise CPU.
device = "auto"
# Languages you dictate in. With more than one, the language of each dictation
# is auto-detected among them. ISO 639-1 codes.
languages = ["el", "en"]
# Decoding beam size. 5 is more accurate; 1 is faster on CPU.
beam_size = 5
# Optional text that primes the decoder (e.g. names or jargon you use often).
initial_prompt = ""

[audio]
# PulseAudio/PipeWire source name (see `pactl list sources short`). Empty = default mic.
source = ""
# Recordings shorter than this (seconds) are ignored.
min_duration = 0.4

[text]
# Remove filler words such as "um", "uh", "εε", "εμ".
remove_fillers = true
# Turn "new line" / "new paragraph" / "νέα γραμμή" / "νέα παράγραφος" into line breaks.
voice_commands = true
# Capitalize the first letter of the dictation and of each new line.
capitalize = true
# Add a space after the inserted text so consecutive dictations do not stick together.
trailing_space = true

[inject]
# How the text reaches the focused app:
#   "paste"   - put the text on the clipboard and press Ctrl+V (fast, handles Greek).
#   "type"    - simulate key presses for each character (slower, no clipboard use).
#   "xdotool" - use `xdotool type` if installed.
#   "clipboard" - only copy the text; you paste it yourself.
method = "paste"
# Put the previous clipboard text back after pasting.
restore_clipboard = true
# Windows whose WM_CLASS contains one of these get Ctrl+Shift+V instead of Ctrl+V.
terminal_classes = ["terminal", "kitty", "alacritty", "xterm", "konsole", "tilix", "ptyxis", "wezterm", "foot", "ghostty"]

[ui]
# Show the small pill at the bottom of the screen while idle (like Wispr Flow).
show_idle_pill = true
# Show the floating overlay at all.
overlay = true
# Show a tray icon with a menu.
tray = true
# Desktop notifications for errors and model loading.
notifications = true
"""


@dataclass
class HotkeyConfig:
    key: str = "ctrl_r"
    double_tap_ms: int = 400
    tap_ms: int = 300
    cancel_key: str = "esc"


@dataclass
class ModelConfig:
    name: str = "turbo"
    device: str = "auto"
    languages: list[str] = field(default_factory=lambda: ["el", "en"])
    beam_size: int = 5
    initial_prompt: str = ""


@dataclass
class AudioConfig:
    source: str = ""
    min_duration: float = 0.4
    sample_rate: int = 16000


@dataclass
class TextConfig:
    remove_fillers: bool = True
    voice_commands: bool = True
    capitalize: bool = True
    trailing_space: bool = True


@dataclass
class InjectConfig:
    method: str = "paste"
    restore_clipboard: bool = True
    terminal_classes: list[str] = field(
        default_factory=lambda: [
            "terminal", "kitty", "alacritty", "xterm", "konsole", "tilix", "ptyxis", "wezterm", "foot", "ghostty",
        ]
    )


@dataclass
class UIConfig:
    show_idle_pill: bool = True
    overlay: bool = True
    tray: bool = True
    notifications: bool = True


@dataclass
class Config:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    text: TextConfig = field(default_factory=TextConfig)
    inject: InjectConfig = field(default_factory=InjectConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def _fill(dc_type, data: dict):
    """Build a dataclass from a dict, ignoring unknown keys."""
    known = set(dc_type.__dataclass_fields__)
    return dc_type(**{k: v for k, v in data.items() if k in known})


def ensure_config_file(path: Path = CONFIG_PATH) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path


def load_config(path: Path = CONFIG_PATH) -> Config:
    ensure_config_file(path)
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return Config(
        hotkey=_fill(HotkeyConfig, raw.get("hotkey", {})),
        model=_fill(ModelConfig, raw.get("model", {})),
        audio=_fill(AudioConfig, raw.get("audio", {})),
        text=_fill(TextConfig, raw.get("text", {})),
        inject=_fill(InjectConfig, raw.get("inject", {})),
        ui=_fill(UIConfig, raw.get("ui", {})),
    )
