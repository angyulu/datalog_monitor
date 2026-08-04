' Launches Datalog Monitor with no visible console window.
' To stop the app, end the "python" process in Task Manager.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir
shell.Run """" & scriptDir & "\launch.bat""", 0, False
