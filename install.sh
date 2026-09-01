#!/usr/bin/env bash
# Install Whisper Dictate on Ubuntu (22.04 / 24.04, X11 session).
#
#   ./install.sh            install everything and start the app
#   ./install.sh --no-start install only
#
# What it does:
#   1. installs missing system packages (asks for sudo only if needed)
#   2. creates a Python venv at <repo>/.venv with access to the system GTK bindings
#   3. installs openai-whisper (PyTorch with CUDA) and this app into it
#   4. installs a launcher, a .desktop entry and an autostart entry
#   5. downloads the Whisper model
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO/.venv"
BIN_DIR="$HOME/.local/bin"
START=1
[[ "${1:-}" == "--no-start" ]] && START=0

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- 1. system deps
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
  warn "You are on a Wayland session. Global hotkeys and text insertion need X11."
  warn "Log out, click the gear icon on the login screen and pick 'Ubuntu on Xorg'."
fi

need=()
python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null \
  || need+=(python3-gi python3-gi-cairo gir1.2-gtk-3.0)
python3 -c "import cairo" 2>/dev/null || need+=(python3-gi-cairo)
python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1'); from gi.repository import AyatanaAppIndicator3" 2>/dev/null \
  || need+=(gir1.2-ayatanaappindicator3-0.1)
command -v parec >/dev/null || need+=(pulseaudio-utils)
command -v notify-send >/dev/null || need+=(libnotify-bin)
command -v ffmpeg >/dev/null || need+=(ffmpeg)
python3 -c "import venv" 2>/dev/null || need+=(python3-venv)

if ((${#need[@]})); then
  info "Installing system packages: ${need[*]}"
  sudo apt-get update -qq
  sudo apt-get install -y "${need[@]}"
fi

# ---------------------------------------------------------------- 2. uv + venv
if ! command -v uv >/dev/null; then
  info "Installing uv (fast Python package manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  info "Creating virtualenv at $VENV (system python, so GTK bindings are visible)"
  uv venv --system-site-packages --python "$(command -v python3)" "$VENV"
fi

# ---------------------------------------------------------------- 3. python deps
info "Installing whisper-dictate + openai-whisper (this downloads PyTorch, ~2.5 GB, first time only)"
uv pip install --python "$VENV/bin/python" -e "$REPO"

# ---------------------------------------------------------------- 4. launcher + desktop entry
mkdir -p "$BIN_DIR" "$HOME/.local/share/applications" "$HOME/.config/autostart"
cat > "$BIN_DIR/whisper-dictate" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" -m whisper_dictate "\$@"
EOF
chmod +x "$BIN_DIR/whisper-dictate"

sed "s|@EXEC@|$BIN_DIR/whisper-dictate|" "$REPO/whisper-dictate.desktop" > "$HOME/.local/share/applications/whisper-dictate.desktop"
cp "$HOME/.local/share/applications/whisper-dictate.desktop" "$HOME/.config/autostart/whisper-dictate.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not on your PATH; run it as $BIN_DIR/whisper-dictate or add the dir to PATH." ;;
esac

# ---------------------------------------------------------------- 5. model
info "Downloading the Whisper model (turbo, ~1.6 GB, first time only)"
"$VENV/bin/python" -m whisper_dictate --download-only

info "Installed."
echo "  launcher : $BIN_DIR/whisper-dictate"
echo "  config   : $("$VENV/bin/python" -m whisper_dictate --print-config-path)"
echo "  autostart: ~/.config/autostart/whisper-dictate.desktop"
echo
echo "  Hold Right Ctrl and speak; release to insert the text. Tap twice for hands-free. Esc cancels."

if ((START)); then
  info "Starting Whisper Dictate"
  nohup "$BIN_DIR/whisper-dictate" >"$HOME/.cache/whisper-dictate.log" 2>&1 &
  echo "  log      : ~/.cache/whisper-dictate.log"
fi
