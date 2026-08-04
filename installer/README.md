# Portable / no-Python installer

Produces a self-contained copy of Datalog Monitor with its own bundled Python
runtime, so it can be copied to a Windows machine that has no Python installed
and just... run.

## Building it (do this on a dev machine with internet access)

```
powershell -ExecutionPolicy Bypass -File installer\build_portable.ps1
```

This downloads an embeddable Python runtime, installs all dependencies into it,
and copies the app + launcher/updater scripts into `dist\portable\`. Takes a
few minutes; the output folder is a few hundred MB (mostly pandas/pyarrow/numpy).

## Installing on a target machine

1. Copy the whole `dist\portable` folder to the target machine (network share,
   USB drive, etc. -- rename it to whatever you like).
2. Double-click **`Create Desktop Shortcut.bat`** once. This adds a "Datalog
   Monitor" icon to the desktop.
3. Double-click the desktop icon to launch. Streamlit opens your default
   browser automatically. Close the console window to stop the app.

No Python, pip, or any other install step is required on the target machine --
everything needed lives inside the copied folder.

## Auto-update

Every time it's launched, `launch.bat` runs `update_check.ps1` first, which:

1. Asks the GitHub API for the latest commit on `main`.
2. Compares it against `version.json` (the commit this copy was last updated to).
3. If newer, downloads a zip of that commit, replaces `app.py` and
   `datalog_monitor\`, reinstalls dependencies only if `requirements.txt`
   changed, and updates `version.json`.

This requires the target machine to reach `github.com`/`api.github.com`. If it
can't (offline, firewalled), the check silently fails and the app launches
with whatever's already installed -- it never blocks startup.

To disable auto-update on a given machine, open `launch.bat` and delete the
`powershell ... update_check.ps1` line -- the app launches with whatever's
currently installed and never checks GitHub.

## Files

| File | Purpose |
|---|---|
| `build_portable.ps1` | Builds `dist\portable\` from scratch (run on a dev machine, not distributed) |
| `make_icon.py` | Regenerates `assets/icon.ico` |
| `launch.bat` | Runs the updater, then starts Streamlit (visible console) |
| `launch_silent.vbs` | Same, but with no visible console window |
| `update_check.ps1` | The GitHub auto-updater, copied into the built bundle |
| `create_shortcut.ps1` / `Create Desktop Shortcut.bat` | Creates the desktop icon, copied into the built bundle |
