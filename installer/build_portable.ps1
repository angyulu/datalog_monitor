# Builds a self-contained "portable" copy of Datalog Monitor: an embeddable Python
# runtime with all dependencies pre-installed, plus the app and launcher/updater
# scripts. Run this on a dev machine with internet access; the output folder
# (dist\portable) needs no Python installation on the machine it's copied to.
#
# Usage: powershell -ExecutionPolicy Bypass -File installer\build_portable.ps1

$ErrorActionPreference = "Stop"

$PythonVersion = "3.12.10"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$InstallerDir = $PSScriptRoot
$DistDir = Join-Path $RepoRoot "dist\portable"

Write-Host "=== Building portable Datalog Monitor -> $DistDir ==="

if (Test-Path $DistDir) {
    Write-Host "Removing previous build..."
    Remove-Item -Path $DistDir -Recurse -Force
}
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null

# --- 1. Embeddable Python runtime ---
$PythonDir = Join-Path $DistDir "python"
$embedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$embedZip = Join-Path $env:TEMP "python-$PythonVersion-embed-amd64.zip"

Write-Host "Downloading embeddable Python $PythonVersion..."
Invoke-WebRequest -Uri $embedUrl -OutFile $embedZip
Expand-Archive -Path $embedZip -DestinationPath $PythonDir -Force

# Enable site-packages (disabled by default in embeddable builds) so pip installs
# are importable.
$verTag = ($PythonVersion -split '\.')[0] + ($PythonVersion -split '\.')[1]
$pthFile = Join-Path $PythonDir "python$verTag._pth"
if (-not (Test-Path $pthFile)) {
    throw "Expected _pth file not found: $pthFile"
}
(Get-Content $pthFile) -replace '^#\s*import site', 'import site' | Set-Content $pthFile

# --- 2. Bootstrap pip ---
Write-Host "Bootstrapping pip..."
$getPipPath = Join-Path $env:TEMP "get-pip.py"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath
& (Join-Path $PythonDir "python.exe") $getPipPath --no-warn-script-location

# --- 3. App code ---
Write-Host "Copying app code..."
Copy-Item -Path (Join-Path $RepoRoot "app.py") -Destination $DistDir -Force
Copy-Item -Path (Join-Path $RepoRoot "datalog_monitor") -Destination $DistDir -Recurse -Force
Copy-Item -Path (Join-Path $RepoRoot "pages") -Destination $DistDir -Recurse -Force
Copy-Item -Path (Join-Path $RepoRoot "requirements.txt") -Destination $DistDir -Force

# --- 4. Install dependencies into the embedded runtime ---
Write-Host "Installing dependencies (this takes a few minutes)..."
& (Join-Path $PythonDir "python.exe") -m pip install -r (Join-Path $DistDir "requirements.txt") `
    --no-warn-script-location --disable-pip-version-check

# --- 5. Launcher, updater, shortcut creator, icon ---
Write-Host "Copying launcher/updater scripts..."
Copy-Item -Path (Join-Path $InstallerDir "launch.bat") -Destination $DistDir -Force
Copy-Item -Path (Join-Path $InstallerDir "launch_silent.vbs") -Destination $DistDir -Force
Copy-Item -Path (Join-Path $InstallerDir "update_check.ps1") -Destination $DistDir -Force
Copy-Item -Path (Join-Path $InstallerDir "create_shortcut.ps1") -Destination $DistDir -Force
Copy-Item -Path (Join-Path $InstallerDir "Create Desktop Shortcut.bat") -Destination $DistDir -Force
Copy-Item -Path (Join-Path $InstallerDir "assets\icon.ico") -Destination $DistDir -Force

# --- 6. Record the currently-built commit so the updater doesn't immediately
#        re-download the version it was just built from. ---
$sha = $null
try {
    Push-Location $RepoRoot
    $sha = (git rev-parse HEAD).Trim()
    Pop-Location
} catch {
    Write-Host "Warning: could not determine current git commit; version.json will be omitted." -ForegroundColor Yellow
}
if ($sha) {
    @{ sha = $sha; updated_at = (Get-Date -Format "o") } |
        ConvertTo-Json | Set-Content -Path (Join-Path $DistDir "version.json") -Encoding utf8
}

Write-Host ""
Write-Host "=== Build complete: $DistDir ===" -ForegroundColor Green
Write-Host "Copy this whole folder to the target machine, then run 'Create Desktop Shortcut.bat' once."
