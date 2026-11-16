# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Checks on the installation files: versions agree, scripts parse, the venv setup does the right steps."""

import os
import re
import stat
import subprocess

import pytest
from packaging_support import APP_ID, ARCH, ROOT, needs_bash

import istinbat

SCRIPTS = [
    ROOT / "packaging" / "build.sh",
    ROOT / "packaging" / "build-arch.sh",
    ROOT / "packaging" / "arch" / "setup-venv.sh",
    ROOT / "scripts" / "install-debian.sh",
    ROOT / "scripts" / "install-arch.sh",
]


def pkgbuild_value(name):
    match = re.search(rf"^{name}=(.+)$", (ARCH / "PKGBUILD").read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1).strip("'\"") if match else None


def test_the_pkgbuild_version_matches_the_package_version():
    assert pkgbuild_value("pkgver") == istinbat.__version__


def test_the_pkgbuild_builds_a_cpu_and_a_cuda_package_that_conflict():
    text = (ARCH / "PKGBUILD").read_text(encoding="utf-8")
    assert "pkgname=('istinbat' 'istinbat-cuda')" in text
    assert "conflicts=('istinbat-cuda')" in text and "conflicts=('istinbat')" in text
    assert "'python-pytorch'" in text and "'python-pytorch-cuda' 'cuda'" in text


def test_the_install_hooks_call_the_setup_script_with_their_variant():
    assert "setup-venv.sh cpu" in (ARCH / "istinbat.install").read_text(encoding="utf-8")
    assert "setup-venv.sh cuda" in (ARCH / "istinbat-cuda.install").read_text(encoding="utf-8")
    for hook in (ARCH / "istinbat.install", ARCH / "istinbat-cuda.install"):
        content = hook.read_text(encoding="utf-8")
        assert "post_install()" in content and "post_upgrade()" in content and "pre_remove()" in content


@needs_bash
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_every_shell_script_parses(script):
    assert script.exists()
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_the_app_icon_is_a_single_svg():
    icons = [path for path in (ROOT / "data" / "icons").rglob("*") if path.is_file()]
    assert [path.name for path in icons] == [f"{APP_ID}.svg"]
    assert icons[0].parent.name == "apps" and icons[0].parent.parent.name == "scalable"


def test_the_desktop_entry_points_at_the_installed_launcher_and_icon():
    entry = (ROOT / "data" / f"{APP_ID}.desktop").read_text(encoding="utf-8")
    assert "Exec=istinbat" in entry and f"Icon={APP_ID}" in entry and "Name[ar]=" in entry


def test_the_license_file_and_spdx_headers_are_present():
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    for module in (ROOT / "src" / "istinbat").rglob("*.py"):
        assert "SPDX-License-Identifier: AGPL-3.0-or-later" in module.read_text(encoding="utf-8"), module


# -- The venv setup script, run against stub commands -------------------------------

def run_setup(tmp_path, variant):
    """Run setup-venv.sh with a fake python3 whose venv has a pip that only logs its calls."""
    log = tmp_path / "pip.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        '# Handles only: python3 -m venv --system-site-packages DIR\n'
        'DIR="$4"\n'
        'mkdir -p "$DIR/bin"\n'
        "cat > \"$DIR/bin/pip\" <<'PIP'\n"
        "#!/bin/sh\n"
        f'echo "CMAKE_ARGS=[$CMAKE_ARGS] pip $*" >> "{log}"\n'
        "PIP\n"
        'chmod +x "$DIR/bin/pip"\n'
    )
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IEXEC)

    app_dir = tmp_path / "opt"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ISTINBAT_APP_DIR": str(app_dir)}
    env.pop("CMAKE_ARGS", None)
    subprocess.run(["sh", str(ARCH / "setup-venv.sh"), variant], check=True, env=env, capture_output=True)
    return log.read_text(encoding="utf-8").splitlines(), app_dir


@needs_bash
def test_the_cpu_variant_ensures_cpu_pytorch_then_installs_the_app_without_cuda(tmp_path):
    calls, app_dir = run_setup(tmp_path, "cpu")
    assert len(calls) == 3
    assert "install --upgrade pip" in calls[0]
    assert "install --quiet torch --index-url https://download.pytorch.org/whl/cpu" in calls[1]
    assert calls[2] == f"CMAKE_ARGS=[] pip install --quiet {app_dir}/src"


@needs_bash
def test_the_cuda_variant_builds_llama_cpp_with_cuda_and_does_not_touch_pytorch(tmp_path):
    calls, app_dir = run_setup(tmp_path, "cuda")
    assert len(calls) == 2 and not any("torch" in call for call in calls)
    assert calls[1] == f"CMAKE_ARGS=[-DGGML_CUDA=on] pip install --quiet {app_dir}/src"


@needs_bash
def test_an_existing_environment_is_reused_not_recreated(tmp_path):
    run_setup(tmp_path, "cpu")
    bin_dir = tmp_path / "bin"
    (bin_dir / "python3").write_text("#!/bin/sh\necho unexpected >&2\nexit 1\n")   # Would fail if called.
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ISTINBAT_APP_DIR": str(tmp_path / "opt")}
    subprocess.run(["sh", str(ARCH / "setup-venv.sh"), "cpu"], check=True, env=env, capture_output=True)


def test_the_two_build_scripts_do_not_delete_each_others_packages():
    """build.sh and build-arch.sh share packaging/dist; neither may wipe the whole folder."""
    for script in ("build.sh", "build-arch.sh"):
        text = (ROOT / "packaging" / script).read_text(encoding="utf-8")
        assert 'rm -rf "$OUT_DIR"' not in text and 'rm -rf "$WORK_DIR" "$OUT_DIR"' not in text, script
