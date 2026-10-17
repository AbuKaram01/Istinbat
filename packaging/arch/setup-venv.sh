#!/bin/sh
# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Creates (or refreshes) Istinbat's virtual environment under /opt/istinbat/venv.
# Called by the pacman install hooks with the package variant: "cpu" or "cuda".
#
# Python modules available as system packages (PyGObject, and PyTorch on Arch) are
# reused through --system-site-packages; everything else comes from PyPI. llama-cpp-python
# has no prebuilt wheel, so pip compiles it, which needs internet access and a C++ toolchain.
#
# ISTINBAT_APP_DIR overrides the install location (used by the tests).

set -e

VARIANT="${1:-cpu}"
APP_DIR="${ISTINBAT_APP_DIR:-/opt/istinbat}"
VENV_DIR="$APP_DIR/venv"

echo "Istinbat: setting up its Python environment (needs internet access;"
echo "the first time can take several minutes while llama.cpp is compiled)."

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv --system-site-packages "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip --quiet

if [ "$VARIANT" = "cuda" ]; then
    # PyTorch comes from the python-pytorch-cuda package. Build llama.cpp with CUDA too.
    CMAKE_ARGS="-DGGML_CUDA=on" "$VENV_DIR/bin/pip" install --quiet "$APP_DIR/src"
else
    # A no-op when the system python-pytorch is visible; otherwise it fetches the small
    # CPU build instead of letting pip pick the multi-gigabyte CUDA one.
    "$VENV_DIR/bin/pip" install --quiet torch --index-url https://download.pytorch.org/whl/cpu
    "$VENV_DIR/bin/pip" install --quiet "$APP_DIR/src"
fi

echo "Istinbat is ready. Find it in your applications menu, or run: istinbat"
