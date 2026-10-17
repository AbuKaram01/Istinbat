# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Builds the Windows installer (packaging\dist\istinbat-<version>-windows-setup.exe).
# Needs Inno Setup 6 (winget install JRSoftware.InnoSetup). Run from anywhere:
#
#     powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$pyproject = Get-Content (Join-Path $ProjectRoot 'pyproject.toml') -Raw -Encoding UTF8
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') { throw 'Could not read the version from pyproject.toml.' }
$Version = $Matches[1]

$candidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | ForEach-Object { $_.Source }),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path $_) }
if (-not $candidates) { throw 'Inno Setup 6 was not found. Install it with: winget install JRSoftware.InnoSetup' }

& @($candidates)[0] "/DAppVersion=$Version" (Join-Path $PSScriptRoot 'windows\istinbat.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE." }
Write-Host "Built: $(Join-Path $PSScriptRoot "dist\istinbat-$Version-windows-setup.exe")"
