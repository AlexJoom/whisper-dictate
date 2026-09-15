# Whisper Dictate

Push-to-talk voice dictation for Ubuntu, in Greek and English, running
[Whisper](https://github.com/openai/whisper) locally on your GPU (or CPU). Nothing
leaves your machine.

The interaction copies [Wispr Flow](https://wisprflow.ai/):

| Action | What happens |
| --- | --- |
| **Hold `Right Ctrl`** and speak, release | Your words are inserted at the cursor of whatever app is focused |
| **Tap `Right Ctrl` twice** | Hands-free mode: recording keeps going until you press `Right Ctrl` again |
| **`Esc`** while recording | Discards the recording |
| Tray icon | Language (Auto / Ελληνικά / English), hands-free toggle, copy last dictation, history, config, quit |

A small dark pill appears at the bottom of the screen while you dictate: a live
waveform while you talk, a shimmer while Whisper transcribes, then a short preview of
the inserted text. It never steals keyboard focus. While idle, nothing is shown; set
`show_idle_pill = true` in the `[ui]` section of the config to keep a thin bar on
screen as a sign that the app runs.

Auto-edits, like Wispr Flow:

* language of every dictation is detected automatically between Greek and English
* filler words are removed ("um", "uh", "εε", "εμ" ...)
* "new line" / "new paragraph" / "νέα γραμμή" / "νέα παράγραφος" become line breaks
* spoken punctuation works when you want to be explicit: "question mark", "comma",
  "full stop", "exclamation mark", "ερωτηματικό", "κόμμα", "τελεία", "θαυμαστικό"
  (Whisper already punctuates from your intonation, so this is optional)
* first letter of the text and of each sentence is capitalized, a space is added after
  the text so dictations chain nicely
* known Whisper hallucinations on silence ("Υπότιτλοι AUTHORWAVE", "Thank you.") are dropped
* every dictation is saved to `~/.local/share/whisper-dictate/history.jsonl`

## Requirements

* Ubuntu 22.04 / 24.04 with an **X11** session (`echo $XDG_SESSION_TYPE` must print `x11`).
  On Wayland, global hotkeys and text insertion are blocked by the compositor. Log out,
  click the gear on the login screen and choose **Ubuntu on Xorg**.
* An NVIDIA GPU with 4 GB+ VRAM for the default `turbo` model (about 1 s latency for a
  sentence). Without a GPU set `name = "small"` or `"base"` in the config and `beam_size = 1`.
* Python 3.10+ (system Python 3.12 on 24.04 works).

## Install

```bash
git clone https://github.com/AlexJoom/whisper-dictate.git
cd whisper-dictate
./install.sh
```

The script installs the few missing system packages (asks for sudo only then), creates
`.venv` in the repo, installs `openai-whisper` with PyTorch (CUDA) and the app,
downloads the `turbo` model (about 1.6 GB), adds a launcher at `~/.local/bin/whisper-dictate`,
a desktop entry and an autostart entry, and starts the app.

Start it later from the app grid ("Whisper Dictate") or:

```bash
whisper-dictate
```

## Configuration

`~/.config/whisper-dictate/config.toml` is created on first run with comments for every
option. The most useful ones:

```toml
[hotkey]
key = "ctrl_r"            # or "alt_r", "pause", "f8", "<ctrl>+<super>" ...

[model]
name = "turbo"            # tiny | base | small | medium | large-v3 | turbo
languages = ["el", "en"]  # auto-detect among these; one entry pins the language
beam_size = 5             # 1 is faster on CPU

[inject]
method = "paste"          # paste | type | xdotool | clipboard
```

Restart the app (tray icon, Quit) after editing.

## Debugging

```bash
whisper-dictate -v                      # verbose log
whisper-dictate --mic-check 4           # record 4 s and print the transcript
whisper-dictate --file some_audio.mp3   # transcribe a file through the same pipeline
pactl list sources short                # find your microphone name for [audio] source
```

Log file when started by the installer or autostart: `~/.cache/whisper-dictate.log`.

## How it works

```
Right Ctrl held ──► parec (16 kHz mono) ──► Whisper turbo (fp16, CUDA)
                                                  │ detect el/en, decode
                                                  ▼
                              clean-up (fillers, commands, caps) ──► clipboard + Ctrl+V
```

* `whisper_dictate/hotkey.py` global hotkey with pynput
* `whisper_dictate/audio.py` microphone capture through PulseAudio/PipeWire `parec`
* `whisper_dictate/engine.py` model loading (fp16 on GPU, fits in 4 GB) and transcription
* `whisper_dictate/textproc.py` auto-edits (unit tested in `tests/`)
* `whisper_dictate/inject.py` insertion into the focused window (Ctrl+Shift+V in terminals)
* `whisper_dictate/overlay.py` the bottom-of-screen pill (GTK 3 + cairo)
* `whisper_dictate/tray.py` AppIndicator menu

Run the tests with `.venv/bin/python -m pytest tests`.

## License

MIT. Whisper itself is MIT licensed by OpenAI.
