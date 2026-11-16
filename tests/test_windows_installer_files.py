# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Checks on the files of the Windows installer: the Inno Setup script, the PowerShell scripts, and what the
installer carries (the GTK runtime, Python and the Python libraries)."""

import subprocess

import pytest
from packaging_support import APP_ID, ROOT, WINDOWS, needs_pwsh

import istinbat

POWERSHELL_SCRIPTS = [
    ROOT / "scripts" / "install-windows.ps1",
    ROOT / "scripts" / "uninstall-windows.ps1",
    ROOT / "packaging" / "build-windows.ps1",
    ROOT / "scripts" / "gtk-portable.ps1",
    ROOT / "scripts" / "python-bundle.ps1",
    ROOT / "scripts" / "vcruntime-bundle.ps1",
    ROOT / "packaging" / "windows" / "check-installed.ps1",
    ROOT / "packaging" / "windows" / "run-installer.ps1",
]


def test_the_windows_icon_and_installer_files_exist():
    assert (ROOT / "data" / "windows" / "istinbat.ico").is_file()
    assert (WINDOWS / "istinbat.iss").is_file()
    for script in POWERSHELL_SCRIPTS:
        assert script.is_file(), script


def test_the_installer_script_matches_the_package_version_and_app_id():
    text = (WINDOWS / "istinbat.iss").read_text(encoding="utf-8")
    assert f'#define AppVersion "{istinbat.__version__}"' in text
    assert f'#define AppId "{APP_ID}"' in text
    assert istinbat.APP_ID == APP_ID


def test_the_installer_runs_the_install_script_per_user_and_cleans_up_after_itself():
    text = (WINDOWS / "istinbat.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert "scripts\\install-windows.ps1" in text and "-NoShortcut" in text
    assert "{localappdata}\\istinbat\\gtk" in text and "{app}\\.venv" in text
    assert "-m istinbat" in text
    deletions = [
        line.lower() for line in text.split("[UninstallDelete]")[1].split("[Code]")[0].splitlines()
        if line.strip() and not line.startswith(";")
    ]
    for kept in ("models", "chroma_db", "conversations", "settings", "documents"):
        assert not any(kept in line for line in deletions), kept  # User data is never deleted.


def test_pygobject_is_not_requested_from_pypi_on_windows():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "\"PyGObject; sys_platform != 'win32'\"" in text


def test_the_install_script_follows_the_runtime_that_the_application_looks_for():
    text = (ROOT / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")
    portable = (ROOT / "scripts" / "gtk-portable.ps1").read_text(encoding="utf-8")  # Where Test-GtkRuntime lives.
    assert "'istinbat'" in text and "'gtk'" in text  # %LOCALAPPDATA%\istinbat\gtk, see winsupport.
    assert "ISTINBAT_GTK_DIR" in text and "-m istinbat" in text
    assert "Adw-1.typelib" in portable
    assert "*adwaita-1-*.dll" in portable                     # The DLL is adwaita-1-0.dll, not libadwaita-...


@pytest.mark.parametrize("name", ["install-windows.ps1", "uninstall-windows.ps1"])
def test_the_windows_scripts_refuse_to_run_elsewhere_with_a_clear_message(name):
    text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    assert "$env:OS -ne 'Windows_NT'" in text and "install-debian.sh" in text
    # The check has to come before anything that needs Windows.
    assert text.index("Windows_NT") < text.index("$env:LOCALAPPDATA")


@needs_pwsh
@pytest.mark.parametrize("script", POWERSHELL_SCRIPTS, ids=lambda path: path.name)
def test_every_powershell_script_parses(script, tmp_path):
    checker = tmp_path / "parse.ps1"
    checker.write_text(
        "param($Path)\n"
        "$errors = $null; $tokens = $null\n"
        "[System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null\n"
        "if ($errors.Count) { $errors | ForEach-Object { Write-Output $_.Message }; exit 1 }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(checker), str(script)], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout


def test_the_windows_icon_ships_with_the_sources():
    from istinbat import winsupport

    icon = winsupport.icon_file()
    assert icon is not None and icon.name == "istinbat.ico"
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"  # An ICO header with at least one image.


# --- The GTK runtime inside the Windows installer ---

def test_the_windows_installer_carries_the_gtk_runtime_when_one_was_prepared():
    text = (WINDOWS / "istinbat.iss").read_text(encoding="utf-8")
    assert "#if DirExists(GtkFolder)" in text and 'DestDir: "{app}\\gtk"' in text
    assert 'gtk-portable.ps1"; DestDir: "{app}\\scripts"' in text  # The install script needs it.
    # An upgrade replaces the runtime as a whole, so no file of an older one stays beside the new DLLs ...
    assert 'Type: filesandordirs; Name: "{app}\\gtk"' in text.split("[InstallDelete]")[1].split("[Icons]")[0]
    # ... and the uninstaller removes it, with the one an older installer downloaded.
    removed = text.split("[UninstallDelete]")[1].split("[Code]")[0]
    assert '"{app}\\gtk"' in removed and '"{localappdata}\\istinbat\\gtk"' in removed


def test_the_build_prepares_the_gtk_runtime_afresh_and_can_pin_it():
    build = (ROOT / "packaging" / "build-windows.ps1").read_text(encoding="utf-8")
    assert "Get-PortableGtk" in build and "gtk-portable.ps1" in build
    for option in ("NoGtk", "GtkTag", "GtkSha256", "GtkZip"):
        assert f"${option}" in build, option
    assert build.index("Remove-Item $gtkBundle") < build.index("Get-PortableGtk -Target")  # Never an old runtime.
    assert "/packaging/gtk/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_the_install_script_uses_the_runtime_inside_the_installer_before_downloading_one():
    install = (ROOT / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")
    assert "gtk-portable.ps1" in install and "Resolve-GtkChoice" in install
    assert "function Test-GtkRuntime" not in install  # One definition, in gtk-portable.ps1.
    assert install.index("Resolve-GtkChoice -Explicit") < install.index("Get-PortableGtk -Target $GtkDir")
    # The bundled runtime is found by itself: nothing to save.
    assert "$CustomGtk   = $gtkChoice.Custom" in install


def test_the_gtk_download_is_checked_before_it_is_used():
    text = (ROOT / "scripts" / "gtk-portable.ps1").read_text(encoding="utf-8")
    assert "github.com/wingtk/gvsbuild/releases/download/$resolved/$asset" in text
    assert "Get-FileHash" in text and "does not match the expected SHA256" in text
    assert "digest" in text and "gvsbuild-release.txt" in text
