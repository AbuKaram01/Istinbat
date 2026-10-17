# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Windows start-up support. Windows behaviour is simulated so these run on every system."""

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

from istinbat import winsupport

ARABIC = "اكتملت الإجابة: «ما هو الحاسوب؟»"


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(winsupport, "is_windows", lambda: True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv(winsupport.GTK_DIR_ENV, raising=False)
    return tmp_path


def make_runtime(root: Path, schemas: bool = False) -> Path:
    (root / "bin").mkdir(parents=True)
    (root / "lib" / "girepository-1.0").mkdir(parents=True)
    (root / "share").mkdir()
    if schemas:
        (root / "share" / "glib-2.0" / "schemas").mkdir(parents=True)
        (root / "share" / "glib-2.0" / "schemas" / "gschemas.compiled").write_bytes(b"x")
    return root


# -- Finding the runtime ---------------------------------------------------------------------------

def test_an_explicit_folder_is_tried_first(monkeypatch, tmp_path):
    monkeypatch.setenv(winsupport.GTK_DIR_ENV, str(tmp_path / "mine"))
    assert winsupport.gtk_candidates()[0] == tmp_path / "mine"


def test_a_folder_is_a_runtime_only_with_binaries_and_typelibs(tmp_path):
    (tmp_path / "bin").mkdir()
    assert not winsupport.is_gtk_runtime(tmp_path)
    (tmp_path / "lib" / "girepository-1.0").mkdir(parents=True)
    assert winsupport.is_gtk_runtime(tmp_path)


def test_the_first_valid_candidate_is_used(monkeypatch, windows):
    runtime = make_runtime(windows / "gtk")
    monkeypatch.setenv(winsupport.GTK_DIR_ENV, str(windows / "missing"))
    monkeypatch.setattr(winsupport, "gtk_candidates", lambda: [windows / "missing", runtime])
    assert winsupport.find_gtk_runtime() == runtime


def test_the_installer_location_is_among_the_candidates(windows):
    assert windows / "data" / "istinbat" / "gtk" in winsupport.gtk_candidates()


# -- Configuring the process -----------------------------------------------------------------------

def test_configuring_makes_dlls_typelibs_and_data_visible(monkeypatch, tmp_path):
    runtime = make_runtime(tmp_path / "gtk", schemas=True)
    added = []
    monkeypatch.setattr(os, "add_dll_directory", added.append, raising=False)
    for name in ("PATH", "GI_TYPELIB_PATH", "XDG_DATA_DIRS", "GSETTINGS_SCHEMA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", "other")

    winsupport.configure_gtk(runtime)

    assert added == [str(runtime / "bin")]
    assert os.environ["PATH"].split(os.pathsep) == [str(runtime / "bin"), "other"]
    assert os.environ["GI_TYPELIB_PATH"] == str(runtime / "lib" / "girepository-1.0")
    assert os.environ["XDG_DATA_DIRS"] == str(runtime / "share")
    assert os.environ["GSETTINGS_SCHEMA_DIR"] == str(runtime / "share" / "glib-2.0" / "schemas")


def test_configuring_twice_does_not_repeat_entries(monkeypatch, tmp_path):
    runtime = make_runtime(tmp_path / "gtk")
    monkeypatch.setattr(os, "add_dll_directory", lambda path: None, raising=False)
    monkeypatch.setenv("PATH", "other")
    monkeypatch.delenv("XDG_DATA_DIRS", raising=False)
    monkeypatch.delenv("GSETTINGS_SCHEMA_DIR", raising=False)
    winsupport.configure_gtk(runtime)
    winsupport.configure_gtk(runtime)
    assert os.environ["PATH"].split(os.pathsep).count(str(runtime / "bin")) == 1
    assert "GSETTINGS_SCHEMA_DIR" not in os.environ      # No compiled schemas in this runtime.


def test_prepare_does_nothing_outside_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(winsupport, "is_windows", lambda: False)
    monkeypatch.setattr(winsupport, "find_gtk_runtime", lambda: pytest.fail("must not search"))
    before = dict(os.environ)
    winsupport.prepare_runtime()
    assert dict(os.environ) == before


def test_prepare_on_windows_sets_up_streams_runtime_and_identity(monkeypatch, windows):
    runtime = make_runtime(windows / "gtk")
    steps = []
    monkeypatch.setattr(winsupport, "ensure_standard_streams", lambda: steps.append("streams"))
    monkeypatch.setattr(winsupport, "find_gtk_runtime", lambda: runtime)
    monkeypatch.setattr(winsupport, "configure_gtk", lambda gtk: steps.append(("gtk", gtk)))
    monkeypatch.setattr(winsupport, "set_app_user_model_id", lambda: steps.append("identity"))
    winsupport.prepare_runtime()
    assert steps == ["streams", ("gtk", runtime), "identity"]


def test_prepare_still_works_when_no_runtime_is_found(monkeypatch, windows):
    monkeypatch.setattr(winsupport, "ensure_standard_streams", lambda: None)
    monkeypatch.setattr(winsupport, "find_gtk_runtime", lambda: None)
    monkeypatch.setattr(winsupport, "configure_gtk", lambda gtk: pytest.fail("no runtime to configure"))
    monkeypatch.setattr(winsupport, "set_app_user_model_id", lambda: None)
    winsupport.prepare_runtime()


def test_a_process_without_a_console_gets_streams_and_a_log_file(monkeypatch, windows):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    winsupport.ensure_standard_streams()
    try:
        print("hello")                                    # Would raise without a stdout.
        print(ARABIC, file=sys.stderr)
        sys.stderr.flush()
        log = windows / "data" / "istinbat" / "istinbat.log"
        assert ARABIC in log.read_text(encoding="utf-8")
    finally:
        sys.stdout.close()
        sys.stderr.close()


def test_existing_streams_are_left_alone(monkeypatch, windows, capsys):
    before = (sys.stdout, sys.stderr)
    winsupport.ensure_standard_streams()
    assert (sys.stdout, sys.stderr) == before


# -- Missing toolkit -------------------------------------------------------------------------------

def test_a_missing_toolkit_is_reported_with_the_way_out(monkeypatch, capsys):
    monkeypatch.setattr(winsupport, "is_windows", lambda: False)
    winsupport.report_missing_toolkit(ImportError("DLL load failed"))
    error = capsys.readouterr().err
    assert "DLL load failed" in error and "install-windows.ps1" in error and winsupport.GTK_DIR_ENV in error


# -- Notifications ---------------------------------------------------------------------------------

def decode(command):
    return base64.b64decode(command[command.index("-EncodedCommand") + 1]).decode("utf-16-le")


def test_the_toast_script_escapes_xml_and_powershell_quotes():
    script = winsupport.toast_script("It's <ready> & done", "a 'quoted' <b>", app_id="x.y")
    assert "It''s &lt;ready&gt; &amp; done" in script
    assert "a ''quoted'' &lt;b&gt;" in script
    assert "CreateToastNotifier('x.y')" in script


def test_arabic_text_survives_the_encoded_command():
    script = winsupport.toast_script("استنباط", ARABIC)
    command = winsupport.powershell_command(script)
    assert command[0] == "powershell.exe" and "-NonInteractive" in command
    assert decode(command) == script and ARABIC in decode(command)


def test_no_toast_is_attempted_outside_windows(monkeypatch):
    monkeypatch.setattr(winsupport, "is_windows", lambda: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must not start a process"))
    assert winsupport.send_toast("t", "b") is False


def test_a_toast_registers_the_identity_and_starts_powershell(monkeypatch, windows):
    started, registered = [], []
    monkeypatch.setattr(winsupport, "register_toast_app", lambda: registered.append(True))
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kwargs: started.append((command, kwargs)))
    assert winsupport.send_toast("استنباط", ARABIC) is True
    assert registered == [True]
    command, kwargs = started[0]
    assert ARABIC in decode(command) and kwargs["creationflags"] == winsupport._CREATE_NO_WINDOW


def test_a_toast_that_cannot_be_shown_reports_failure_instead_of_raising(monkeypatch, windows):
    monkeypatch.setattr(winsupport, "register_toast_app", lambda: None)

    def fail(*args, **kwargs):
        raise OSError("no powershell")

    monkeypatch.setattr(subprocess, "Popen", fail)
    assert winsupport.send_toast("t", "b") is False


# -- Icon ------------------------------------------------------------------------------------------

def test_the_windows_icon_ships_with_the_sources():
    icon = winsupport.icon_file()
    assert icon is not None and icon.name == "istinbat.ico"
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"      # An ICO header with at least one image.


def test_setting_the_icon_is_a_no_op_outside_windows(monkeypatch):
    monkeypatch.setattr(winsupport, "is_windows", lambda: False)
    winsupport.apply_icon_to_own_windows()
