# Security policy

## Supported versions

Controlify is a small local utility. Security fixes are applied to the latest
release on the default branch; older snapshots are not maintained.

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Reporting a vulnerability

Please **do not open a public issue with exploit details, secrets, or personal
data**.

1. If the repository has **Security → Report a vulnerability** enabled, use
   GitHub's private vulnerability reporting.
2. Otherwise, open a minimal issue asking for a private contact channel. Do not
   include the vulnerability details in that issue.
3. Include the version, Windows version, steps to reproduce, and the impact.
   Redact song/show names, file paths containing your username, and any tokens.

You can expect an acknowledgement when the report is seen. This is a
spare-time project, so a fix may take a while; please do not publish details
before there has been a chance to respond.

## Scope

Controlify runs as your normal user account. It does **not**:

* make network requests, collect telemetry, or require an account;
* run a local server or accept remote connections;
* install a driver, service, or kernel component;
* request elevation (the autostart task is registered for the current user with
  `RunLevel Limited`);
* modify Spotify or Wispr Flow files.

It **does**:

* read Spotify's media session, window title, and per-app audio level through
  Windows APIs;
* read the process list to find Spotify and Wispr Flow;
* read `%APPDATA%\Wispr Flow\config.json` read-only, if present;
* read the Windows microphone consent store as a fallback for older Wispr
  builds;
* write `controlify.log`, `state.json`, `settings.json`, and volume-scaled cue
  clips next to the script;
* create `HKCU\Software\Classes\AppUserModelId\Controlify` so Windows can label
  its toast notifications.

## Practical hardening

* Keep the project in a folder only you can write to. The app runs Python code
  from that folder and loads a local `.venv`; another user who can modify those
  files can run code as you.
* Do not run `controlify.py` as administrator. It does not need it, and the
  scheduled task is deliberately registered with limited privileges.
* Review the `.bat`, `.vbs`, and `.ps1` launchers before running them. They are
  plain text.
* The log can contain the titles of songs and podcast episodes. Treat it as
  private and redact it before sharing.
* `settings.json` and `state.json` contain only local preferences and ad-break
  timings; they are not secrets, but they are machine-specific and gitignored.

## Third-party components

Runtime dependencies are listed in `requirements.txt` and installed from PyPI
by `setup.bat`. The bundled cue WAVs were generated with a Piper voice; see
[clips/README.md](clips/README.md) for that audio licence. The Piper voice model
itself is not included.
