"""Native Windows folder picker, shared by any page that needs one."""
import subprocess


def _ps_single_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def pick_folder_dialog(initial_dir: str | None) -> str | None:
    """Native folder picker via PowerShell + WinForms.

    Not tkinter: the Windows embeddable Python distribution used for the
    portable/no-install build doesn't ship tkinter at all, and PowerShell's
    WinForms are present on every Windows machine with no bundling needed.
    """
    initial_dir_literal = _ps_single_quote(initial_dir) if initial_dir else "''"
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select the folder'
$initial = {initial_dir_literal}
if ($initial -and (Test-Path $initial)) {{
    $dialog.SelectedPath = $initial
}}
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output $dialog.SelectedPath
}}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=180,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    path = result.stdout.strip()
    return path or None
