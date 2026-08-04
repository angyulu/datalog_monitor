# Silently checks GitHub for a newer commit on main; if found, downloads and applies
# updated app files (app.py, datalog_monitor/, requirements.txt) in place.
# Any failure here (offline, GitHub unreachable, etc.) is swallowed -- this must
# never block launching the app with whatever is already installed.

$RepoOwner = "angyulu"
$RepoName = "datalog_monitor"
$Branch = "main"

$RootDir = $PSScriptRoot
$VersionFile = Join-Path $RootDir "version.json"
$PythonExe = Join-Path $RootDir "python\python.exe"

function Get-InstalledSha {
    if (Test-Path $VersionFile) {
        try {
            return (Get-Content $VersionFile -Raw | ConvertFrom-Json).sha
        } catch {
            return $null
        }
    }
    return $null
}

try {
    $headers = @{ "User-Agent" = "DatalogMonitorUpdater" }
    $latest = Invoke-RestMethod -Uri "https://api.github.com/repos/$RepoOwner/$RepoName/commits/$Branch" `
        -Headers $headers -TimeoutSec 10
    $latestSha = $latest.sha
    $installedSha = Get-InstalledSha

    if ($installedSha -eq $latestSha) {
        Write-Host "Datalog Monitor is up to date ($($latestSha.Substring(0,7)))."
        exit 0
    }

    $fromLabel = if ($installedSha) { $installedSha.Substring(0,7) } else { "none" }
    Write-Host "Update found: $fromLabel -> $($latestSha.Substring(0,7)). Downloading..."

    $tempDir = Join-Path $env:TEMP "datalog_monitor_update_$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $zipPath = Join-Path $tempDir "update.zip"

    Invoke-WebRequest -Uri "https://github.com/$RepoOwner/$RepoName/archive/$latestSha.zip" `
        -OutFile $zipPath -Headers $headers -TimeoutSec 60
    Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force

    $extractedDir = Get-ChildItem -Path $tempDir -Directory |
        Where-Object { $_.Name -like "$RepoName-*" } | Select-Object -First 1
    if (-not $extractedDir) { throw "Could not find extracted repo folder in downloaded archive." }

    $srcApp = Join-Path $extractedDir.FullName "app.py"
    $srcPkg = Join-Path $extractedDir.FullName "datalog_monitor"
    $srcReq = Join-Path $extractedDir.FullName "requirements.txt"

    $destReq = Join-Path $RootDir "requirements.txt"
    $reqChanged = $true
    if (Test-Path $destReq) {
        $oldHash = (Get-FileHash $destReq -Algorithm SHA256).Hash
        $newHash = (Get-FileHash $srcReq -Algorithm SHA256).Hash
        $reqChanged = $oldHash -ne $newHash
    }

    Copy-Item -Path $srcApp -Destination (Join-Path $RootDir "app.py") -Force

    $destPkg = Join-Path $RootDir "datalog_monitor"
    if (Test-Path $destPkg) { Remove-Item -Path $destPkg -Recurse -Force }
    Copy-Item -Path $srcPkg -Destination $RootDir -Recurse -Force

    Copy-Item -Path $srcReq -Destination $destReq -Force

    if ($reqChanged) {
        Write-Host "requirements.txt changed -- updating packages..."
        & $PythonExe -m pip install -r $destReq --no-warn-script-location --disable-pip-version-check -q
    }

    @{ sha = $latestSha; updated_at = (Get-Date -Format "o") } |
        ConvertTo-Json | Set-Content -Path $VersionFile -Encoding utf8

    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Updated to $($latestSha.Substring(0,7))."
}
catch {
    Write-Host "Update check skipped (offline or GitHub unreachable): $($_.Exception.Message)"
}
