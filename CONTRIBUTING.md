# Contributing to Controlify

Thanks for taking a look. Controlify is a small, Windows-only utility, so the
most useful contributions are focused bug reports, detection-rule fixes, and
careful changes that keep the app quiet and unobtrusive.

## Before you start

* Read the [README](README.md) and [FAQ](docs/FAQ.md).
* Search existing issues and pull requests.
* For a security problem, follow [SECURITY.md](SECURITY.md) instead of opening
  a public issue with details.
* For a large change (new dependency, new feature, a redesign of the watcher),
  open an issue first so we can agree on the approach.

## Development setup

You need Windows 10/11 and Python 3.9+.

```bat
setup.bat --dev
.venv\Scripts\python.exe -m pytest tests -q
```

`setup.bat --dev` creates `.venv` and installs both `requirements.txt` and
`requirements-dev.txt`. The test suite is self-contained: it uses synthetic
Spotify metadata, so it needs no Spotify, Wispr Flow, or audio device.

Useful commands:

```bat
run.bat                     run with a console (Ctrl+C stops it)
run.bat --no-tray           run without the tray icon
settings.bat                open the settings window
.venv\Scripts\python.exe probe\probe.py 60
                            read-only signal log for detection work
```

## What to test manually

The automated suite covers the detection rules and the pause/resume state
machine. Before opening a pull request that touches the live app, also check the
parts that need real Windows/Spotify:

- [ ] An ad is muted and the volume comes back when the break ends.
- [ ] The ad-break toast appears and the spoken cue is audible (or silent when
      it should be).
- [ ] Dictation pauses Spotify, and playback resumes only if Controlify paused
      it.
- [ ] Starting dictation during an ad does not pause, and the pause happens when
      the ad ends.
- [ ] Tray toggles apply immediately; **Settings...** opens and saves.
- [ ] `stop.bat` restores the volume after an ad was muted.
- [ ] `run.bat --help` still lists the old flags.

## Changing ad detection

Ad detection is a heuristic and Spotify changes its metadata. When you fix a
rule:

1. Capture the signal with `probe\probe.py` while the ad plays.
2. Add a **synthetic** sample with the same shape to
   `tests/test_detect.py`. Do not commit real listening history, song names, or
   show names.
3. Explain in the pull request which rule changed and why the new sample is
   representative.
4. Keep podcast episodes exempt from the weak window-title rule; a real ad
   inside a podcast still announces itself as "Advertisement".

## Code style

* Python 3.9-compatible syntax, four-space indentation, PEP 8 in spirit.
* Keep the detection code (`controlify.py`) free of UI imports. The tray and
  settings window live in `ui.py` and are imported lazily, so a missing
  `pystray`/`Pillow` install cannot break ad muting.
* Prefer the standard library. A new runtime dependency needs a good reason and
  must be added to `requirements.txt` and documented in the README.
* Keep Windows-only behaviour explicit; there is no cross-platform fallback.
* Update the README, FAQ, and `CHANGELOG.md` when behaviour changes.
* Write commit messages in the imperative mood, e.g. `Fix podcast ad detection`
  or `Add tray settings window`.

## Pull request checklist

- [ ] `pytest tests -q` passes.
- [ ] `run.bat --help` works.
- [ ] New behaviour is documented (README/FAQ/CHANGELOG).
- [ ] No personal data, logs, `state.json`, `settings.json`, `voices/`, or
      `.venv/` are included.
- [ ] The change is focused; unrelated formatting is kept out.
- [ ] If the UI changed, the screenshot in `docs/` is still accurate (or was
      updated).

## Reporting bugs

Use the bug report issue form. Include:

* Windows version, Python version, and Spotify version.
* Whether you used `setup.bat`, `run.bat`, `run-hidden.vbs`, or autostart.
* The relevant tail of `controlify.log` (**redact song/show names**).
* For detection problems, a short `probe\probe.py` capture.

Please do not paste your whole log or `state.json`; a few lines around the
problem are enough.

## Be kind

This is a personal project maintained in spare time. Assume good faith, keep
discussion technical, and respect the licences of the bundled audio and voice
assets. See [LICENSE](LICENSE) and [clips/README.md](clips/README.md).
