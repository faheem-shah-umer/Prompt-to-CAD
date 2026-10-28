Option Explicit
Dim shell, files, folder, interpreter
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
interpreter = folder & "\.venv\Scripts\pythonw.exe"
If Not files.FileExists(interpreter) Then
    MsgBox "Set up the project Python environment first. See docs\native-workspace.md.", 16, "Prompt to CAD Native"
    WScript.Quit 1
End If
shell.CurrentDirectory = folder
shell.Run """" & interpreter & """ -B """ & folder & "\native-app.py""", 0, False
