' Start the Controlify watcher in the background (no window). It launches
' Controlify when Spotify opens and Controlify exits when Spotify closes.
' Stop everything with stop.bat.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
If Not fso.FileExists(dir & "\.venv\Scripts\pythonw.exe") Then
    MsgBox "Controlify is not set up yet. Run setup.bat first.", 16, "Controlify"
    WScript.Quit 1
End If
sh.CurrentDirectory = dir
sh.Run """" & dir & "\.venv\Scripts\pythonw.exe"" """ & dir & "\controlify.py"" --watch", 0, False
