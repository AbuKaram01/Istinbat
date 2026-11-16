# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# install-windows.ps1 - one-command installer for Istinbat on Windows 10/11 (64-bit), run from a checkout as your
# normal user. Everything goes into your own profile: no administrator rights are needed.

<#
.SYNOPSIS
    Installs Istinbat and everything it needs on Windows 10/11 (64-bit).
.DESCRIPTION
    Sets up, in this order:
      1. The GTK 4 + libadwaita runtime: the copy inside the installer, else the prebuilt gvsbuild release, unless
         -GtkDir points at your own.
      2. Python itself when it is missing: the python.org installer inside the Istinbat installer, else winget.
      3. A Python virtual environment in .venv that matches the PyGObject wheel shipped with that runtime.
      4. PyTorch, llama-cpp-python, chromadb and the other Python dependencies: the wheels inside the Istinbat
         installer, else downloaded.
      5. A Start menu entry.
.PARAMETER Cuda
    Compile llama.cpp (the language model) with CUDA. Needs the CUDA Toolkit and the Visual Studio Build Tools.
    PyTorch (the embedding and reranking models) stays the CPU build unless -TorchIndexUrl names a CUDA index.
.PARAMETER TorchIndexUrl
    A wheel index for PyTorch, e.g. https://download.pytorch.org/whl/cu128 for a CUDA build. By default PyTorch comes
    from the wheels inside the installer or from PyPI, which on Windows is the CPU build.
.PARAMETER LlamaIndexUrl
    A wheel index for llama-cpp-python, e.g. https://abetlen.github.io/llama-cpp-python/whl/cu124
.PARAMETER BuildLlamaFromSource
    Skip prebuilt wheels and compile llama-cpp-python from source (newest llama.cpp; slow; needs the Visual Studio
    Build Tools and CMake).
.PARAMETER GtkDir
    Use an existing GTK 4 runtime folder (one that contains bin, lib and share) instead of the copy inside the
    installer or a download.
.PARAMETER GtkTag
    The gvsbuild release to download the GTK runtime from (a tag such as 2026.8.0, or "latest"). By default the
    release this project is tested with (see scripts\gtk-portable.ps1): the newest one may carry wheels for a Python
    version that the other libraries do not support yet.
.PARAMETER PythonVersion
    Force a Python version, e.g. 3.13. By default it follows the PyGObject wheel of the GTK runtime.
.PARAMETER SkipHeavy
    Install the dependencies but not PyTorch, chromadb, sentence-transformers and llama-cpp-python (used by the
    automated tests).
.PARAMETER NoShortcut
    Do not create the Start menu entry.
.PARAMETER LogFile
    Also write everything this script prints to this file (the installer does, so that a failure can be looked at).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -Cuda
#>
[CmdletBinding()]
param(
    [switch]$Cuda,
    [string]$LlamaIndexUrl = "",
    [string]$TorchIndexUrl = "",
    [switch]$BuildLlamaFromSource,
    [string]$GtkDir = "",
    [string]$GtkTag = "",
    [string]$PythonVersion = "",
    [switch]$SkipHeavy,
    [switch]$NoShortcut,
    [string]$LogFile = ""
)

Set-StrictMode -Version 2.0

# This script is for Windows only; say so clearly instead of failing on a missing %LOCALAPPDATA%.
if ($env:OS -ne 'Windows_NT') {
    Write-Host ('ERR This script is for Windows. On Linux use scripts/install-debian.sh or ' +
                'scripts/install-arch.sh.') -ForegroundColor Red
    exit 1
}
$ErrorActionPreference = 'Stop'
# Makes Invoke-WebRequest much faster in Windows PowerShell 5.1.
$ProgressPreference = 'SilentlyContinue'
if ($LogFile) {
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogFile) | Out-Null
        Start-Transcript -Path $LogFile -Force | Out-Null
    } catch {
        Write-Host "!!  The log file $LogFile could not be opened: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$AppId         = 'io.github.AbuKaram01.Istinbat'
$MinPython     = [version]'3.10'
$ProjectRoot   = Split-Path -Parent $PSScriptRoot
$DataRoot      = Join-Path $env:LOCALAPPDATA 'istinbat'
$DefaultGtk    = Join-Path $DataRoot 'gtk'
$Venv          = Join-Path $ProjectRoot '.venv'
$CpuLlamaIndex = 'https://abetlen.github.io/llama-cpp-python/whl/cpu'

function Info($Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Ok($Text)   { Write-Host "OK  $Text" -ForegroundColor Green }
function Warn($Text) { Write-Host "!!  $Text" -ForegroundColor Yellow }
function Fail($Text) { Write-Host "ERR $Text" -ForegroundColor Red; exit 1 }

# Runs a native command and returns its output; $null when it failed. Never throws.
function Run-Quietly([string]$Exe, [string[]]$Arguments) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Exe @Arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return $output
    } catch { return $null } finally { $ErrorActionPreference = $saved }
}

if (-not [Environment]::Is64BitOperatingSystem) { Fail 'Istinbat needs 64-bit Windows.' }
if (-not (Test-Path (Join-Path $ProjectRoot 'pyproject.toml'))) {
    Fail "pyproject.toml not found in $ProjectRoot. Run this script from a checkout."
}

# The helper scripts are dot-sourced, so that their functions are available below:
#   gtk-portable.ps1         Test-GtkRuntime, Resolve-GtkChoice, Get-PortableGtk
#   python-bundle.ps1        Find-PythonInstaller, Install-PythonFromInstaller, Test-Wheelhouse
. (Join-Path $PSScriptRoot 'gtk-portable.ps1')
. (Join-Path $PSScriptRoot 'python-bundle.ps1')

# --- 1. The GTK 4 + libadwaita runtime -------------------------------------------------------------------------

# -GtkDir wins; then the runtime inside the installer (<application folder>\gtk, which the application finds by itself,
# so nothing has to be saved for it); then the default folder, where one is downloaded when it is missing.
$gtkExplicit = [bool]$GtkDir
$gtkChoice   = Resolve-GtkChoice -Explicit $GtkDir -ProjectRoot $ProjectRoot -DefaultDir $DefaultGtk
$GtkDir      = $gtkChoice.Dir
$CustomGtk   = $gtkChoice.Custom
if (-not $gtkExplicit -and -not $gtkChoice.Bundled -and (Test-Path (Join-Path $ProjectRoot 'gtk'))) {
    Warn "The GTK runtime inside the installer ($(Join-Path $ProjectRoot 'gtk')) is incomplete; using another one."
}

if (Test-GtkRuntime $GtkDir) {
    if ($gtkChoice.Bundled) { Ok "GTK 4 and libadwaita come with the installer ($GtkDir)" }
    else { Ok "GTK 4 and libadwaita found in $GtkDir" }
} else {
    if ($CustomGtk) {
        Fail ("$GtkDir is not a complete GTK 4 runtime " +
              '(it needs bin, the Gtk-4.0 and Adw-1 typelibs, and adwaita-1-*.dll).')
    }
    Warn 'The prebuilt gvsbuild binaries are provided as-is and are not security-updated by their authors;'
    Warn 'for a machine you care about, build your own (see the README) and pass -GtkDir.'
    if (-not (Get-PortableGtk -Target $GtkDir -Tag $GtkTag)) {
        Fail ("Could not get the gvsbuild GTK 4 runtime. Download GTK4_Gvsbuild_<release>_x64.zip from " +
              "https://github.com/wingtk/gvsbuild/releases yourself, unzip it, and pass the folder as -GtkDir.")
    }
    if (-not (Test-GtkRuntime $GtkDir)) {
        Fail ("The downloaded GTK runtime does not contain libadwaita. Build it yourself with:`n" +
              ("    gvsbuild build --enable-gi --py-wheel gtk4 libadwaita librsvg adwaita-icon-theme " +
               "pygobject pycairo`n") +
              "and pass the output folder (C:\gtk-build\gtk\x64\release) as -GtkDir.")
    }
    Ok "GTK 4 and libadwaita installed in $GtkDir"
}

# --- 2. Python: the version has to match the PyGObject wheel of the runtime -----------------------------------

# The Python version ("3.14") a PyGObject or pycairo wheel is for, or $null.
function Get-WheelVersion([string]$FileName) {
    if ($FileName -match '-cp(\d)(\d+)-cp\d+-win_amd64\.whl$') {
        return [version]("{0}.{1}" -f $Matches[1], $Matches[2])
    }
    return $null
}

# The python.exe of version <x.y> that is on this machine: in the usual folders, else the py launcher's, else the one on
# PATH. $null when there is none.

function Find-Python([string]$Version) {
    $tag = $Version.Replace('.', '')
    $direct = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python$tag\python.exe"),
        "C:\Program Files\Python$tag\python.exe"
    )
    foreach ($path in $direct) { if (Test-Path $path) { return $path } }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $found = Run-Quietly 'py' @("-$Version-64", '-c', 'import sys; print(sys.executable)')
        if ($found) { return ([string]$found).Trim() }
    }
    # A Python that the launcher does not know (conda, scoop, a CI image). The Microsoft Store stub is not one.
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath -and $onPath.Source -notlike '*\WindowsApps\*') {
        $reported = Run-Quietly $onPath.Source @('-c', $script:PythonMinorSnippet)
        if ($reported -and ([string]$reported).Trim() -eq $Version) { return $onPath.Source }
    }
    return $null
}

# The python.org installer that came inside the Istinbat installer (<application folder>\python) comes first: it needs
# no internet and no winget. Without it, or when it does not finish, winget installs Python.
function Install-Python([string]$Version) {
    $bundled = Find-PythonInstaller (Join-Path $ProjectRoot 'python') $Version
    if ($bundled) {
        Info "Installing Python $Version from the installer that came with Istinbat (nothing is downloaded)..."
        New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
        $pythonLog = Join-Path $DataRoot 'python-install.log'
        if (Install-PythonFromInstaller $bundled $pythonLog) { return }
        Warn "The Python installer that came with Istinbat did not finish (its log is $pythonLog)."
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail ("Python $Version is needed and winget is not available. Install Python $Version from " +
              "https://www.python.org/downloads/ and run this script again.")
    }
    Info "Installing Python $Version with winget..."
    & winget install --id "Python.Python.$Version" --exact --scope user --silent `
        --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Warn "winget reported exit code $LASTEXITCODE." }
}

$wheelDir = Join-Path $GtkDir 'wheels'
$gobjectWheels = @(Get-ChildItem $wheelDir -Filter 'pygobject*.whl' -ErrorAction SilentlyContinue)
$cairoWheels   = @(Get-ChildItem $wheelDir -Filter 'pycairo*.whl' -ErrorAction SilentlyContinue)
if ($gobjectWheels.Count -eq 0 -or $cairoWheels.Count -eq 0) {
    Fail ("No PyGObject/pycairo wheels in $wheelDir. " +
          "Build them with gvsbuild (--py-wheel) and copy them into that folder.")
}

$versions = @($gobjectWheels |
    ForEach-Object { Get-WheelVersion $_.Name } |
    Where-Object { $_ -and $_ -ge $MinPython } |
    Sort-Object -Descending -Unique)
if ($PythonVersion) { $versions = @($versions | Where-Object { "$($_.Major).$($_.Minor)" -eq $PythonVersion }) }
if ($versions.Count -eq 0) {
    $available = @($gobjectWheels |
        ForEach-Object { Get-WheelVersion $_.Name } |
        Where-Object { $_ } |
        Sort-Object -Unique |
        ForEach-Object { "$($_.Major).$($_.Minor)" })
    $wanted = if ($PythonVersion) { "Python $PythonVersion" }
    else { "Python $MinPython or newer, which Istinbat needs" }
    Fail ("The PyGObject wheels in $wheelDir are for Python $($available -join ', '), not for $wanted.`n" +
          "They come from a gvsbuild release; use one whose wheels are for the Python you want (-GtkTag), " +
          "or pass -GtkDir.")
}

$python = $null
$chosen = $null
foreach ($candidate in $versions) {
    $text = "$($candidate.Major).$($candidate.Minor)"
    $found = Find-Python $text
    if ($found) { $python = $found; $chosen = $text; break }
}
if (-not $python) {
    $chosen = "$($versions[0].Major).$($versions[0].Minor)"
    Install-Python $chosen
    $python = Find-Python $chosen
    if (-not $python) {
        Fail ("Python $chosen was installed but could not be found. " +
              "Open a new PowerShell window and run this script again.")
    }
}
Ok "Using Python $chosen ($python)"

# --- 3. The virtual environment --------------------------------------------------------------------------------

$venvPython  = Join-Path $Venv 'Scripts\python.exe'
$venvPythonW = Join-Path $Venv 'Scripts\pythonw.exe'
if (Test-Path $venvPython) {
    $existing = Run-Quietly $venvPython @('-c', $script:PythonMinorSnippet)
    if (-not $existing -or ([string]$existing).Trim() -ne $chosen) {
        Info 'The existing .venv was made with another Python version; recreating it...'
        Remove-Item $Venv -Recurse -Force
    }
}
if (-not (Test-Path $venvPython)) {
    Info 'Creating the virtual environment (.venv)...'
    & $python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create the virtual environment.' }
}

function Pip([string[]]$Arguments) {
    & $venvPython -m pip @Arguments
    if ($LASTEXITCODE -ne 0) { throw "pip $($Arguments -join ' ') failed (exit code $LASTEXITCODE)." }
}
function Try-Pip([string[]]$Arguments) {
    # What pip prints must not become part of the result.
    & $venvPython -m pip @Arguments | Out-Host
    return ($LASTEXITCODE -eq 0)
}

# The Python libraries inside the Istinbat installer, when they are for this Python: nothing is downloaded for them.
$wheelhouse = Join-Path $ProjectRoot 'wheelhouse'
$offline = Test-Wheelhouse $wheelhouse $chosen
if ($offline) { Ok "The Python libraries come with the installer ($wheelhouse)" }
elseif (Test-Path $wheelhouse) {
    $why = Get-WheelhouseProblem $wheelhouse $chosen
    Warn "The libraries inside the installer ($wheelhouse) cannot be used ($why); downloading them instead."
}

if (-not $offline) { Pip @('install', '--upgrade', 'pip', '--quiet') }

Info 'Installing PyGObject and pycairo (the gvsbuild wheels that match the GTK runtime)...'
$wheelTag = "-cp$($chosen.Replace('.', ''))-"
$gobject = $gobjectWheels | Where-Object { $_.Name -like "*$wheelTag*" } | Select-Object -First 1
$cairo   = $cairoWheels   | Where-Object { $_.Name -like "*$wheelTag*" } | Select-Object -First 1
if (-not $gobject -or -not $cairo) { Fail "The runtime has no PyGObject and pycairo wheels for Python $chosen." }
Pip @('install', '--force-reinstall', '--quiet', $cairo.FullName, $gobject.FullName)

# --- 4. PyTorch and llama.cpp ----------------------------------------------------------------------

function Test-BuildTools {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { return $false }
    $found = Run-Quietly $vswhere @('-latest', '-products', '*', '-requires',
                                    'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                                    '-property', 'installationPath')
    return [bool]$found
}

function Install-LlamaFromSource {
    if (-not (Test-BuildTools)) {
        Fail ("Compiling llama.cpp needs the Visual Studio Build Tools (C++ workload) and CMake. Install them with:`n" +
              "    winget install Microsoft.VisualStudio.2022.BuildTools --override " +
              "`"--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended`"`n" +
              "    winget install Kitware.CMake`n" +
              "then open a new PowerShell window and run this script again.")
    }
    if ($Cuda) {
        if (-not (Get-Command nvcc -ErrorAction SilentlyContinue)) {
            Fail 'CUDA build requested but nvcc was not found. Install the NVIDIA CUDA Toolkit first.'
        }
        $env:CMAKE_ARGS = '-DGGML_CUDA=on'
    }
    Info 'Compiling llama-cpp-python (this takes several minutes)...'
    Pip @('install', 'llama-cpp-python', '--no-cache-dir', '--no-binary', 'llama-cpp-python')
}

if ($SkipHeavy) {
    Warn 'Skipping PyTorch, chromadb and llama-cpp-python (-SkipHeavy).'
    Warn 'The application cannot answer questions without them.'
} else {
    if ($TorchIndexUrl) {
        Info "Installing PyTorch from $TorchIndexUrl..."
        Pip @('install', 'torch', '--index-url', $TorchIndexUrl, '--quiet')
    } elseif ($Cuda) {
        Warn 'PyTorch stays the CPU build: pass -TorchIndexUrl https://download.pytorch.org/whl/cu128 for a CUDA one.'
    }

    if ($BuildLlamaFromSource -or ($Cuda -and -not $LlamaIndexUrl)) {
        Install-LlamaFromSource
    } elseif ($offline -and -not $LlamaIndexUrl -and
              (Try-Pip @('install', '--no-index', '--find-links', $wheelhouse, '--only-binary', 'llama-cpp-python',
                         'llama-cpp-python', '--quiet'))) {
        Ok 'llama-cpp-python installed from the wheelhouse (no internet needed).'
    } else {
        $index = if ($LlamaIndexUrl) { $LlamaIndexUrl } else { $CpuLlamaIndex }
        Info "Installing llama-cpp-python (prebuilt wheel from $index)..."
        $prebuilt = @('install', 'llama-cpp-python', '--only-binary', 'llama-cpp-python',
                      '--extra-index-url', $index, '--quiet')
        if (-not (Try-Pip $prebuilt)) {
            Warn ("No prebuilt llama-cpp-python wheel for Python $chosen was found at $index; " +
                  "building it from source instead.")
            Install-LlamaFromSource
        }
    }
}

# --- 5. Istinbat itself -----------------------------------------------------------------------------------------

Info 'Installing Istinbat and its Python dependencies...'
if ($SkipHeavy) {
    Pip @('install', '--quiet', 'numpy', 'rank-bm25', 'markdown-it-py', 'pytest')
    Pip @('install', '--quiet', '--no-deps', '-e', $ProjectRoot)
} else {
    $installed = $false
    if ($offline) {
        $installed = Try-Pip @('install', '--quiet', '--no-index', '--find-links', $wheelhouse, '-e', $ProjectRoot)
        if ($installed) { Ok 'Python libraries installed from the wheelhouse (no internet needed).' }
        else { Warn 'The libraries could not be installed from the wheelhouse; downloading them instead.' }
    }
    if (-not $installed) { Pip @('install', '--quiet', '-e', $ProjectRoot) }
}
Ok 'Python dependencies installed.'

# --- 6. Check that the toolkit really loads --------------------------------------------------------------------

Info 'Checking that GTK 4 and libadwaita load...'
$env:ISTINBAT_GTK_DIR = $GtkDir
$probe = "import istinbat.gui, gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); " +
         "from gi.repository import Gtk, Adw; " +
         "print('GTK %d.%d, libadwaita %d.%d' % (Gtk.get_major_version(), Gtk.get_minor_version(), " +
         "Adw.get_major_version(), Adw.get_minor_version()))"
# Windows PowerShell 5.1 turns native stderr into errors under 'Stop'.
$ErrorActionPreference = 'Continue'
$probeOutput = & $venvPython -c $probe 2>&1
$probeExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($probeExit -ne 0) { Fail "GTK could not be loaded:`n$($probeOutput -join "`n")" }
Ok ([string]($probeOutput | Select-Object -Last 1))

# A runtime in a non-default folder has to be told to the application.
if ($CustomGtk) {
    [Environment]::SetEnvironmentVariable('ISTINBAT_GTK_DIR', $GtkDir, 'User')
    Ok 'Saved ISTINBAT_GTK_DIR for your user account.'
}

# --- 7. Start menu entry ---------------------------------------------------------------------------------------

if (-not $NoShortcut) {
    Info 'Creating the Start menu entry...'
    $programs = [Environment]::GetFolderPath('Programs')
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $programs 'Istinbat.lnk'))
    $shortcut.TargetPath       = $venvPythonW
    $shortcut.Arguments        = '-m istinbat'
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.Description      = 'Ask questions about your Arabic and English books, fully offline'
    $icon = Join-Path $ProjectRoot 'data\windows\istinbat.ico'
    if (Test-Path $icon) { $shortcut.IconLocation = "$icon,0" }
    $shortcut.Save()
    Ok 'Start menu entry created: Istinbat.'
}

Write-Host ''
Ok 'Istinbat is installed.'
Write-Host ''
Write-Host '  Start it from the Start menu (Istinbat), or run:'
Write-Host "    $venvPythonW -m istinbat"
Write-Host '  If it does not open, run it with python.exe instead of pythonw.exe to see the error:'
Write-Host "    $venvPython -m istinbat"
Write-Host ''
Write-Host 'First launch: the welcome guide helps you download the language, embedding and reranking models. Then set'
Write-Host 'your books folder and index your .txt books.'
