Option Explicit

Dim files, shell, root, runtime, executable, quote
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = files.GetParentFolderName(WScript.ScriptFullName)
runtime = files.BuildPath(files.GetParentFolderName(root), files.GetFileName(root) & "-build\bin")
executable = files.BuildPath(runtime, "PromptToCAD.exe")
quote = Chr(34)

If Not files.FileExists(executable) Then
    MsgBox "The desktop build is missing. Rebuild Prompt to CAD in the sibling build folder before opening it.", vbExclamation, "Prompt to CAD"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
shell.Environment("Process")("QT_QPA_PLATFORM_PLUGIN_PATH") = files.BuildPath(runtime, "plugins\platforms")
shell.Environment("Process")("CSF_ShadersDirectory") = files.BuildPath(runtime, "resources\Shaders")
shell.Environment("Process")("PATH") = runtime & ";" & shell.Environment("Process")("PATH")
shell.Run quote & executable & quote & " --workspace " & quote & root & quote, 1, False
