#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# One-command installer for Istinbat on Arch Linux and its derivatives
# (Manjaro, EndeavourOS, CachyOS, Garuda, ...).
# Run from anywhere:  ./scripts/install-arch.sh [--cuda]
#
# By default it uses the CPU build of PyTorch from the repositories (python-pytorch).
# Pass --cuda to use python-pytorch-cuda and compile llama.cpp with CUDA support.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

APP_ID="io.github.AbuKaram01.Istinbat"
USE_CUDA=0
[ "${1:-}" = "--cuda" ] && USE_CUDA=1

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$1"; }
fail() { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

command -v pacman >/dev/null 2>&1 || fail "This script is for Arch-based systems (needs pacman)."
[ "$EUID" -ne 0 ] || fail "Don't run this as root — it installs into your own \$HOME. Run it as your normal user; it asks for sudo only for the system packages."

# python-pytorch and python-pytorch-cuda conflict, so exactly one of them is requested.
PACKAGES=(python python-pip python-gobject gtk4 libadwaita librsvg adwaita-icon-theme gcc make cmake)
if [ "$USE_CUDA" -eq 1 ]; then
    PACKAGES+=(python-pytorch-cuda cuda)
else
    PACKAGES+=(python-pytorch)
fi

info "Installing system packages (GTK4, libadwaita, Python bindings, PyTorch, build tools)..."
sudo pacman -S --needed --noconfirm "${PACKAGES[@]}"
ok "System packages installed."

# A virtual environment is required: Arch marks the system Python as externally managed.
# --system-site-packages lets it reuse python-gobject and python-pytorch from pacman.
if [ ! -d .venv ]; then
    info "Creating virtual environment (.venv)..."
    python3 -m venv --system-site-packages .venv
    ok "Virtual environment created."
else
    info "Reusing existing .venv"
fi

.venv/bin/pip install --upgrade pip -q

info "Installing Python dependencies (llama-cpp-python is compiled from source — this can take several minutes)..."
if [ "$USE_CUDA" -eq 1 ]; then
    CMAKE_ARGS="-DGGML_CUDA=on" .venv/bin/pip install -e . -q
else
    .venv/bin/pip install -e . -q
fi
ok "Python dependencies installed."

info "Installing the desktop launcher and app icon for your user..."
mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor
# The desktop entry's Exec command must resolve, and "istinbat" only exists inside
# .venv/bin, so the installed copy gets an absolute path.
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
