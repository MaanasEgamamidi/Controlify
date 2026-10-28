"""Controlify: silence Spotify ads, and pause Spotify while Wispr Flow dictates.

* Ads: when Spotify's media session says an ad is playing, every Spotify audio
  session is set to volume 0; the previous volume is restored when the ad ends.
* Dictation: while Wispr Flow is dictating, Spotify is paused (through its own
  media session, not a global media key), and resumed afterwards if Controlify
  was the one that paused it.

A tray icon (optional; needs pystray + Pillow) exposes the same switches as
``settings.json`` and can open a small settings window.  ``--settings`` opens
that window on its own, without starting the watcher.
"""
import argparse
import asyncio
import ctypes
import ctypes.wintypes as wt
import json
import logging
import logging.handlers
import os
import signal
import statistics
import sys
import threading
import time
import winreg
from dataclasses import dataclass
from typing import Optional

import psutil

__version__ = "1.0.0"

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
LOG_FILE = os.path.join(HERE, "controlify.log")
WISPR_CONFIG = os.path.expandvars(r"%APPDATA%\Wispr Flow\config.json")
WISPR_SETTING_KEY = "shouldMuteAudio"
MIC_CONSENT_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager"
    r"\ConsentStore\microphone\NonPackaged"
)
# Seconds between the FILETIME epoch (1601-01-01) and the unix epoch.
FILETIME_EPOCH_OFFSET = 11644473600

# GlobalSystemMediaTransportControlsSessionPlaybackStatus
PLAYING, PAUSED = 4, 5

log = logging.getLogger("controlify")


# --------------------------------------------------------------------------
# Ad detection
# --------------------------------------------------------------------------
@dataclass
class Media:
    title: str
    artist: str
    album: str
    status: int
    window_title: str = ""


AD_TITLES = {"advertisement", "spotify advertising"}
SPOTIFY_ARTISTS = {"spotify", "spotify advertising"}
STRONG, WEAK = 2, 1
SIGNAL_NAMES = {0: "no", WEAK: "weak", STRONG: "strong"}


def is_episode(m: Media) -> bool:
    """A podcast episode rather than a track, so the ad rules below must not
    fire on it.

    Music always has an artist, and Spotify's window shows "Artist - Track"; a
    podcast episode is published with the *show* as the album, no artist at all,
    and a window title that is just the episode name. Either half identifies
    one, which covers feeds that do fill in an artist.

    The album is what tells an episode from an ad. Spotify publishes every ad
    *without* an album (the advertiser is the artist), while every track and
    every episode has one - so "no album" means ad, and an episode is only an
    episode if it has one. (Vetoing ads because their window title happened to
    equal their title is what let real ads play unmuted.)

    This only vetoes the weak rule: a session that really says "Advertisement"
    is still muted, including during a podcast's own ad breaks.
    """
    if not m.album.strip():
        return False
    return not m.artist.strip() or m.window_title.strip().lower() == m.title.strip().lower()


def ad_signal(m: Media) -> int:
    """STRONG if Spotify's media session itself says ad, WEAK if the metadata
    has the shape of an ad, 0 if it looks like a normal track or an episode.

    Real tracks have an artist + album and a window title of "Artist - Track".
    Ads are published with the advertiser as the artist ("Sample Brand",
    "Another Advertiser", ...) and *no album at all*, and Spotify's
    window then shows just the ad's own text instead of "Artist - Track".

    So an ad is one of two things: the window title is exactly the ad's text,
    or the window has dropped the "Artist - Track" form (e.g. "Advertisement",
    "Spotify Free", "LISTEN NOW", a bare dash). Podcast episodes look like the
    second case, so is_episode() vetoes them - but only when they have an
    album, which ads never do.

    The window rules only apply while PLAYING: a paused Spotify also shows
    "Spotify Free".
    """
    title, artist = m.title.strip().lower(), m.artist.strip().lower()
    if title in AD_TITLES or (artist in SPOTIFY_ARTISTS and not m.album.strip()):
        return STRONG
    if m.status != PLAYING:
        return 0
    if is_episode(m):
        return 0
    win = m.window_title.strip()
    if not win:
        return 0
    if win.lower() == title:
        # The window shows the ad's own text, not "Artist - Track".
        return WEAK
    if " - " not in win:
        # The window dropped the artist prefix - the older ad tell.
        return WEAK
    return 0


def is_ad(m: Media) -> bool:
    return ad_signal(m) > 0


# What the *next* ad break is likely to look like, learned from the breaks
# Spotify has already played on this PC. Spotify exposes only the ad that is
# playing right now - never how many are queued or how long the break runs -
# so the count and the lengths can only come from history. Every completed
# break is measured (each ad's own runtime and the break's total) and stored
# in state.json; the medians of those become the next prediction.
AD_HISTORY_MAX = 20
DEFAULT_AD_COUNT = 2
DEFAULT_AD_SECONDS = 30.0
MIN_AD_S = 5.0        # shorter than this is a metadata flicker, not a new ad
MIN_BREAK_S = 10.0    # ...and a break this short is not worth learning from


def predict_ad_break(breaks) -> tuple[int, float, float]:
    """(ads, seconds each, total seconds) for the break that just started.

    Medians, so one odd break can't skew it. Breaks that cannot be real are
    ignored: an ad shorter than 5s is a metadata flicker, and a break longer
    than 6 minutes is Spotify left paused halfway through one.
    """
    usable = [
        b for b in breaks
        if isinstance(b.get("ads"), list) and b["ads"]
        and all(isinstance(a, (int, float)) and MIN_AD_S <= a <= 120 for a in b["ads"])
        and isinstance(b.get("total"), (int, float)) and MIN_BREAK_S <= b["total"] <= 360
    ]
    counts = [len(b["ads"]) for b in usable] or [DEFAULT_AD_COUNT]
    lengths = [a for b in usable for a in b["ads"]] or [DEFAULT_AD_SECONDS]
    totals = [b["total"] for b in usable] or [DEFAULT_AD_COUNT * DEFAULT_AD_SECONDS]
    return (round(statistics.median(counts)), statistics.median(lengths),
            statistics.median(totals))


def _ad_key(m: Optional[Media]) -> tuple[str, str]:
    """Artist + title, the only thing that changes from one ad to the next."""
    return ("", "") if m is None else (m.artist.strip().lower(), m.title.strip().lower())


# --------------------------------------------------------------------------
# Spotify audio sessions (per-app volume; never the master volume)
# --------------------------------------------------------------------------
def spotify_volume_controls():
    from pycaw.pycaw import AudioUtilities

    controls = []
    for s in AudioUtilities.GetAllSessions():
        try:
            if s.ProcessId and psutil.Process(s.ProcessId).name().lower() == "spotify.exe":
                controls.append(s.SimpleAudioVolume)
        except (psutil.Error, OSError):
            continue
    return controls


def set_spotify_volume(level: float) -> int:
    n = 0
    for c in spotify_volume_controls():
        try:
            c.SetMasterVolume(level, None)
            n += 1
        except Exception:
            log.exception("could not set Spotify session volume")
    return n


def current_spotify_volume() -> Optional[float]:
    vols = []
    for c in spotify_volume_controls():
        try:
            vols.append(c.GetMasterVolume())
        except Exception:
            pass
    return max(vols) if vols else None


# --------------------------------------------------------------------------
# Bluetooth quality: a headset drops to hands-free while its own mic is open
# --------------------------------------------------------------------------
def _endpoint_name(dev) -> str:
    from pycaw.pycaw import AudioUtilities

    try:
        return AudioUtilities.CreateDevice(dev).FriendlyName or ""
    except Exception:
        return ""


def default_capture_devices() -> dict[str, str]:
    """{role: friendly name} for the default capture device of each role.

    Windows keeps three mic roles. An app asking for "the default microphone"
    can land on the *communications* mic, which is often still a Bluetooth
    headset left over from a call profile. Opening a Bluetooth headset's own
    mic forces that headset into hands-free mode - mono, roughly 8kHz - until
    the mic closes. That is the "music sounds bad while I dictate, then
    recovers a few seconds later" effect, and it has nothing to do with
    muting.
    """
    import comtypes
    from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
    from pycaw.constants import CLSID_MMDeviceEnumerator, ERole
    from pycaw.pycaw import EDataFlow

    out = {}
    try:
        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator,
                                         comtypes.CLSCTX_INPROC_SERVER)
    except Exception:
        return out
    for role in (ERole.eConsole, ERole.eMultimedia, ERole.eCommunications):
        key = role.name.lstrip("e").lower()
        try:
            dev = enum.GetDefaultAudioEndpoint(EDataFlow.eCapture.value, role.value)
            out[key] = _endpoint_name(dev)
        except Exception:
            out[key] = ""
    return out


def align_default_mic() -> str:
    """Point every mic role at the same device (the console default), so no app
    can reach a Bluetooth headset mic by accident. Returns a log line."""
    from pycaw.constants import DEVICE_STATE, ERole
    from pycaw.pycaw import AudioUtilities, EDataFlow

    before = default_capture_devices()
    target = before.get("console") or before.get("multimedia")
    if not target:
        raise OSError("no default capture device found")
    device_id = next(
        (d.id for d in AudioUtilities.GetAllDevices(
            data_flow=EDataFlow.eCapture.value,
            device_state=DEVICE_STATE.ACTIVE.value) if d.FriendlyName == target),
        None)
    if device_id is None:
        raise OSError(f"no active capture device named {target!r}")
    AudioUtilities.SetDefaultDevice(
        device_id, roles=[ERole.eConsole, ERole.eMultimedia, ERole.eCommunications])
    after = default_capture_devices()
    return (f"console={after['console']!r} multimedia={after['multimedia']!r} "
            f"communications={after['communications']!r} "
            f"(communications was {before['communications']!r})")


def mic_role_warning() -> Optional[str]:
    """Warn when the mic dictation will open isn't the mic you normally use."""
    devs = default_capture_devices()
    comm, other = devs.get("communications", ""), devs.get("multimedia", "")
    if comm and other and comm != other:
        return (f"default communications mic is {comm!r} but the default mic is "
                f"{other!r}; dictation opens {comm!r}. If that is a Bluetooth "
                f"headset its mic, music drops to hands-free quality while you "
                f"dictate - run: controlify.py --fix-default-mic")
    return None


# --------------------------------------------------------------------------
# Wispr Flow: dictation signal + setting
# --------------------------------------------------------------------------
class WisprWatcher:
    """Dictation signal.

    Wispr Flow records the dictation it is running in its own config file:
    ``prefs.activeDictationSession`` is null while idle and holds the session
    (uuid + start timestamp) while you are dictating.  That is the signal we
    use - it flips within milliseconds of the hotkey.

    (The Windows microphone consent store used to be the signal, but Wispr
    stopped being tracked there: no consent entry is written for the current
    build at all, so the store stays silent even while dictation runs.)

    The consent store is still used as a fallback for builds that do not
    expose the config key: it records which app holds the mic, where
    LastUsedTimeStop is 0 (or older than LastUsedTimeStart) while open.
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._key_names: list[str] = []
        self._names_at = 0.0
        self._cfg_mtime = None
        self._cfg: Optional[dict] = None
        self._mute_setting = False

    # -- Wispr's own config ------------------------------------------------
    def _config(self) -> Optional[dict]:
        """Parsed config.json; re-read only when the file actually changed.

        A failed read (mid-write) keeps the previous parse and is retried on
        the next poll instead of being cached as "unchanged".
        """
        try:
            mtime = os.stat(self.config_path).st_mtime_ns
        except OSError:
            return None
        if mtime != self._cfg_mtime:
            try:
                with open(self.config_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                return self._cfg
            self._cfg = data
            self._cfg_mtime = mtime
        return self._cfg

    def _config_dictating(self) -> Optional[bool]:
        """True/False from Wispr's config, or None if the key isn't there."""
        cfg = self._config()
        if cfg is None:
            return None
        found, active = _find_dictation_session(cfg)
        return active if found else None

    # -- dictation ----------------------------------------------------------
    def mic_in_use(self, now: float) -> bool:
        state = self._config_dictating()
        if state is not None:
            return state
        return self._consent_mic_in_use(now)

    def _consent_mic_in_use(self, now: float) -> bool:
        cutoff = int((time.time() + FILETIME_EPOCH_OFFSET) * 10_000_000
                     - 300 * 10_000_000)
        for name in self._wispr_key_names(now):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, MIC_CONSENT_KEY + "\\" + name
                ) as k:
                    start = winreg.QueryValueEx(k, "LastUsedTimeStart")[0]
                    stop = winreg.QueryValueEx(k, "LastUsedTimeStop")[0]
            except OSError:
                continue
            if (stop == 0 or start > stop) and start >= cutoff:
                return True
        return False

    def _wispr_key_names(self, now: float) -> list[str]:
        if now - self._names_at > 5:
            self._names_at = now
            names = set()
            for p in psutil.process_iter(["name", "exe"]):
                if (p.info["name"] or "").lower() == "wispr flow.exe" and p.info["exe"]:
                    names.add(p.info["exe"].replace("\\", "#"))
            self._key_names = sorted(names)
        return self._key_names

    def mute_setting_enabled(self) -> bool:
        """Read Wispr's config (read-only). Keeps the last value on a bad read."""
        cfg = self._config()
        if cfg is None:
            return self._mute_setting
        value = _find_key(cfg, WISPR_SETTING_KEY)
        if value is not None:
            self._mute_setting = bool(value)
        return self._mute_setting


def _find_dictation_session(obj) -> tuple[bool, bool]:
    """Find ``activeDictationSession`` anywhere in Wispr's config.

    Returns (found, active).  found is False when the key is missing
    entirely, which lets the caller fall back to another signal.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "activeDictationSession":
                return True, value is not None
            found, active = _find_dictation_session(value)
            if found:
                return True, active
    elif isinstance(obj, list):
        for value in obj:
            found, active = _find_dictation_session(value)
            if found:
                return True, active
    return False, False


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_key(v, key)
            if found is not None:
                return found
    return None


# --------------------------------------------------------------------------
# Persisted state, so a crash/kill mid-ad can't leave Spotify at volume 0
# (and so what ad breaks look like on this PC survives a restart)
# --------------------------------------------------------------------------
def _read_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError:
        log.exception("could not write state file")


def load_saved_volume() -> Optional[float]:
    v = _read_state().get("saved_volume")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def store_saved_volume(v: Optional[float]) -> None:
    state = _read_state()
    state["saved_volume"] = v
    _write_state(state)


def restore_volume_now() -> str:
    """Put Spotify's volume back from state.json; returns a short message."""
    v = load_saved_volume()
    if v is None:
        return "Nothing to restore."
    if set_spotify_volume(v):
        store_saved_volume(None)
        log.info("Spotify volume restored to %.2f", v)
        return f"Spotify volume restored to {v:.0%}."
    return "Spotify has no audio session; the restore will be retried."


def load_ad_breaks() -> list[dict]:
    """Completed ad breaks, oldest first: {"ads": [seconds, ...], "total": s}."""
    breaks = _read_state().get("ad_breaks")
    if not isinstance(breaks, list):
        return []
    return [b for b in breaks if isinstance(b, dict)][-AD_HISTORY_MAX:]


def store_ad_breaks(breaks: list[dict]) -> None:
    state = _read_state()
    state["ad_breaks"] = breaks[-AD_HISTORY_MAX:]
    _write_state(state)


# --------------------------------------------------------------------------
# Spotify media session (SMTC) + window title
# --------------------------------------------------------------------------
user32 = ctypes.windll.user32


class SpotifyProbe:
    def __init__(self, manager):
        self.manager = manager
        self._pids: set[int] = set()
        self._pids_at = 0.0

    def _spotify_pids(self, now: float) -> set[int]:
        if now - self._pids_at > 3:
            self._pids_at = now
            self._pids = {
                p.pid for p in psutil.process_iter(["name"])
                if (p.info["name"] or "").lower() == "spotify.exe"
            }
        return self._pids

    def window_title(self, now: float) -> str:
        pids, found = self._spotify_pids(now), []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def cb(h, _):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value in pids:
                cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(h, cls, 64)
                n = user32.GetWindowTextLengthW(h)
                if cls.value == "Chrome_WidgetWin_1" and n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(h, buf, n + 1)
                    found.append(buf.value)
            return True

        user32.EnumWindows(cb, 0)
        return found[0] if found else ""

    def session(self):
        for s in self.manager.get_sessions():
            if s.source_app_user_model_id.lower().startswith("spotify"):
                return s
        return None

    async def read(self, now: float):
        s = self.session()
        if s is None:
            return None, None
        try:
            props = await s.try_get_media_properties_async()
            status = int(s.get_playback_info().playback_status)
        except OSError:
            return None, None
        media = Media(props.title or "", props.artist or "", props.album_title or "",
                      status, self.window_title(now))
        return s, media


# --------------------------------------------------------------------------
# Spoken cue (Windows SAPI), played in a quiet voice
# --------------------------------------------------------------------------
CLIP_DIR = os.path.join(HERE, "clips")
CLIPS = {"ad start": "ad_start.wav", "ad start, not muted": "ad_start_not_muted.wav"}


class Toggle:
    """A callable that can be switched off at runtime (tray/settings UI)."""

    def __init__(self, func, enabled: bool = True):
        self.func, self.enabled = func, enabled

    def __call__(self, *args, **kwargs):
        if self.enabled:
            return self.func(*args, **kwargs)
        return None


class Announcer:
    """Plays a pre-generated neural-voice clip (see make_clips.py) at low volume;
    falls back to the built-in SAPI voice if a clip is missing."""

    def __init__(self, volume: int = 15, voice: str = "Zira"):
        self.volume = max(0, min(100, volume))
        self.voice_name = voice  # SAPI fallback only
        self.enabled = True
        self._voice = None

    def __call__(self, text: str) -> None:
        if not self.enabled:
            return
        name = CLIPS.get(text)
        path = os.path.join(CLIP_DIR, name) if name else None
        if path and os.path.isfile(path) and self._play_clip(path):
            return
        self._speak_sapi(text)

    def _scaled_copy(self, path: str) -> str:
        """16-bit PCM clip scaled to the cue volume, cached next to the original."""
        import array, wave
        out = os.path.join(CLIP_DIR, f".v{self.volume}_{os.path.basename(path)}")
        if not os.path.isfile(out) or os.path.getmtime(out) < os.path.getmtime(path):
            with wave.open(path, "rb") as src:
                params, frames = src.getparams(), src.readframes(src.getnframes())
            samples = array.array("h", frames)
            gain = self.volume / 100
            for i, v in enumerate(samples):
                samples[i] = int(v * gain)
            with wave.open(out, "wb") as dst:
                dst.setparams(params)
                dst.writeframes(samples.tobytes())
        return out

    def _play_clip(self, path: str) -> bool:
        try:
            import winsound
            winsound.PlaySound(self._scaled_copy(path),
                               winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except Exception:
            log.exception("could not play cue clip")
            return False

    def _speak_sapi(self, text: str) -> None:
        try:
            if self._voice is None:
                import comtypes.client
                self._voice = comtypes.client.CreateObject("SAPI.SpVoice")
                self._voice.Volume = self.volume
                for v in self._voice.GetVoices():
                    if self.voice_name.lower() in v.GetDescription().lower():
                        self._voice.Voice = v
                        break
            self._voice.Speak(text, 1)  # 1 = SVSFlagsAsync: never blocks the poll loop
        except Exception:
            log.exception("could not speak %r", text)


# --------------------------------------------------------------------------
# Windows notification (a toast), so the ad-break details don't have to be
# spoken at all
# --------------------------------------------------------------------------
AUMID = "Controlify"


def _register_app_id() -> None:
    """Name the toasts "Controlify".

    An unpackaged app has no identity of its own, and Windows labels a toast
    with whatever its AUMID says (or refuses to show it at all if the AUMID is
    unknown to it). This one registry key is what gives it a name.
    """
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                           rf"Software\Classes\AppUserModelId\{AUMID}")
    try:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, AUMID)
    finally:
        winreg.CloseKey(key)


def _toast_notifier():
    from winrt.windows.ui.notifications import ToastNotificationManager

    # pywinrt 3.x exposes the AUMID overload under its own name; 4.x overloads
    # the plain one. Support both, since requirements.txt isn't pinned.
    with_id = getattr(ToastNotificationManager, "create_toast_notifier_with_id", None)
    return (with_id(AUMID) if with_id
            else ToastNotificationManager.create_toast_notifier(AUMID))


def notify(title: str, body: str) -> None:
    """Show a silent Windows toast. Best effort: a notification that fails must
    never take the ad muting down with it."""
    try:
        _register_app_id()
    except OSError:
        # Worth trying to show it anyway; Windows just won't know the name.
        log.exception("could not register the notification app id")
    try:
        from xml.sax.saxutils import escape

        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import ToastNotification

        xml = XmlDocument()
        xml.load_xml(
            '<toast><visual><binding template="ToastGeneric">'
            f"<text>{escape(title)}</text><text>{escape(body)}</text>"
            '</binding></visual><audio silent="true"/></toast>')
        toast = ToastNotification(xml)
        # One ad-break toast at a time: the next break replaces the last one
        # instead of piling up in the notification centre.
        toast.tag, toast.group = "ad-break", "controlify"
        _toast_notifier().show(toast)
    except Exception:
        log.exception("could not show notification")


def fmt_mute(seconds: float) -> str:
    """90 -> "1:30", 45 -> "45s"."""
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s}s"


# --------------------------------------------------------------------------
# Main controller
# --------------------------------------------------------------------------
class Controlify:
    AD_START_TICKS = 2   # consecutive reads before muting (SMTC says ad)
    AD_START_TICKS_WEAK = 3  # same, when only the window title looks like an ad
    RESTORE_AFTER_DICTATION_S = 0.5  # let Wispr restore its own volume first
    AD_END_TICKS = 3     # consecutive "not ad" reads before restoring
    DICTATION_END_S = 0.3
    PAUSE_RETRY_S = 20.0  # keep trying to pause this long after dictation starts
    PAUSE_RETRY_EVERY_S = 1.0  # ...but not more often than this

    def __init__(self, probe, wispr, handle_ads=True, handle_dictation=True,
                 announce=None, pause_needs_setting=False, notify=None):
        self.probe, self.wispr = probe, wispr
        self.announce = announce or (lambda text: None)
        self.notify = notify or (lambda title, body: None)
        self.handle_ads, self.handle_dictation = handle_ads, handle_dictation
        # By default Spotify is paused whenever Wispr holds the mic. Only
        # follow Wispr's own "mute all audio while dictating" switch when
        # pause_needs_setting is set (--pause-needs-wispr-setting).
        self.pause_needs_setting = pause_needs_setting
        self.saved_volume = load_saved_volume()   # non-None => we owe a restore
        self.ad_active = False
        self.ad_breaks = load_ad_breaks()   # completed breaks, for the next prediction
        self._ad_streak = self._clear_streak = 0
        self._ad_strong = False
        self._last_playing_was_ad = False
        self._break_start = 0.0
        self._break_ad_start = 0.0
        self._break_ad_key: Optional[tuple[str, str]] = None
        self._break_next_key: Optional[tuple[str, str]] = None
        self._break_ads: list[float] = []
        self._break_predicted = (DEFAULT_AD_COUNT, DEFAULT_AD_SECONDS,
                                 DEFAULT_AD_COUNT * DEFAULT_AD_SECONDS)
        self._dictation_ended_at = -1e9
        self.dictating = False
        self._dictation_idle_since: Optional[float] = None
        self.paused_by_us = False
        self._pause_pending = self._resume_pending = False
        self._song_streak = 0
        self._paused_at = 0.0
        self._pause_confirmed = False  # we have seen our own pause in the session
        self._last_media = None
        self._pause_wanted = False        # Wispr's setting says Spotify should be paused
        self._pause_deadline = 0.0
        self._last_pause_try = 0.0

    async def tick(self):
        now = time.monotonic()
        session, media = await self.probe.read(now)
        if media and (media.title, media.artist, media.album, media.status, media.window_title) != self._last_media:
            self._last_media = (media.title, media.artist, media.album, media.status, media.window_title)
            log.info("spotify: %r - %r | album=%r status=%s window=%r -> ad=%s",
                     media.artist, media.title, media.album, media.status,
                     media.window_title, SIGNAL_NAMES[ad_signal(media)])
        if self.handle_ads:
            self._update_ad(now, media)
        elif self.ad_active or self.saved_volume is not None:
            # Ads were switched off while one was muted: give the volume back.
            self._stop_ads(now)
        if self.handle_dictation or self.dictating or self.paused_by_us:
            await self._update_dictation(now, session, media)

    # -- ads ---------------------------------------------------------------
    def _update_ad(self, now: float, media: Optional[Media]):
        sig = ad_signal(media) if media is not None else 0
        ad = sig > 0
        if media is not None and media.status == PLAYING:
            self._last_playing_was_ad = ad
        if ad:
            self._ad_strong = self._ad_strong or sig == STRONG
            self._ad_streak += 1
            self._clear_streak = 0
        elif (self.ad_active and self._last_playing_was_ad
              and media is not None and media.status != PLAYING):
            # A paused ad looks like a paused track ("Spotify Free"); keep the
            # mute until something is actually playing again, or the ad would
            # blast for a moment when playback resumes.
            self._ad_streak, self._ad_strong = 0, False
        else:
            self._ad_streak, self._ad_strong = 0, False
            self._clear_streak += 1
        need = self.AD_START_TICKS if self._ad_strong else self.AD_START_TICKS_WEAK

        if self.ad_active:
            if self._clear_streak >= self.AD_END_TICKS or media is None:
                self.ad_active = False
                self._finish_ad_break(now)
                self._maybe_restore(now)
            else:
                self._enforce_mute()
                if ad:
                    # Only ad metadata can mark the next ad: a paused break
                    # reports the paused *track*, which must not count as one.
                    self._track_ad(now, media)
        elif self._ad_streak >= need:
            self.ad_active = True
            if self.saved_volume is None:
                vol = current_spotify_volume()
                # Wispr may have zeroed the session; never remember that as "your" volume.
                self.saved_volume = vol if vol and vol > 0.01 else 1.0
                store_saved_volume(self.saved_volume)
            log.info("ad detected (%s) -> muting Spotify (will restore to %.2f)",
                     "media session" if self._ad_strong else "window title",
                     self.saved_volume)
            self._start_ad_break(now, media)
            self._enforce_mute()
            muted = self._muted_ok()
            if self.dictating:
                log.info("ad start (not spoken: you are dictating)")
            else:
                self.announce("ad start" if muted else "ad start, not muted")
            self.notify(*self._break_notification(muted))
        elif self.saved_volume is not None and not ad:
            # leftover from a crash/kill during an ad, or a deferred restore
            self._maybe_restore(now)

    def _stop_ads(self, now: float):
        """Ad muting was switched off: finish the break and restore the volume."""
        if self.ad_active:
            self.ad_active = False
            self._finish_ad_break(now)
        self._ad_streak = self._clear_streak = 0
        self._ad_strong = False
        if self.saved_volume is not None:
            self._maybe_restore(now)

    # -- one ad break: how many ads, how long each, how long we stay muted ---
    def _start_ad_break(self, now: float, media: Optional[Media]):
        self._break_start = self._break_ad_start = now
        self._break_ads = []
        self._break_ad_key = _ad_key(media) or None
        self._break_next_key = None
        self._break_predicted = predict_ad_break(self.ad_breaks)
        count, each, total = self._break_predicted
        log.info("ad break: predicting %d ad%s of about %.0fs%s "
                 "(Spotify muted for about %.0fs)",
                 count, "" if count == 1 else "s", each,
                 "" if count == 1 else " each", total)

    def _track_ad(self, now: float, media: Optional[Media]):
        """Spotify gives each ad in a break its own metadata, so an artist+title
        change is where one ad ends and the next begins. The change has to be
        seen twice: at a transition the window and the media session disagree
        for a tick, and that must not count as an extra ad.
        """
        key = _ad_key(media)
        if not any(key) or key == self._break_ad_key:
            self._break_next_key = None
            return
        if key != self._break_next_key:
            self._break_next_key = key
            return
        self._break_next_key = None
        if now - self._break_ad_start >= MIN_AD_S:
            self._break_ads.append(now - self._break_ad_start)
            self._break_ad_start = now
            log.info("ad break: ad %d started (the last one ran %.0fs)",
                     len(self._break_ads) + 1, self._break_ads[-1])
        self._break_ad_key = key

    def _finish_ad_break(self, now: float):
        if self._break_ad_key is not None and now - self._break_ad_start >= MIN_AD_S:
            self._break_ads.append(now - self._break_ad_start)
        ads, total = self._break_ads, now - self._break_start
        self._break_ads, self._break_ad_key, self._break_next_key = [], None, None
        if not ads or total < MIN_BREAK_S:
            return
        self.ad_breaks = (self.ad_breaks + [{
            "ads": [round(a, 1) for a in ads], "total": round(total, 1),
        }])[-AD_HISTORY_MAX:]
        store_ad_breaks(self.ad_breaks)
        log.info("ad break over after %.0fs: %d ad%s (%s)", total, len(ads),
                 "" if len(ads) == 1 else "s", ", ".join(f"{a:.0f}s" for a in ads))

    def _break_notification(self, muted: bool) -> tuple[str, str]:
        """Title + body for the toast: how many ads, how long each, how long
        the mute lasts. The count and lengths are the learned prediction."""
        count, each, total = self._break_predicted
        ads = (f"{count} ad{'' if count == 1 else 's'}, "
               f"about {each:.0f}s{'' if count == 1 else ' each'}")
        if not muted:
            return "Ads playing - not muted", ads
        return f"Ads muted for about {fmt_mute(total)}", ads

    def _maybe_restore(self, now: float):
        # Wispr zeroes Spotify while dictating and restores its own saved value
        # afterwards; restoring first would be overwritten, so wait it out.
        if self.dictating or now - self._dictation_ended_at < self.RESTORE_AFTER_DICTATION_S:
            return
        self._restore_volume()

    def _muted_ok(self) -> bool:
        cur = current_spotify_volume()
        return cur is not None and cur <= 0.001

    def _enforce_mute(self):
        cur = current_spotify_volume()
        if cur is not None and cur > 0.001:
            set_spotify_volume(0.0)

    def _restore_volume(self):
        if self.saved_volume is None:
            return
        n = set_spotify_volume(self.saved_volume)
        if n:
            log.info("ad over -> Spotify volume restored to %.2f", self.saved_volume)
            self.saved_volume = None
            store_saved_volume(None)
        # n == 0: Spotify has no audio session right now; keep owing the restore.

    # -- dictation ---------------------------------------------------------
    async def _update_dictation(self, now, session, media):
        if not self.handle_dictation:
            # Switched off mid-dictation: stop trying to pause, but still
            # resume anything we paused before the switch.
            self._pause_wanted = self._pause_pending = False
        mic = self.wispr.mic_in_use(now)
        if self.paused_by_us and media and media.status == PAUSED:
            # Our own pause is now visible in the media session. Only from
            # here on does a PLAYING status mean the user pressed play.
            self._pause_confirmed = True
        if (self.paused_by_us and self._pause_confirmed and media
                and media.status == PLAYING):
            # You pressed play yourself: from here on playback is yours, so
            # never auto-resume (even if you pause again later).
            self.paused_by_us = False
            self._pause_confirmed = False
            self._pause_wanted = False     # and never pause it for you either
            log.info("Spotify resumed by you during dictation; leaving playback alone")

        if mic:
            self._dictation_idle_since = None
            if not self.dictating:
                self.dictating = True
                await self._on_dictation_start(now, session, media)
            elif self._pause_pending:
                await self._pause_when_ad_over(now, session, media)
            elif (self._pause_wanted and not self.paused_by_us
                    and media is not None and media.status == PLAYING
                    and now < self._pause_deadline
                    and now - self._last_pause_try > self.PAUSE_RETRY_EVERY_S):
                # Wispr's setting says pause, but Spotify is still playing: the
                # first attempt was refused or missed. Keep trying, because
                # pausing an already-paused player is a no-op, so a retry can
                # never un-pause anything.
                self._last_pause_try = now
                await self._pause(now, session, media)
        elif self.dictating:
            if self._dictation_idle_since is None:
                self._dictation_idle_since = now
            if now - self._dictation_idle_since >= self.DICTATION_END_S:
                self.dictating = False
                self._dictation_ended_at = now
                self._pause_pending = False
                self._pause_wanted = False
                self._resume_pending = self.paused_by_us
                log.info("dictation ended")

        if self._resume_pending and not self.dictating:
            await self._resume_after_dictation(now, session, media)

    async def _on_dictation_start(self, now, session, media):
        enabled = self.wispr.mute_setting_enabled()
        warning = mic_role_warning()
        if warning:
            log.info(warning)
        if self.pause_needs_setting and not enabled:
            log.info("dictation started (no pause: Wispr's "
                     "'mute all audio while dictating' is off)")
        elif self.ad_active or (media is not None and is_ad(media)):
            self._pause_pending, self._song_streak = True, 0
            log.info("dictation started during an ad -> not pausing; "
                     "will pause as soon as the ad ends")
        else:
            self._pause_wanted, self._pause_deadline = True, now + self.PAUSE_RETRY_S
            if media is not None and media.status != PLAYING:
                log.info("dictation started (Spotify isn't playing yet)")
            self._last_pause_try = now
            await self._pause(now, session, media)

    async def _pause_when_ad_over(self, now, session, media):
        """Dictation began during an ad: pause the moment a real track starts."""
        real = media is not None and media.status == PLAYING and not is_ad(media)
        self._song_streak = self._song_streak + 1 if real else 0
        if self._song_streak >= 2:
            self._pause_pending = False
            await self._pause(now, session, media)

    async def _pause(self, now, session, media=None):
        """Pause Spotify, but only if it is actually playing right now."""
        if session is None or (media is not None and media.status != PLAYING):
            return
        self.paused_by_us = bool(await session.try_pause_async())
        self._paused_at = now
        self._pause_confirmed = False
        log.info("paused Spotify for dictation (ok=%s)", self.paused_by_us)

    async def _resume_after_dictation(self, now, session, media):
        if not self.paused_by_us:           # you took over playback
            self._resume_pending = False
            return
        # If an ad was muted during dictation, wait for the volume to come back
        # first so the song doesn't start silent (give up waiting after 3s).
        if self.saved_volume is not None and now - self._dictation_ended_at < 3.0:
            return
        self._resume_pending = self.paused_by_us = False
        if session is None:
            return
        if media is not None and media.status == PLAYING and self._pause_confirmed:
            # We saw our own pause land and it plays again: you restarted it.
            log.info("Spotify was changed by you; leaving it alone")
            return
        # The session can still report the old status for a moment after our
        # pause, so play anyway: resuming something that is already playing is
        # a no-op, while skipping it would leave your music stuck.
        await session.try_play_async()
        log.info("resumed Spotify")

    def shutdown(self):
        if self.saved_volume is not None:
            self._restore_volume()


# --------------------------------------------------------------------------
async def run(args):
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
    )

    import ui  # lazy: the tray/tkinter are optional and must not break detection

    settings = ui.Settings()
    # Command-line flags are per-run overrides; the settings file stays the
    # persistent source of truth (and is what the tray/window edits).
    if args.no_ads is not None:
        settings.override(mute_ads=not args.no_ads)
    if args.no_pause is not None:
        settings.override(pause_dictation=not args.no_pause)
    if args.pause_needs_wispr_setting is not None:
        settings.override(pause_needs_wispr_setting=args.pause_needs_wispr_setting)
    if args.no_announce is not None:
        settings.override(announce=not args.no_announce)
    if args.no_notify is not None:
        settings.override(notify=not args.no_notify)
    if args.announce_volume is not None:
        settings.override(announce_volume=args.announce_volume)
    if args.announce_voice is not None:
        settings.override(announce_voice=args.announce_voice)

    announcer = Announcer(settings.get("announce_volume"), settings.get("announce_voice"))
    announcer.enabled = settings.get("announce")
    notifier = Toggle(notify, enabled=settings.get("notify"))

    mgr = await Manager.request_async()
    app = Controlify(SpotifyProbe(mgr), WisprWatcher(args.wispr_config),
                     handle_ads=settings.get("mute_ads"),
                     handle_dictation=settings.get("pause_dictation"),
                     announce=announcer,
                     pause_needs_setting=settings.get("pause_needs_wispr_setting"),
                     notify=notifier)
    controller = ui.UIController(settings, app=app, announcer=announcer,
                                 notifier=notifier, on_restore=restore_volume_now)
    controller.apply()

    stop = threading.Event()
    tray = None
    if not args.no_tray:
        tray = ui.Tray(controller, quit_event=stop)
        if not tray.start():
            tray = None

    signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    log.info("Controlify running (ads=%s, dictation-pause=%s%s)",
             settings.get("mute_ads"), settings.get("pause_dictation"),
             " [only when Wispr's mute setting is on]"
             if settings.get("pause_needs_wispr_setting") else "")
    gone_since = None
    last_settings_check = 0.0
    try:
        while not stop.is_set():
            try:
                await app.tick()
            except Exception:
                log.exception("tick failed")
            now = time.monotonic()
            if now - last_settings_check > 2.0:
                # Pick up edits from `--settings` or a hand-edited settings.json.
                last_settings_check = now
                if settings.reload_if_changed():
                    controller.apply()
            if args.exit_with_spotify:
                if app.probe._spotify_pids(now):
                    gone_since = None
                elif gone_since is None:
                    gone_since = now
                elif now - gone_since > 5:
                    log.info("Spotify closed -> exiting")
                    break
            await asyncio.sleep(args.poll)
    finally:
        if tray is not None:
            tray.stop()
        app.shutdown()
        if stop.is_set() and args.exit_with_spotify:
            # Tray Quit in the watcher setup: stop the supervisors too, or the
            # watcher would restart Controlify in a few seconds.
            stop_supervisors()
        log.info("Controlify stopped")


class AppendFileHandler(logging.Handler):
    """Appends to the log file, rotating it when it gets too big.

    RotatingFileHandler keeps its own file offset, so with three processes
    (keeper + watcher + controlify) writing to the same file they overwrite
    each other's lines and the log ends up out of order. Opening the file for
    append on every record keeps it readable no matter how many writers there
    are.
    """

    def __init__(self, path: str, max_bytes: int = 1_000_000, backups: int = 2):
        super().__init__()
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups

    def emit(self, record):
        try:
            self._rotate()
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(self.format(record) + "\n")
        except Exception:
            self.handleError(record)

    def _rotate(self):
        try:
            if not os.path.exists(self.path) or os.path.getsize(self.path) < self.max_bytes:
                return
            for i in range(self.backups - 1, 0, -1):
                src, dst = f"{self.path}.{i}", f"{self.path}.{i + 1}"
                if os.path.exists(src):
                    os.replace(src, dst)
            os.replace(self.path, f"{self.path}.1")
        except OSError:
            pass


def setup_logging(verbose: bool):
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
    fh = AppendFileHandler(LOG_FILE)
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if sys.stdout is not None:  # pythonw has no console
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)


def _mutex_taken(name: str) -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, name)
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def already_running() -> bool:
    return _mutex_taken("Local\\Controlify.SingleInstance")


def spotify_running() -> bool:
    return any((p.info["name"] or "").lower() == "spotify.exe"
               for p in psutil.process_iter(["name"]))


def _has_controlify(*flags: str) -> bool:
    """True if a controlify.py process was started with all of these flags."""
    for p in psutil.process_iter(["cmdline"]):
        cmd = p.info["cmdline"] or []
        if all(f in cmd for f in flags) and any(
                os.path.normcase(a).endswith("controlify.py") for a in cmd):
            return True
    return False


def controlify_running() -> bool:
    """True if a Controlify instance is already alive (keeper/watcher don't count)."""
    return _has_controlify("--exit-with-spotify")


def watcher_running() -> bool:
    """True if a watcher is already alive (the keeper doesn't count)."""
    return _has_controlify("--watch")


def stop_supervisors() -> None:
    """Stop the watcher and keeper after a tray Quit.

    Without this the watcher would simply start Controlify again a few seconds
    later, so "Quit Controlify" would look broken in the autostart setup.  The
    scheduled task is left enabled: it starts the stack again at the next logon,
    while stop.bat is the "stop and stay stopped" option.
    """
    keepers, watchers = [], []
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
            if not any(os.path.normcase(a).endswith("controlify.py") for a in cmd):
                continue
            if "--keep-alive" in cmd:
                keepers.append(p)
            elif "--watch" in cmd:
                watchers.append(p)
        except (psutil.Error, OSError):
            continue
    # Kill the keeper first: it restarts a missing watcher after ~5s.
    for p in keepers + watchers:
        try:
            p.terminate()
        except (psutil.Error, OSError):
            pass
    if keepers or watchers:
        log.info("stopped keeper/watcher (%d/%d) at the tray's request",
                 len(keepers), len(watchers))


def watch() -> None:
    """Tiny launcher: start Controlify when Spotify opens. Controlify exits by
    itself when Spotify closes, so nothing heavy stays loaded in between.

    This is the only thing keeping ad muting alive, so it is deliberately hard
    to kill by accident: every iteration is guarded, so a transient failure
    (a process list that can't be read, a Popen that fails) is logged and
    retried instead of taking the watcher down for the rest of the session.
    """
    import subprocess

    if _mutex_taken("Local\\Controlify.Watcher"):
        log.info("watcher already running; exiting")
        return
    HEARTBEAT_S = 300
    child, last_start = None, 0.0
    last_beat, orphan_logged = time.monotonic(), False
    log.info("watcher started (idle until Spotify opens)")
    try:
        while True:
            try:
                if child is not None and child.poll() is not None:
                    # A non-zero code means Controlify crashed; a "watcher
                    # stopped" line below without one here means this process
                    # was killed from outside.
                    log.info("Controlify exited (code=%s)", child.returncode)
                    child = None
                if (child is None and time.monotonic() - last_start > 10
                        and spotify_running()):
                    last_start = time.monotonic()   # rate-limit the rescan below
                    if controlify_running():
                        # A previous watcher's Controlify outlived it; don't
                        # pile up no-op restarts behind it.
                        if not orphan_logged:
                            log.info("Controlify is already running; leaving it alone")
                            orphan_logged = True
                    else:
                        orphan_logged = False
                        log.info("Spotify is open -> starting Controlify")
                        child = subprocess.Popen(
                            [sys.executable, os.path.abspath(__file__), "--exit-with-spotify"],
                            creationflags=0x08000000, cwd=HERE)  # CREATE_NO_WINDOW
                now = time.monotonic()
                if now - last_beat > HEARTBEAT_S:
                    last_beat = now
                    log.info("watcher alive (spotify=%s, controlify=%s)",
                             spotify_running(),
                             "running" if controlify_running() else "stopped")
            except Exception:
                log.exception("watcher iteration failed; retrying")
            time.sleep(2)
    finally:
        log.info("watcher stopped")


def keep_alive() -> None:
    """Outer supervisor: keep a watcher alive. Autostart runs this, so losing
    the watcher (a crash, a stray "End task", a sign-out) only costs the few
    seconds it takes to notice and start a new one."""
    import subprocess

    if _mutex_taken("Local\\Controlify.KeepAlive"):
        log.info("keeper already running; exiting")
        return
    child, last_start = None, 0.0
    adopted_logged = False
    log.info("keeper started (supervises the watcher)")
    try:
        while True:
            try:
                if child is not None and child.poll() is not None:
                    log.info("watcher exited (code=%s)", child.returncode)
                    child = None
                if child is None and time.monotonic() - last_start > 5:
                    last_start = time.monotonic()   # rate-limit the rescan below
                    if watcher_running():
                        # A watcher we didn't start is alive (we were restarted,
                        # or one outlived the previous keeper). Don't fight it.
                        if not adopted_logged:
                            log.info("a watcher is already running; leaving it alone")
                            adopted_logged = True
                    else:
                        adopted_logged = False
                        child = subprocess.Popen(
                            [sys.executable, os.path.abspath(__file__), "--watch"],
                            creationflags=0x08000000, cwd=HERE)  # CREATE_NO_WINDOW
            except Exception:
                log.exception("keeper iteration failed; retrying")
            time.sleep(2)
    finally:
        log.info("keeper stopped")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    # None means "not given": the saved setting is used.  Passing the flag
    # overrides it for this run only.
    ap.add_argument("--no-ads", action="store_true", default=None,
                    help="disable ad muting")
    ap.add_argument("--no-pause", action="store_true", default=None,
                    help="disable pause-while-dictating")
    ap.add_argument("--pause-needs-wispr-setting", action="store_true", default=None,
                    help="only pause Spotify while dictating if Wispr Flow's "
                         "'mute all audio while dictating' is on (default: "
                         "pause on any dictation)")
    ap.add_argument("--no-announce", action="store_true", default=None,
                    help="don't say \"ad start\" when an ad is muted")
    ap.add_argument("--no-notify", action="store_true", default=None,
                    help="don't show a Windows notification with how many ads "
                         "the break has and how long Spotify stays muted")
    ap.add_argument("--announce-volume", type=int, default=None,
                    help="volume of the spoken cue, 0-100 (default 15)")
    ap.add_argument("--announce-voice", default=None,
                    help="part of an installed voice name, e.g. Zira or David (default Zira)")
    ap.add_argument("--no-tray", action="store_true",
                    help="don't show the system tray icon")
    ap.add_argument("--settings", action="store_true",
                    help="open the settings window and exit")
    ap.add_argument("--version", action="version",
                    version=f"Controlify {__version__}")
    ap.add_argument("--poll", type=float, default=0.15, help="poll interval in seconds")
    ap.add_argument("--wispr-config", default=WISPR_CONFIG)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--watch", action="store_true",
                    help="idle until Spotify opens, then run Controlify (until it closes)")
    ap.add_argument("--keep-alive", action="store_true",
                    help="supervise the watcher, restarting it if it dies")
    ap.add_argument("--exit-with-spotify", action="store_true",
                    help="exit once Spotify has been closed for 5s")
    ap.add_argument("--restore", action="store_true",
                    help="restore Spotify's volume from state.json and exit")
    ap.add_argument("--fix-default-mic", action="store_true",
                    help="point every Windows mic role at the same device, so "
                         "dictation can't open a Bluetooth headset's mic and "
                         "drop your music to hands-free quality")
    args = ap.parse_args()
    setup_logging(args.verbose)
    if args.settings:
        try:
            import ui
            ui.run_settings()
        except Exception:
            log.exception("could not open the settings window")
        return
    if args.fix_default_mic:
        log.info("default mic for all roles: %s", align_default_mic())
        return
    if args.restore:
        log.info(restore_volume_now())
        return
    if args.keep_alive:
        try:
            keep_alive()
        except KeyboardInterrupt:
            pass
        return
    if args.watch:
        try:
            watch()
        except KeyboardInterrupt:
            pass
        return
    if already_running():
        log.info("Controlify is already running; exiting")
        return
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
