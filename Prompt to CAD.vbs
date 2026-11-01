Option Explicit

Dim files, shell, root, python, executable, quote
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(root, ".venv\Scripts\pythonw.exe")
executable = files.BuildPath(root, "build\bin\PromptToCAD.exe")
quote = Chr(34)

If Not files.FileExists(executable) Or Not files.FileExists(python) Then
    MsgBox "Complete the contributor setup in docs/setup.md, then run python -m tools.build_native. Portable users should use Start-PromptToCAD.cmd from the extracted ZIP.", vbExclamation, "Prompt to CAD"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
shell.Run quote & python & quote & " -m tools.run_native", 1, False
