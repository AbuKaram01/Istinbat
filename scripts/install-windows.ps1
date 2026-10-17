# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# One-command installer for Istinbat on Windows 10/11 (64-bit). Run from a checkout, as your normal user:
#
#     powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 [-Cuda]
#
# It sets up, all inside your own profile (no administrator rights needed):
#   * the GTK 4 + libadwaita runtime (the prebuilt gvsbuild release, unless you point -GtkDir at your own),
#   * a Python virtual environment in .venv that matches the PyGObject wheel shipped with that runtime,
#   * PyTorch (CPU build by default), llama-cpp-python and the other Python dependencies,
#   * a Start menu entry.

[CmdletBinding()]
param(
    # Use the regular (CUDA) PyTorch build and compile llama.cpp with CUDA. Needs the CUDA Toolkit and
    # the Visual Studio Build Tools.
    [switch]$Cuda,
    # A wheel index for llama-cpp-python, e.g. https://abetlen.github.io/llama-cpp-python/whl/cu124
    [string]$LlamaIndexUrl = "",
    # Skip prebuilt wheels and compile llama-cpp-python from source (newest llama.cpp; slow; needs the
    # Visual Studio Build Tools and CMake).
    [switch]$BuildLlamaFromSource,
    # Use an existing GTK 4 runtime folder (one that contains bin, lib and share) instead of downloading one.
    [string]$GtkDir = "",
    # Force a Python version, e.g. 3.13. By default it follows the PyGObject wheel of the GTK runtime.
    [string]$PythonVersion = "",
    # Install the dependencies but not PyTorch and llama-cpp-python (used by the automated tests).
    [switch]$SkipHeavy,
    [switch]$NoShortcut
)

Set-StrictMode -Version 2.0

# This script is for Windows only; say so clearly instead of failing on a missing %LOCALAPPDATA%.
if ($env:OS -ne 'Windows_NT') {
    Write-Host 'ERR This script is for Windows. On Linux use scripts/install-debian.sh or scripts/install-arch.sh.' -ForegroundColor Red
    exit 1
}
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'     # Makes Invoke-WebRequest much faster in Windows PowerShell 5.1.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$AppId        = 'io.github.AbuKaram01.Istinbat'
$MinPython    = [version]'3.10'
$ProjectRoot  = Split-Path -Parent $PSScriptRoot
$DataRoot     = Join-Path $env:LOCALAPPDATA 'istinbat'
$DefaultGtk   = Join-Path $DataRoot 'gtk'
$Venv         = Join-Path $ProjectRoot '.venv'
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
if (-not (Test-Path (Join-Path $ProjectRoot 'pyproject.toml'))) { Fail "pyproject.toml not found in $ProjectRoot. Run this script from a checkout." }

# -- 1. The GTK 4 + libadwaita runtime ---------------------------------------------------------------

function Test-GtkRuntime([string]$Folder) {
    if (-not $Folder) { return $false }
    return (Test-Path (Join-Path $Folder 'bin')) -and
           (Test-Path (Join-Path $Folder 'lib\girepository-1.0\Gtk-4.0.typelib')) -and
           (Test-Path (Join-Path $Folder 'lib\girepository-1.0\Adw-1.typelib')) -and
           [bool](Get-ChildItem (Join-Path $Folder 'bin') -Filter '*adwaita-1-*.dll' -ErrorAction SilentlyContinue)
}

# The download links of the newest gvsbuild release. The "latest" redirect is tried first because the GitHub API
# allows only 60 anonymous requests per hour per address, which a shared connection can exhaust.
function Get-GtkZipUrls {
    $urls = @()
    try {
        $request = [Net.HttpWebRequest]::Create('https://github.com/wingtk/gvsbuild/releases/latest')
        $request.Method = 'HEAD'
        $request.AllowAutoRedirect = $false
        $request.UserAgent = 'istinbat-installer'
        $response = $request.GetResponse()
        $location = [string]$response.Headers['Location']
        $response.Close()
        if ($location -match '/tag/([^/]+)$') {
            $tag = $Matches[1]
            $urls += "https://github.com/wingtk/gvsbuild/releases/download/$tag/GTK4_Gvsbuild_${tag}_x64.zip"
        }
    } catch { }
    try {
        $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/wingtk/gvsbuild/releases/latest' -Headers @{ 'User-Agent' = 'istinbat-installer' }
        $asset = $release.assets | Where-Object { $_.name -like 'GTK4_Gvsbuild_*_x64.zip' } | Select-Object -First 1
        if ($asset) { $urls += $asset.browser_download_url }
    } catch { }
    return @($urls | Select-Object -Unique)
}

function Install-GtkRuntime([string]$Target) {
    Info 'Looking up the latest gvsbuild GTK 4 release...'
    $zip = Join-Path $env:TEMP ('istinbat-gtk-' + [guid]::NewGuid().ToString('N') + '.zip')
    $downloaded = $false
    foreach ($url in (Get-GtkZipUrls)) {
        try {
            Info "Downloading $url ..."
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
            $downloaded = $true
            break
        } catch { Warn "Download failed: $($_.Exception.Message)" }
    }
    if (-not $downloaded) { Fail 'Could not download the gvsbuild GTK 4 zip. Download GTK4_Gvsbuild_*_x64.zip from https://github.com/wingtk/gvsbuild/releases yourself, unzip it, and pass the folder as -GtkDir.' }

    $unpacked = Join-Path $env:TEMP ('istinbat-gtk-' + [guid]::NewGuid().ToString('N'))
    Info 'Unpacking...'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($zip, $unpacked)
    Remove-Item $zip -Force

    # The archive may hold the runtime at its top level or inside one folder.
    $root = $unpacked
    if (-not (Test-Path (Join-Path $root 'bin'))) {
        $inner = Get-ChildItem $unpacked -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'bin') } | Select-Object -First 1
        if ($inner) { $root = $inner.FullName }
    }
    if (Test-Path $Target) { Remove-Item $Target -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
    Move-Item -LiteralPath $root -Destination $Target
    if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
}

$CustomGtk = $false
if ($GtkDir) {
    $GtkDir = (Resolve-Path $GtkDir).Path
    $CustomGtk = ($GtkDir -ne $DefaultGtk)
} else {
    $GtkDir = $DefaultGtk
}

if (Test-GtkRuntime $GtkDir) {
    Ok "GTK 4 and libadwaita found in $GtkDir"
} else {
    if ($CustomGtk) { Fail "$GtkDir is not a complete GTK 4 runtime (it needs bin, the Gtk-4.0 and Adw-1 typelibs, and adwaita-1-*.dll)." }
    Warn 'The prebuilt gvsbuild binaries are provided as-is and are not security-updated by their authors;'
    Warn 'for a machine you care about, build your own (see the README) and pass -GtkDir.'
    Install-GtkRuntime $GtkDir
    if (-not (Test-GtkRuntime $GtkDir)) {
        Fail ("The downloaded GTK runtime does not contain libadwaita. Build it yourself with:`n" +
              "    gvsbuild build --enable-gi --py-wheel gtk4 libadwaita librsvg adwaita-icon-theme pygobject pycairo`n" +
              "and pass the output folder (C:\gtk-build\gtk\x64\release) as -GtkDir.")
    }
    Ok "GTK 4 and libadwaita installed in $GtkDir"
}

# -- 2. Python: the version has to match the PyGObject wheel of the runtime ---------------------------

function Get-WheelVersion([string]$FileName) {
    if ($FileName -match '-cp(\d)(\d+)-cp\d+-win_amd64\.whl$') { return [version]("{0}.{1}" -f $Matches[1], $Matches[2]) }
    return $null
}

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
        $reported = Run-Quietly $onPath.Source @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')
        if ($reported -and ([string]$reported).Trim() -eq $Version) { return $onPath.Source }
    }
    return $null
}

function Install-Python([string]$Version) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "Python $Version is needed and winget is not available. Install Python $Version from https://www.python.org/downloads/ and run this script again."
    }
    Info "Installing Python $Version with winget..."
    & winget install --id "Python.Python.$Version" --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Warn "winget reported exit code $LASTEXITCODE." }
}

$wheelDir = Join-Path $GtkDir 'wheels'
$gobjectWheels = @(Get-ChildItem $wheelDir -Filter 'pygobject*.whl' -ErrorAction SilentlyContinue)
$cairoWheels   = @(Get-ChildItem $wheelDir -Filter 'pycairo*.whl' -ErrorAction SilentlyContinue)
if ($gobjectWheels.Count -eq 0 -or $cairoWheels.Count -eq 0) {
    Fail "No PyGObject/pycairo wheels in $wheelDir. Build them with gvsbuild (--py-wheel) and copy them into that folder."
}

$versions = @($gobjectWheels | ForEach-Object { Get-WheelVersion $_.Name } | Where-Object { $_ -and $_ -ge $MinPython } | Sort-Object -Descending -Unique)
if ($PythonVersion) { $versions = @($versions | Where-Object { "$($_.Major).$($_.Minor)" -eq $PythonVersion }) }
if ($versions.Count -eq 0) { Fail "The PyGObject wheels in $wheelDir do not match Python $PythonVersion (Istinbat needs Python $MinPython or newer)." }

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
    if (-not $python) { Fail "Python $chosen was installed but could not be found. Open a new PowerShell window and run this script again." }
}
Ok "Using Python $chosen ($python)"

# -- 3. The virtual environment ------------------------------------------------------------------------

$venvPython  = Join-Path $Venv 'Scripts\python.exe'
$venvPythonW = Join-Path $Venv 'Scripts\pythonw.exe'
if (Test-Path $venvPython) {
    $existing = Run-Quietly $venvPython @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')
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
    & $venvPython -m pip @Arguments
    return ($LASTEXITCODE -eq 0)
}

Pip @('install', '--upgrade', 'pip', '--quiet')

Info 'Installing PyGObject and pycairo (the gvsbuild wheels that match the GTK runtime)...'
$wheelTag = "-cp$($chosen.Replace('.', ''))-"
$gobject = $gobjectWheels | Where-Object { $_.Name -like "*$wheelTag*" } | Select-Object -First 1
$cairo   = $cairoWheels   | Where-Object { $_.Name -like "*$wheelTag*" } | Select-Object -First 1
if (-not $gobject -or -not $cairo) { Fail "The runtime has no PyGObject and pycairo wheels for Python $chosen." }
Pip @('install', '--force-reinstall', '--quiet', $cairo.FullName, $gobject.FullName)

# -- 4. PyTorch and llama.cpp ---------------------------------------------------------------------------

function Test-BuildTools {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { return $false }
    $found = Run-Quietly $vswhere @('-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath')
    return [bool]$found
}

function Install-LlamaFromSource {
    if (-not (Test-BuildTools)) {
        Fail ("Compiling llama.cpp needs the Visual Studio Build Tools (C++ workload) and CMake. Install them with:`n" +
              "    winget install Microsoft.VisualStudio.2022.BuildTools --override `"--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended`"`n" +
              "    winget install Kitware.CMake`n" +
              "then open a new PowerShell window and run this script again.")
    }
    if ($Cuda) {
        if (-not (Get-Command nvcc -ErrorAction SilentlyContinue)) { Fail 'CUDA build requested but nvcc was not found. Install the NVIDIA CUDA Toolkit first.' }
        $env:CMAKE_ARGS = '-DGGML_CUDA=on'
    }
    Info 'Compiling llama-cpp-python (this takes several minutes)...'
    Pip @('install', 'llama-cpp-python', '--no-cache-dir', '--no-binary', 'llama-cpp-python')
}

if ($SkipHeavy) {
    Warn 'Skipping PyTorch and llama-cpp-python (-SkipHeavy). The application cannot answer questions without them.'
} else {
    if ($Cuda) {
        Info 'Installing PyTorch (CUDA build)...'
        Pip @('install', 'torch', '--quiet')
    } else {
        Info 'Installing CPU-only PyTorch...'
        Pip @('install', 'torch', '--index-url', 'https://download.pytorch.org/whl/cpu', '--quiet')
    }

    if ($BuildLlamaFromSource -or ($Cuda -and -not $LlamaIndexUrl)) {
        Install-LlamaFromSource
    } else {
        $index = if ($LlamaIndexUrl) { $LlamaIndexUrl } else { $CpuLlamaIndex }
        Info "Installing llama-cpp-python (prebuilt wheel from $index)..."
        if (-not (Try-Pip @('install', 'llama-cpp-python', '--only-binary', 'llama-cpp-python', '--extra-index-url', $index, '--quiet'))) {
            Warn "No prebuilt llama-cpp-python wheel for Python $chosen was found at $index; building it from source instead."
            Install-LlamaFromSource
        }
    }
}

# -- 5. Istinbat itself ---------------------------------------------------------------------------------

Info 'Installing Istinbat and its Python dependencies...'
if ($SkipHeavy) {
    Pip @('install', '--quiet', 'numpy', 'rank-bm25', 'markdown-it-py', 'pytest')
    Pip @('install', '--quiet', '--no-deps', '-e', $ProjectRoot)
} else {
    Pip @('install', '--quiet', '-e', $ProjectRoot)
}
Ok 'Python dependencies installed.'

# -- 6. Check that the toolkit really loads -------------------------------------------------------------

Info 'Checking that GTK 4 and libadwaita load...'
$env:ISTINBAT_GTK_DIR = $GtkDir
$probe = "import istinbat.gui, gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); " +
         "from gi.repository import Gtk, Adw; print('GTK %d.%d, libadwaita %d.%d' % (Gtk.get_major_version(), Gtk.get_minor_version(), Adw.get_major_version(), Adw.get_minor_version()))"
$ErrorActionPreference = 'Continue'      # Windows PowerShell 5.1 turns native stderr into errors under 'Stop'.
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

# -- 7. Start menu entry --------------------------------------------------------------------------------

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
Write-Host 'First launch: press "Download Models..." (or open Preferences, Ctrl+,), pick the models and press'
Write-Host 'Reload models when they finish. Then set your books folder and index your .txt books.'
