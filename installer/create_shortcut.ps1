# Creates a "Datalog Monitor" desktop shortcut pointing at this folder's launcher.
# Run this once after copying the portable folder to a new machine.

$RootDir = $PSScriptRoot
$TargetPath = Join-Path $RootDir "launch.bat"
$IconPath = Join-Path $RootDir "icon.ico"
$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Datalog Monitor.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = $RootDir
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Description = "Datalog Monitor"
$Shortcut.Save()

Write-Host "Created desktop shortcut: $ShortcutPath"
