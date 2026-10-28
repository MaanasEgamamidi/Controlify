# Pull request

## Summary

<!-- What changed, and why? Link the issue if there is one. -->

## Type of change

- [ ] Bug fix (detection rule, pause/resume, restore, install)
- [ ] New feature (tray, settings, notification, cue)
- [ ] Documentation
- [ ] Refactor / cleanup (no behaviour change)
- [ ] Tests only

## Testing

<!-- What did you run? Tick everything that applies. -->

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` passes.
- [ ] `run.bat --help` works.
- [ ] Tried it with real Spotify (ad mute and/or dictation pause).
- [ ] Tried the tray/settings window (if changed).
- [ ] Tried `stop.bat` and the volume restore (if changed).

## Checklist

- [ ] The change is focused and does not include unrelated formatting.
- [ ] New behaviour is documented (README, `docs/FAQ.md`, `CHANGELOG.md`).
- [ ] Detection changes include a synthetic test sample and no real listening
      history.
- [ ] No `controlify.log`, `state.json`, `settings.json`, `.venv/`, `voices/`, or
      personal data is committed.
- [ ] If the UI changed, the screenshot in `docs/` is still accurate or was
      updated.
- [ ] New runtime dependencies are in `requirements.txt` and documented.

## Notes for reviewers

<!-- Anything subtle: timing, Spotify metadata quirks, Windows API behaviour. -->
