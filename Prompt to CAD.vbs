Option Explicit

Dim files, shell, root, executable, quote
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = files.GetParentFolderName(WScript.ScriptFullName)
executable = files.BuildPath(root, ".app-runtime\PromptToCAD.exe")
quote = Chr(34)

If Not files.FileExists(executable) Then
    MsgBox "The runnable application files are missing. Restore .app-runtime before opening Prompt to CAD.", vbExclamation, "Prompt to CAD"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
shell.Environment("Process")("QT_QPA_PLATFORM_PLUGIN_PATH") = files.BuildPath(root, ".app-runtime\plugins\platforms")
shell.Environment("Process")("CSF_ShadersDirectory") = files.BuildPath(root, ".app-runtime\resources\Shaders")
shell.Run quote & executable & quote & " --workspace " & quote & root & quote, 1, False
