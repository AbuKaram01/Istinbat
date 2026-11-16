#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Builds istinbat_<ver>_amd64.deb, istinbat-cuda_<ver>_amd64.deb,
# istinbat-<ver>-1.x86_64.rpm and istinbat-cuda-<ver>-1.x86_64.rpm into
# packaging/dist/.
#
# The packages ship NO Python dependencies, so they stay small. On install, the
# postinst/%post script creates a venv at /opt/istinbat/venv and runs `pip install`
# there. That needs internet access and a C++ toolchain (llama-cpp-python has no
# prebuilt wheel, so pip compiles it from source). The CPU variant installs the
# CPU-only build of PyTorch first (about 200 MB instead of several GB of CUDA libraries).
#
# Requires: dpkg-deb (Debian/Ubuntu) and rpmbuild (the `rpm` package) on the machine
# that RUNS this script, not on the machine installing the resulting packages.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$PROJECT_ROOT/packaging/work"
OUT_DIR="$PROJECT_ROOT/packaging/dist"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$PROJECT_ROOT/src/istinbat/__init__.py")"
APP_ID="io.github.AbuKaram01.Istinbat"
MAINTAINER="AbuKaram01 <AbuKaram01@users.noreply.github.com>"

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$1"; }

[ -n "$VERSION" ] || { echo "Could not read the version from src/istinbat/__init__.py." >&2; exit 1; }
command -v dpkg-deb >/dev/null 2>&1 || { echo "dpkg-deb not found — install dpkg-dev." >&2; exit 1; }
command -v rpmbuild  >/dev/null 2>&1 || { echo "rpmbuild not found — install rpm (or rpm-build on Fedora)." >&2; exit 1; }

# Clean only what this script produces, so packages built by build-arch.sh survive.
rm -rf "$WORK_DIR/cpu" "$WORK_DIR/cuda"
mkdir -p "$WORK_DIR" "$OUT_DIR"
rm -f "$OUT_DIR"/istinbat*_amd64.deb "$OUT_DIR"/istinbat*.x86_64.rpm

# ── Shared payload: identical for every variant and format ──────────────────
# Only the postinst build commands and the package metadata differ per variant.
build_payload() {
    local payload="$1"
    mkdir -p "$payload/opt/istinbat/src"
    # pip builds from this folder, so everything pyproject.toml refers to must be here.
    cp -r "$PROJECT_ROOT/src" "$PROJECT_ROOT/pyproject.toml" \
          "$PROJECT_ROOT/LICENSE" "$PROJECT_ROOT/README.md" "$payload/opt/istinbat/src/"
    find "$payload/opt/istinbat/src" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

    mkdir -p "$payload/usr/bin"
    cat > "$payload/usr/bin/istinbat" << 'LAUNCHER'
#!/bin/sh
# A real package always installs to the same place, so this path is always correct.
exec /opt/istinbat/venv/bin/python3 -m istinbat "$@"
LAUNCHER
    chmod 755 "$payload/usr/bin/istinbat"

    mkdir -p "$payload/usr/share/applications"
    cp "$PROJECT_ROOT/data/${APP_ID}.desktop" "$payload/usr/share/applications/"

    mkdir -p "$payload/usr/share/icons"
    cp -r "$PROJECT_ROOT/data/icons/hicolor" "$payload/usr/share/icons/"
}

for variant in cpu cuda; do
    case "$variant" in
        cpu)
            pkg_name="istinbat"
            conflicts_pkg="istinbat-cuda"
            torch_step='"$VENV_DIR/bin/pip" install --quiet torch --index-url https://download.pytorch.org/whl/cpu'
            cmake_env=""
            summary_suffix=""
            ;;
        cuda)
            pkg_name="istinbat-cuda"
            conflicts_pkg="istinbat"
            torch_step=""
            cmake_env='CMAKE_ARGS="-DGGML_CUDA=on" '
            summary_suffix=" (CUDA-accelerated)"
            ;;
    esac

    info "Building payload for $pkg_name..."
    variant_dir="$WORK_DIR/$variant"
    payload="$variant_dir/payload"
    build_payload "$payload"

    # ── postinst (deb) / %post (rpm) share the same body ────────────────────
    postinst_body=$(cat << POSTINST
APP_DIR=/opt/istinbat
VENV_DIR="\$APP_DIR/venv"
echo "Istinbat: setting up its Python environment — needs internet access"
echo "and a C/C++ toolchain, and can take several minutes the first time"
echo "(it compiles llama-cpp-python from source; there is no prebuilt wheel)."
if [ ! -d "\$VENV_DIR" ]; then
    python3 -m venv --system-site-packages "\$VENV_DIR"
fi
"\$VENV_DIR/bin/pip" install --upgrade pip --quiet
$torch_step
${cmake_env}"\$VENV_DIR/bin/pip" install --quiet "\$APP_DIR/src"
echo "Istinbat is ready. Find it in your applications menu, or run: istinbat"
POSTINST
)

    # ==== .deb ==============================================================
    info "Building ${pkg_name}_${VERSION}_amd64.deb..."
    deb_root="$variant_dir/deb-root"
    rm -rf "$deb_root"
    cp -r "$payload" "$deb_root"
    mkdir -p "$deb_root/DEBIAN"

    cat > "$deb_root/DEBIAN/control" << CONTROL
Package: $pkg_name
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.10), python3-venv, python3-pip, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1, adwaita-icon-theme, librsvg2-common, build-essential, cmake
Conflicts: $conflicts_pkg
Maintainer: $MAINTAINER
Description: Istinbat${summary_suffix} - ask questions about your Arabic books, fully offline
 Index your plain-text books and ask questions about them. Answers are drawn
 from the books themselves by local embedding, reranking and language models.
CONTROL

    { printf '#!/bin/sh\nset -e\n%s\nexit 0\n' "$postinst_body"; } > "$deb_root/DEBIAN/postinst"
    cat > "$deb_root/DEBIAN/postrm" << 'POSTRM'
#!/bin/sh
set -e
if [ "$1" = "purge" ] || [ "$1" = "remove" ]; then
    rm -rf /opt/istinbat/venv
fi
exit 0
POSTRM
    chmod 755 "$deb_root/DEBIAN/postinst" "$deb_root/DEBIAN/postrm"

    dpkg-deb --build --root-owner-group "$deb_root" "$OUT_DIR/${pkg_name}_${VERSION}_amd64.deb" >/dev/null
    ok "${pkg_name}_${VERSION}_amd64.deb"

    # ==== .rpm ==============================================================
    info "Building ${pkg_name}-${VERSION}-1.x86_64.rpm..."
    rpm_topdir="$variant_dir/rpmbuild"
    mkdir -p "$rpm_topdir"/{BUILD,RPMS,SOURCES,SPECS,SRPMS,BUILDROOT}

    spec_file="$rpm_topdir/SPECS/${pkg_name}.spec"
    cat > "$spec_file" << SPEC
Name: $pkg_name
Version: $VERSION
Release: 1
Summary: Istinbat${summary_suffix} - ask questions about your Arabic books, fully offline
License: AGPL-3.0-or-later
BuildArch: x86_64
Requires: python3 >= 3.10, python3-pip, python3-gobject, gtk4, libadwaita, adwaita-icon-theme, librsvg2, gcc-c++, cmake
Conflicts: $conflicts_pkg

%description
Index your plain-text books and ask questions about them. Answers are drawn
from the books themselves by local embedding, reranking and language models.
Downloads and compiles its Python dependencies on first install (needs
internet access then; not needed afterwards to run it).

%install
mkdir -p %{buildroot}
cp -a $payload/. %{buildroot}/

%files
/opt/istinbat
/usr/bin/istinbat
/usr/share/applications/*.desktop
/usr/share/icons/hicolor

%post
$postinst_body

%postun
if [ "\$1" = "0" ]; then
    rm -rf /opt/istinbat/venv
fi

%clean
rm -rf %{buildroot}
SPEC

    rpmbuild --define "_topdir $rpm_topdir" -bb "$spec_file" >/dev/null 2>&1 || \
        rpmbuild --define "_topdir $rpm_topdir" -bb "$spec_file"
    find "$rpm_topdir/RPMS" -name "*.rpm" -exec cp {} "$OUT_DIR/" \;
    ok "${pkg_name}-${VERSION}-1.x86_64.rpm"
done

echo
ok "All packages built in: $OUT_DIR"
ls -la "$OUT_DIR"
