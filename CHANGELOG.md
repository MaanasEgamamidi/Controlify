# Changelog

All notable changes to Controlify are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-10-27

First public release.

### Added

- Ad muting for the Spotify desktop app: detects ads from the media session and
  window title, sets only Spotify's audio session to volume 0, and restores the
  previous volume when the break ends.
- Crash-safe volume restore through `state.json`, plus `--restore` and a
  tray/settings action.
- Dictation pause for Wispr Flow: pauses Spotify through its own media session
  and resumes only playback that Controlify paused.
- Ad-break measurement and prediction: records each break's ads and length, then
  uses the median of the last 20 for the next notification.
- Silent Windows toast with the predicted ad count and mute time.
- Optional spoken cue ("ad start" / "ad start, not muted") using bundled neural
  voice clips, with a SAPI fallback.
- Podcast-episode exemption so a whole episode is not mistaken for an ad, while
  real ads inside a podcast still mute.
- `--fix-default-mic` to keep a Bluetooth headset in stereo while dictating.
- System tray icon with live status and switches for ad muting, dictation pause,
  cue, and notification. **Quit Controlify** stops the watcher/keeper as well,
  so it is not immediately restarted, while leaving autostart enabled.
- Settings window (`settings.bat` or **Settings...** on the tray), with
  `settings.json` persistence and live reload.
- `--no-tray` and `--settings` command-line options.
- Keeper/watcher supervision, `install-autostart.ps1`, `run-hidden.vbs`, and
  `stop.bat`.
- Self-contained test suite with synthetic Spotify metadata (79 tests).
- Documentation: README, FAQ, contributing guide, security policy, issue forms,
  pull-request template, architecture diagram, and settings screenshot.

### Changed

- Command-line flags now override saved settings for the current run instead of
  always being the only configuration.
- Ad muting and dictation pause can be switched off while running without
  leaving Spotify muted or paused.

### Notes

- Windows 10/11 only. Tested with Python 3.14 and Spotify desktop.
- The bundled cue audio is licensed CC BY-NC-SA 4.0 because of the Piper
  `en_US-ryan-medium` voice; the code is MIT. See `LICENSE` and
  `clips/README.md`.
