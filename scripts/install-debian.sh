#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# One-command installer for Istinbat on Debian/Ubuntu-based systems.
# Run from anywhere:  ./scripts/install-debian.sh [--cuda]
#
# By default it installs the CPU-only build of PyTorch (small). Pass --cuda to
# use the regular PyTorch build and compile llama.cpp with CUDA support.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

APP_ID="io.github.AbuKaram01.Istinbat"
REQUIRED_PYTHON="3.10"
USE_CUDA=0
[ "${1:-}" = "--cuda" ] && USE_CUDA=1

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$1"; }
fail() { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

if ! command -v apt >/dev/null 2>&1; then
    fail "This script is for Debian/Ubuntu-based systems (needs apt)."
fi

if [ "$EUID" -eq 0 ]; then
    fail "Don't run this as root — it installs into your own \$HOME. Run it as your normal user; it asks for sudo only for the system packages."
fi

info "Installing system packages (GTK4, libadwaita, Python bindings, build tools)..."
sudo apt update -qq
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
    python3-venv python3-dev build-essential cmake adwaita-icon-theme librsvg2-common
ok "System packages installed."

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "$(printf '%s\n' "$REQUIRED_PYTHON" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_PYTHON" ]; then
    fail "Python $REQUIRED_PYTHON+ is required — found $PYTHON_VERSION."
fi
ok "Python $PYTHON_VERSION OK."

if [ ! -d .venv ]; then
    info "Creating virtual environment (.venv)..."
    python3 -m venv --system-site-packages .venv
    ok "Virtual environment created."
else
    info "Reusing existing .venv"
fi

.venv/bin/pip install --upgrade pip -q

if [ "$USE_CUDA" -eq 0 ]; then
    info "Installing CPU-only PyTorch..."
    .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu -q
fi

info "Installing Python dependencies (llama-cpp-python is compiled from source — this can take several minutes)..."
if [ "$USE_CUDA" -eq 1 ]; then
    CMAKE_ARGS="-DGGML_CUDA=on" .venv/bin/pip install -e . -q
else
    .venv/bin/pip install -e . -q
fi
ok "Python dependencies installed."

info "Installing the desktop launcher and app icon for your user..."
mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor
# GIO refuses to register a desktop entry whose Exec command cannot be resolved,
# and "istinbat" only exists inside .venv/bin, not on the system PATH. An absolute
# path always resolves, whatever the PATH.
sed "s|^Exec=istinbat|Exec=${PROJECT_ROOT}/.venv/bin/istinbat|" \
    "data/${APP_ID}.desktop" > ~/.local/share/applications/"${APP_ID}.desktop"
cp -r data/icons/hicolor/* ~/.local/share/icons/hicolor/
gtk-update-icon-cache ~/.local/share/icons/hicolor 2>/dev/null || true
ok "Desktop launcher and icon installed."

echo
ok "Istinbat is installed."
echo
echo "  Run it with:"
echo "    ${PROJECT_ROOT}/.venv/bin/istinbat"
echo
echo "  It should also now appear in your applications menu as \"Istinbat\"."
echo
echo "First launch: open Preferences (Ctrl+,) and set your books folder, your language"
echo "model (.gguf file), the embedding model folder and the reranker model folder."
