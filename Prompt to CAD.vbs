Option Explicit
Dim shell, files, folder, interpreter, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)

If files.FileExists(folder & "\.venv\Scripts\pythonw.exe") Then
    interpreter = folder & "\.venv\Scripts\pythonw.exe"
ElseIf files.FileExists("C:\Program Files\Python311\pythonw.exe") Then
    interpreter = "C:\Program Files\Python311\pythonw.exe"
Else
    interpreter = "pythonw.exe"
End If

shell.CurrentDirectory = folder
command = """" & interpreter & """ -B """ & folder & "\desktop-app.py"""
On Error Resume Next
shell.Run command, 0, False
If Err.Number <> 0 Then
    MsgBox "Could not find Python for Prompt to CAD. Install Python or check README.md.", 16, "Prompt to CAD"
End If
