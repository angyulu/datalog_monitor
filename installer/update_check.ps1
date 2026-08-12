# Silently checks GitHub for a newer commit on main; if found, downloads and applies
# updated app files (app.py, datalog_monitor/, pages/, requirements.txt) in place.
# Any failure here (offline, GitHub unreachable, etc.) is swallowed -- this must
# never block launching the app with whatever is already installed.
#
# The swap itself is rename-based (not copy-over-live / delete-then-copy): app.py,
# datalog_monitor/, and pages/ are staged next to the live copies, then swapped
# into place with Rename-Item, which is a single fast filesystem op rather than
# walking every file. If a lock (e.g. antivirus scanning the freshly-extracted
# files) or any other failure interrupts the swap partway through, whatever
# already landed is rolled back so app.py, datalog_monitor/, and pages/ never end
# up paired from two different commits (which throws an ImportError, or a
# StreamlitAPIException for a missing page, on launch). version.json is only
# written once every file has been swapped in successfully.
#
# Most filesystem cmdlets (Rename-Item, Copy-Item, Remove-Item) report failures
# as *non-terminating* errors by default -- a bare try/catch around them does
# NOT catch a locked/in-use file, it just prints a warning and carries on to
# the next line, which is how app.py, datalog_monitor/, and pages/ could end up
# on different commits with no exception ever being raised. Forcing every error
# to be terminating here is what makes the try/catch (and the rollback) actually
# work.
$ErrorActionPreference = "Stop"

$RepoOwner = "angyulu"
$RepoName = "datalog_monitor"
$Branch = "main"

$RootDir = $PSScriptRoot
$VersionFile = Join-Path $RootDir "version.json"
$PythonExe = Join-Path $RootDir "python\python.exe"
$destApp = Join-Path $RootDir "app.py"
$destPkg = Join-Path $RootDir "datalog_monitor"
$destPages = Join-Path $RootDir "pages"

# --- Self-update ---------------------------------------------------------
# This script is not one of the files the swap below applies (app.py,
# datalog_monitor/, pages/, requirements.txt) -- it's the thing doing the
# swapping. Without this step, a bug fixed here would never reach an
# already-installed copy: it would keep running its own stale logic on every
# future launch forever, no matter what gets pushed to GitHub, because the
# only code capable of fetching the fix is the exact code that needs it.
#
# Refresh this file first, in its own short-lived step, then hand off to a
# freshly-launched process running the new copy -- a script must not keep
# executing after replacing the file it was loaded from. Guarded by an env
# var so a relaunch can never loop more than once even if content still
# compares as different for some benign reason.
if (-not $env:DATALOG_MONITOR_UPDATER_RELAUNCHED) {
    $selfPath = $PSCommandPath
    $selfBackup = "$selfPath.bak"
    $stagedSelf = "$selfPath.new"
    try {
        if (-not (Test-Path $selfPath) -and (Test-Path $selfBackup)) {
            Rename-Item -Path $selfBackup -NewName (Split-Path $selfPath -Leaf)
        }
        if (Test-Path $stagedSelf) { Remove-Item -Path $stagedSelf -Force -ErrorAction SilentlyContinue }

        $headers = @{ "User-Agent" = "DatalogMonitorUpdater" }
        Invoke-WebRequest `
            -Uri "https://raw.githubusercontent.com/$RepoOwner/$RepoName/$Branch/installer/update_check.ps1" `
            -Headers $headers -OutFile $stagedSelf -TimeoutSec 10

        $selfChanged = $true
        if (Test-Path $selfPath) {
            $oldHash = (Get-FileHash -Path $selfPath -Algorithm SHA256).Hash
            $newHash = (Get-FileHash -Path $stagedSelf -Algorithm SHA256).Hash
            $selfChanged = $oldHash -ne $newHash
        }

        if ($selfChanged) {
            if (Test-Path $selfBackup) { Remove-Item -Path $selfBackup -Force -ErrorAction SilentlyContinue }
            try {
                Rename-Item -Path $selfPath -NewName (Split-Path $selfBackup -Leaf)
                Rename-Item -Path $stagedSelf -NewName (Split-Path $selfPath -Leaf)
            } catch {
                if ((Test-Path $selfBackup) -and -not (Test-Path $selfPath)) {
                    Rename-Item -Path $selfBackup -NewName (Split-Path $selfPath -Leaf) -ErrorAction SilentlyContinue
                }
                throw
            }
            Remove-Item -Path $selfBackup -Force -ErrorAction SilentlyContinue

            $env:DATALOG_MONITOR_UPDATER_RELAUNCHED = "1"
            & powershell -NoProfile -ExecutionPolicy Bypass -File $selfPath
            exit $LASTEXITCODE
        } else {
            Remove-Item -Path $stagedSelf -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Host "Self-update check skipped (will retry next launch): $($_.Exception.Message)"
    }
}

# Self-heal: if a previous update was killed mid-swap (live copy renamed to
# .bak, staged copy never renamed into place), restore the backup so the app
# can still launch with whatever was last known-good. Each item is independent
# and best-effort -- one failing here must not stop the other from being
# checked, or stop the update check below from running.
foreach ($live in @($destApp, $destPkg, $destPages)) {
    $backup = "$live.bak"
    if (-not (Test-Path $live) -and (Test-Path $backup)) {
        try { Rename-Item -Path $backup -NewName (Split-Path $live -Leaf) } catch {}
    }
}

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

# Renames $NewPath into place at $LivePath, backing up whatever was already at
# $LivePath (as "$LivePath.bak") so it can be restored on failure. Returns the
# backup path, or $null if there was nothing to back up, so the caller can
# clean it up once the whole update has succeeded.
function Swap-IntoPlace {
    param([string]$LivePath, [string]$NewPath)
    $backupPath = "$LivePath.bak"
    if (Test-Path $backupPath) { Remove-Item -Path $backupPath -Recurse -Force -ErrorAction SilentlyContinue }
    $hadExisting = Test-Path $LivePath
    if ($hadExisting) {
        Rename-Item -Path $LivePath -NewName (Split-Path $backupPath -Leaf)
    }
    try {
        Rename-Item -Path $NewPath -NewName (Split-Path $LivePath -Leaf)
    } catch {
        if ($hadExisting) { Rename-Item -Path $backupPath -NewName (Split-Path $LivePath -Leaf) }
        throw
    }
    if ($hadExisting) { return $backupPath }
    return $null
}

$tempDir = $null
try {
    $headers = @{ "User-Agent" = "DatalogMonitorUpdater" }
    $latest = Invoke-RestMethod -Uri "https://api.github.com/repos/$RepoOwner/$RepoName/commits/$Branch" `
        -Headers $headers -TimeoutSec 10
    $latestSha = $latest.sha
    $installedSha = Get-InstalledSha

    # An install can have version.json pinned at the latest sha yet still be
    # missing pages/ -- e.g. a machine updated by a pre-fix version of this
    # script, which recorded success without ever fetching the (then-new)
    # pages/ folder. Treat that as not up to date so it self-heals here
    # instead of silently staying broken forever.
    $pagesMissing = -not (Test-Path $destPages)

    if ($installedSha -eq $latestSha -and -not $pagesMissing) {
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
    $srcPages = Join-Path $extractedDir.FullName "pages"
    $srcReq = Join-Path $extractedDir.FullName "requirements.txt"
    $destReq = Join-Path $RootDir "requirements.txt"

    $reqChanged = $true
    if (Test-Path $destReq) {
        $oldHash = (Get-FileHash $destReq -Algorithm SHA256).Hash
        $newHash = (Get-FileHash $srcReq -Algorithm SHA256).Hash
        $reqChanged = $oldHash -ne $newHash
    }

    # Stage the new package/app/pages next to the live ones (same volume, so
    # the swap below is a fast rename) before touching anything live.
    $stagedPkg = Join-Path $RootDir "datalog_monitor.new"
    $stagedApp = Join-Path $RootDir "app.py.new"
    $stagedPages = Join-Path $RootDir "pages.new"
    if (Test-Path $stagedPkg) { Remove-Item -Path $stagedPkg -Recurse -Force }
    if (Test-Path $stagedApp) { Remove-Item -Path $stagedApp -Force }
    if (Test-Path $stagedPages) { Remove-Item -Path $stagedPages -Recurse -Force }
    Copy-Item -Path $srcPkg -Destination $stagedPkg -Recurse -Force
    Copy-Item -Path $srcApp -Destination $stagedApp -Force
    Copy-Item -Path $srcPages -Destination $stagedPages -Recurse -Force

    $pkgBackup = $null
    $appBackup = $null
    $pagesBackup = $null
    $pkgApplied = $false
    $pagesApplied = $false
    try {
        $pkgBackup = Swap-IntoPlace -LivePath $destPkg -NewPath $stagedPkg
        $pkgApplied = $true
        $pagesBackup = Swap-IntoPlace -LivePath $destPages -NewPath $stagedPages
        $pagesApplied = $true
        $appBackup = Swap-IntoPlace -LivePath $destApp -NewPath $stagedApp
    } catch {
        # app.py's own swap already rolled itself back internally if that's
        # what failed -- only the package/pages swaps need undoing here.
        if ($pagesApplied -and $pagesBackup) {
            if (Test-Path $destPages) { Remove-Item -Path $destPages -Recurse -Force -ErrorAction SilentlyContinue }
            Rename-Item -Path $pagesBackup -NewName (Split-Path $destPages -Leaf) -ErrorAction SilentlyContinue
        }
        if ($pkgApplied -and $pkgBackup) {
            if (Test-Path $destPkg) { Remove-Item -Path $destPkg -Recurse -Force -ErrorAction SilentlyContinue }
            Rename-Item -Path $pkgBackup -NewName (Split-Path $destPkg -Leaf) -ErrorAction SilentlyContinue
        }
        throw
    }

    Copy-Item -Path $srcReq -Destination $destReq -Force

    if ($reqChanged) {
        Write-Host "requirements.txt changed -- updating packages..."
        & $PythonExe -m pip install -r $destReq --no-warn-script-location --disable-pip-version-check -q
    }

    @{ sha = $latestSha; updated_at = (Get-Date -Format "o") } |
        ConvertTo-Json | Set-Content -Path $VersionFile -Encoding utf8

    if ($pkgBackup) { Remove-Item -Path $pkgBackup -Recurse -Force -ErrorAction SilentlyContinue }
    if ($appBackup) { Remove-Item -Path $appBackup -Force -ErrorAction SilentlyContinue }
    if ($pagesBackup) { Remove-Item -Path $pagesBackup -Recurse -Force -ErrorAction SilentlyContinue }
    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Updated to $($latestSha.Substring(0,7))."
}
catch {
    if ($tempDir -and (Test-Path $tempDir)) { Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host "Update check skipped (will retry next launch): $($_.Exception.Message)"
}
