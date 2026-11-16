# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# check-installed.ps1 - checks an installation made by istinbat-<version>-windows-setup.exe, for the manual CI job
# "windows-installer-run" and for a trial installation in a virtual machine.

<#
.SYNOPSIS
    Checks that an installation made by the Istinbat installer looks the way a user's machine should.
.DESCRIPTION
    Stops with an error at the first thing that is wrong. It checks that

      * the GTK runtime is the one the installer carried, and that no second copy was downloaded;
      * the Python environment exists and its libraries came from the wheelhouse inside the installer (nothing
        downloaded, no compiler);
      * GTK and libadwaita load from that folder without being told where it is;
      * PyTorch, chromadb, sentence-transformers, onnxruntime and llama-cpp-python import, with and without a
        console;
      * the application stays up for a few seconds, the way the Start menu entry starts it.
.PARAMETER App
    The installation folder. The default is where the installer puts it for the current user.
.PARAMETER SecondsToRun
    How long the application has to stay up.
.PARAMETER ExpectBundledPython
    Also check that Python itself came from the python.org installer inside the installer. Use it where no Python
    is installed yet.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\check-installed.ps1 -ExpectBundledPython
#>
param(
    [string]$App = (Join-Path $env:LOCALAPPDATA 'Programs\Istinbat'),
    [int]$SecondsToRun = 15,
    [switch]$ExpectBundledPython
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Ok([string]$Text) { Write-Host "OK  $Text" -ForegroundColor Green }

# 1. The runtime the installer carried is beside the application.
$gtk = Join-Path $App 'gtk'
$neededInGtk = 'bin',
               'lib\girepository-1.0\Gtk-4.0.typelib',
               'lib\girepository-1.0\Adw-1.typelib',
               'wheels',
               'gvsbuild-release.txt'
foreach ($needed in $neededInGtk) {
    if (-not (Test-Path (Join-Path $gtk $needed))) { throw "The installer did not put $needed in $gtk." }
}
Get-Content (Join-Path $gtk 'gvsbuild-release.txt') | ForEach-Object { Write-Host "    $_" }
Ok "GTK is in $gtk"

# 2. Nothing was downloaded to the place where the install script puts a runtime of its own.
$downloaded = Join-Path $env:LOCALAPPDATA 'istinbat\gtk'
if (Test-Path $downloaded) { throw "GTK was downloaded into $downloaded although the installer carries it." }
Ok 'no second copy of GTK was downloaded'

# 3. The install script ran to the end.
$python = Join-Path $App '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "The Python environment was not created in $App\.venv: the install script did not finish."
}
Ok 'the Python environment exists'

# 3b. What the install script did about Python and its libraries, from the log it keeps. The installer carries the
# libraries (a wheelhouse), so none may have been downloaded or compiled, and Python itself must not have needed winget.
$wheelhouse = Join-Path $App 'wheelhouse'
foreach ($library in 'llama_cpp_python', 'torch', 'chromadb') {
    if (-not @(Get-ChildItem $wheelhouse -Filter "$library-*.whl" -ErrorAction SilentlyContinue)) {
        throw "The installer did not put the Python libraries (a wheelhouse with $library) in $wheelhouse."
    }
}
Ok "the Python libraries are in $wheelhouse"
$installLog = Join-Path $env:LOCALAPPDATA 'istinbat\install.log'
if (-not (Test-Path $installLog)) { throw "The install script left no log at $installLog." }
$logText = Get-Content $installLog -Raw
if ($logText -notmatch 'Python libraries installed from the wheelhouse') {
    throw "The libraries were not installed from the wheelhouse; see $installLog."
}
foreach ($forbidden in 'downloading them instead', 'building it from source', 'Installing Python \S+ with winget') {
    if ($logText -match $forbidden) {
        throw ("The installation used the internet or a compiler where it should not have ('$forbidden'); " +
               "see $installLog.")
    }
}
Ok 'the libraries were installed from the wheelhouse, with nothing downloaded or compiled'
if ($ExpectBundledPython) {
    if ($logText -notmatch 'installer that came with Istinbat') {
        throw "Python was not installed from the installer that came with Istinbat; see $installLog."
    }
    $venvHome = Get-Content (Join-Path $App '.venv\pyvenv.cfg') |
        Where-Object { $_ -match '^home\s*=' } |
        Select-Object -First 1
    if (-not $venvHome -or $venvHome -notmatch 'Programs\\Python\\Python\d+') {
        throw "The environment was not made from the Python that the installer installed ($venvHome)."
    }
    Ok "Python came from the installer inside Istinbat ($($venvHome.Trim()))"
}

# 4. GTK loads from that folder, with nothing telling the application where it is.
Remove-Item Env:ISTINBAT_GTK_DIR -ErrorAction SilentlyContinue
$probe = Join-Path ([IO.Path]::GetTempPath()) 'istinbat-check-installed.py'
Set-Content -LiteralPath $probe -Encoding UTF8 -Value @'
import sys
from pathlib import Path

import istinbat.gui  # prepares the runtime before GTK is imported
from istinbat import winsupport
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

found = winsupport.find_gtk_runtime()
print("runtime found:", found)
print(
    "GTK %d.%d, libadwaita %d.%d"
    % (Gtk.get_major_version(), Gtk.get_minor_version(), Adw.get_major_version(), Adw.get_minor_version())
)
beside = Path(sys.prefix).parent / "gtk"
assert found is not None and found.resolve() == beside.resolve(), (
    f"expected the runtime beside the application: {beside}"
)
'@
& $python $probe
if ($LASTEXITCODE -ne 0) { throw "GTK did not load from the installer's folder (exit code $LASTEXITCODE)." }
Ok 'GTK and libadwaita load from the installer''s folder'

# 4b. The libraries that need the Visual C++ runtime and other native DLLs load in the installed environment, from
# a console program (python.exe) and from one that has no console, as the Start menu entry runs it (pythonw.exe, where
# a program started without a window of its own behaves differently). Nothing is loaded from the internet.
$libraryProbeSource = @'
import sys

import istinbat.gui  # Prepares the runtime (the bundled Visual C++ DLLs) first, as the program does.
import chromadb
import llama_cpp
import numpy
import onnxruntime
import sentence_transformers
import torch

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(
        "torch %s, chromadb %s, llama-cpp-python %s"
        % (torch.__version__, chromadb.__version__, llama_cpp.__version__)
    )
'@

# Runs the probe with one interpreter of the installed environment and returns what it wrote.
function Get-LibraryAnswer([string]$Interpreter, [string]$ProbeScript) {
    $answerFile = Join-Path ([IO.Path]::GetTempPath()) "istinbat-libraries-$Interpreter.txt"
    Remove-Item -LiteralPath $answerFile -ErrorAction SilentlyContinue
    $arguments = "`"$ProbeScript`"", "`"$answerFile`""
    Start-Process -FilePath (Join-Path $App ".venv\Scripts\$Interpreter") -ArgumentList $arguments `
                  -WorkingDirectory $App -WindowStyle Hidden
    # pythonw.exe hands over to the real interpreter and may end before it does: wait for the answer itself.
    $deadline = (Get-Date).AddSeconds(180)
    while (-not (Test-Path -LiteralPath $answerFile) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $answerFile)) {
        throw "$Interpreter could not import the libraries within three minutes."
    }
    Start-Sleep -Milliseconds 300
    return (Get-Content -LiteralPath $answerFile -Raw).Trim()
}

$libraryProbe = Join-Path ([IO.Path]::GetTempPath()) 'istinbat-check-libraries.py'
Set-Content -LiteralPath $libraryProbe -Encoding UTF8 -Value $libraryProbeSource
foreach ($interpreter in 'python.exe', 'pythonw.exe') {
    Write-Host "    ${interpreter}: $(Get-LibraryAnswer $interpreter $libraryProbe)"
}
Ok 'PyTorch, chromadb, sentence-transformers, onnxruntime and llama-cpp-python load (with and without a console)'

# 5. The application starts and keeps running.
$pythonw = Join-Path $App '.venv\Scripts\pythonw.exe'
$process = Start-Process -FilePath $pythonw -ArgumentList '-m', 'istinbat' -WorkingDirectory $App -PassThru
Start-Sleep -Seconds $SecondsToRun
$exited = $process.HasExited
# pythonw starts the real interpreter as a child, so the whole tree has to be stopped. taskkill fails when part of
# that tree is already gone, and a script that ends right after it would exit with taskkill's code: so it is run by
# cmd and its code forgotten.
if (-not $exited) { cmd /c "taskkill /PID $($process.Id) /T /F >nul 2>&1"; $global:LASTEXITCODE = 0 }
$log = Join-Path $env:LOCALAPPDATA 'istinbat\istinbat.log'
if (Test-Path $log) { Write-Host '--- istinbat.log'; Get-Content $log }
if ($exited) { throw "The application exited early with code $($process.ExitCode)." }
Ok "the application was still running after $SecondsToRun seconds"
