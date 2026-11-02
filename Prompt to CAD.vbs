Option Explicit

Dim files, shell, root, runtime, executable, quote, python
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = files.GetParentFolderName(WScript.ScriptFullName)
runtime = files.BuildPath(root, ".local\desktop-build\bin")
executable = files.BuildPath(runtime, "PromptToCAD.exe")
quote = Chr(34)

If Not files.FileExists(executable) Or Not files.FileExists(files.BuildPath(runtime, "plugins\platforms\qwindows.dll")) Then
    python = files.BuildPath(root, ".venv\Scripts\pythonw.exe")
    executable = files.BuildPath(root, "build\bin\PromptToCAD.exe")
    If files.FileExists(python) And files.FileExists(executable) Then
        If WScript.Arguments.Named.Exists("check") Then
            WScript.Echo "Source build launcher ready."
            WScript.Quit 0
        End If
        shell.CurrentDirectory = root
        shell.Run quote & python & quote & " -m tools.run_native", 1, False
        WScript.Quit 0
    End If
    MsgBox "No application build was found. Follow README.md or docs/setup.md to set up dependencies and build build\bin\PromptToCAD.exe, then run Run-PromptToCAD.cmd.", vbExclamation, "Prompt to CAD"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
If WScript.Arguments.Named.Exists("check") Then
    WScript.Echo "Existing desktop launcher ready."
    WScript.Quit 0
End If
shell.Environment("Process")("QT_QPA_PLATFORM_PLUGIN_PATH") = files.BuildPath(runtime, "plugins\platforms")
shell.Environment("Process")("CSF_ShadersDirectory") = files.BuildPath(runtime, "resources\Shaders")
shell.Environment("Process")("PATH") = runtime & ";" & shell.Environment("Process")("PATH")
shell.Run quote & executable & quote & " --workspace " & quote & root & quote, 1, False
