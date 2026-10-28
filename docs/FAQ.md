# FAQ

Short answers to the questions that come up most often. For setup steps, see
the [README](../README.md).

## General

### Does Controlify remove ads?

No. It mutes Spotify's own audio session while an ad is playing, then restores
the volume. The ad still plays (silently) and still counts as heard. It does not
skip ads, edit Spotify, or unlock Premium.

### Does it work on macOS or Linux?

No. It uses Windows media-session, per-app audio, microphone, and
toast-notification APIs. It is Windows 10/11 only.

### Does it need Spotify Premium?

No. It works with Free and Premium. Ad muting only matters on Free; the
dictation pause works on both.

### Does it work with the Microsoft Store version of Spotify?

Usually. Controlify looks for a process named `spotify.exe` and a media session
whose app id starts with `spotify`, which the Store build normally provides. If
it cannot find the session, please open an issue with the log.

### Does it work with the Spotify web player, phone, or Cast devices?

No. It only controls the Spotify desktop app on the same PC. It never changes
the system volume or other apps' volume.

### Will I get banned from Spotify?

Controlify is unofficial and not endorsed by Spotify. Muting ads may conflict
with Spotify's terms of service. Check the terms that apply to you and use it at
your own risk. See the disclaimer in the [README](../README.md#disclaimer).

### Does it send anything to the internet?

No. It makes no network requests, has no telemetry, and needs no account. It
reads local Windows state and writes local files. See
[Privacy](../README.md#privacy).

## Setup and running

### What do I need installed?

Windows 10/11, Python 3.9+ from python.org, and the Spotify desktop app. Wispr
Flow is only needed for the dictation pause. Run `setup.bat` once to create the
local `.venv` and install dependencies.

### Why does Windows SmartScreen warn about the scripts?

The project is not code-signed. The `.bat`, `.vbs`, and `.ps1` files are plain
text; open them in Notepad if you want to check what they do before running
them. `setup.bat` only creates `.venv` and installs `requirements.txt`.

### How do I start it automatically at logon?

Run PowerShell in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1
```

This registers a scheduled task called `Controlify`. `stop.bat` disables it.

### How do I stop it?

Run `stop.bat`. It stops the keeper, watcher, and Controlify, disables the
scheduled task, and restores Spotify's volume if an ad was muted. To stop only
the current run without disabling autostart, use the tray icon's **Quit
Controlify** item (it also stops the keeper and watcher, but leaves the
scheduled task enabled, so autostart returns at the next logon) or close the
console window started by `run.bat`.

### Why do I see two or three copies of Python in Task Manager?

The keeper supervises the watcher, and the watcher starts Controlify when
Spotify opens. Each level shows up twice because `.venv\Scripts\pythonw.exe` is
a launcher that re-runs the same script with the real interpreter. See
[Staying alive](../README.md#staying-alive).

### Why is there no tray icon?

The tray needs `pystray` and `Pillow`. `setup.bat` installs them; if you created
the venv before they were added, run `setup.bat` again. A run with `--no-tray`
also has no icon. If the libraries are missing, Controlify logs a warning and
keeps working without the tray.

### The tray icon disappears when I close Spotify. Is that a bug?

No. In the recommended `run-hidden.vbs`/autostart setup, Controlify itself only
runs while Spotify is open, so its tray icon goes away with it. Use
`settings.bat` to change settings while Spotify is closed. If you start
`run.bat` without `--exit-with-spotify`, Controlify keeps running (and keeps its
tray icon) even when Spotify is closed.

### How do I change the settings?

Right-click the tray icon and choose **Settings...**, or run `settings.bat`.
The same values are stored in `settings.json` next to `controlify.py`; you can
edit that file by hand while Controlify is running and it will pick up the
change within a couple of seconds.

## Ad muting

### Why didn't an ad get muted?

Ad detection is heuristic. Check `controlify.log` for `spotify:` lines and the
`-> ad=...` marker. If the ad was not recognised, run `probe\probe.py` for 30-60
seconds while the ad plays, then open an issue with the relevant lines
(**remove song and show names first**). Spotify occasionally changes its
metadata; the rules in `controlify.py` may need updating.

### Why did a podcast get muted?

It should not. Podcast episodes are exempt from the window-title rule because
they have an album and either no artist or a window title equal to the episode
name. A real ad *inside* a podcast still mutes because Spotify labels it
"Advertisement". If a normal episode is muted, please open an issue with the
log lines.

### Why does the notification show a prediction instead of the real count?

Spotify only exposes the ad that is playing right now, never how many are
queued or how long the break lasts. Controlify measures each break as it happens
and predicts the next one from the median of the last 20. With no history it
assumes two ads of about 30 seconds each.

### Can I turn off the spoken cue or the notification?

Yes. Use the tray/settings window, or the flags `--no-announce` and
`--no-notify`. The cue volume is `--announce-volume 0-100` or the **Cue
volume** control in settings.

### The cue is silent. What should I check?

`--no-announce` may be set, the cue volume may be 0, or the two base clips in
`clips/` may be missing. If a clip is missing, Controlify falls back to Windows'
SAPI voice; the fallback voice name is configurable in settings.

## Dictation

### Why is Spotify paused but never resumed?

Controlify only resumes playback it paused itself. If you pressed play or pause
during dictation, it treats playback as yours and leaves it alone. If Spotify
was paused before dictation started, it is not resumed either.

### Does it pause for Wispr Flow meeting recordings?

Yes. Wispr uses the same `activeDictationSession` flag for meeting recording, so
Spotify pauses then too.

### Can I use a different dictation app?

Not currently. The dictation signal is specific to Wispr Flow's config file. Ad
muting does not need Wispr Flow at all.

### Wispr's own "mute all audio" setting is off. Will Spotify still pause?

By default, yes: any dictation pauses Spotify. Enable **Only when Wispr's "mute
all audio" is on** in settings (or pass `--pause-needs-wispr-setting`) to follow
Wispr's switch instead.

### Why does my Bluetooth headset sound bad while dictating?

A Bluetooth headset switches to hands-free (mono, low quality) while its own
microphone is open. Wispr may open the default *communications* mic, which can
be a headset left over from a call profile. Run:

```powershell
.venv\Scripts\python.exe controlify.py --fix-default-mic
```

This points every Windows mic role at the same device. See the Bluetooth note in
the [README](../README.md#notes).

## Privacy and uninstalling

### What files does it write?

`controlify.log`, `state.json`, `settings.json`, and volume-scaled cue clips in
`clips/`. It also creates one registry key so Windows can label its
notifications: `HKCU\Software\Classes\AppUserModelId\Controlify`.

### How do I uninstall it?

1. Run `stop.bat`.
2. Remove the scheduled task and startup shortcut:
   `powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1 -Remove`
3. Delete the project folder.
4. Optionally delete the registry key
   `HKCU\Software\Classes\AppUserModelId\Controlify`.

### Can I delete the log and state files?

Yes. They are recreated as needed. Delete them any time; the log can reveal what
you were listening to, so do not attach it to an issue without redacting song
and show names.
