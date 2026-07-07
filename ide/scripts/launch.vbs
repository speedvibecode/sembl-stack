' Flash-free wrapper for launch.ps1 — shortcuts target this via wscript.exe so no
' console window blinks on click. Any arguments are passed through to the ps1
' (the login auto-start shortcut passes -BackendOnly).
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
extra = ""
For Each a In WScript.Arguments
    extra = extra & " " & a
Next
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptDir & "\launch.ps1""" & extra, 0, False
