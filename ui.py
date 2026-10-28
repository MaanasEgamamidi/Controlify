"""Optional system tray icon and settings window.

This module is imported lazily by ``controlify.py``, so a missing GUI
dependency (or a run with ``--no-tray``) never affects ad muting or the
dictation pause.  Settings live in ``settings.json`` next to the script.

The tray is deliberately thin: every control changes a value in
:class:`Settings`, then :class:`UIController` copies the values onto the live
``Controlify`` object.  The detection code itself knows nothing about the UI.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading

log = logging.getLogger("controlify")

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "settings.json")
ICON_FILE = os.path.join(HERE, "assets", "controlify.ico")

# These defaults are exactly the old command-line defaults, so an existing
# install behaves the same until the user changes something in the UI.
DEFAULTS = {
    "mute_ads": True,
    "pause_dictation": True,
    "pause_needs_wispr_setting": False,
    "announce": True,
    "announce_volume": 15,
    "announce_voice": "Zira",
    "notify": True,
}


def _core_module():
    """The running controlify module, whether it was imported or run as a script."""
    main = sys.modules.get("__main__")
    if main is not None and getattr(main, "__file__", "").endswith("controlify.py"):
        return main
    import controlify
    return controlify


def _clean(key: str, value):
    """Coerce one settings value to the type/shape the app expects."""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if key == "announce_volume":
        try:
            return max(0, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            return default
    if isinstance(default, str):
        text = str(value).strip()
        return text or default
    return value


class Settings:
    """``settings.json`` with validation, atomic writes, and change polling."""

    def __init__(self, path: str = SETTINGS_FILE):
        self.path = path
        self._lock = threading.RLock()
        self._values = dict(DEFAULTS)
        self._overrides: dict = {}
        self._mtime: int | None = None
        self.reload()

    # -- reading -----------------------------------------------------------
    def get(self, key: str):
        with self._lock:
            return self._values[key]

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._values)

    def _file_mtime(self) -> int | None:
        try:
            return os.stat(self.path).st_mtime_ns
        except OSError:
            return None

    def reload(self) -> bool:
        """Read the file, keeping the current values if it is missing/broken."""
        mtime = self._file_mtime()
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            with self._lock:
                self._mtime = mtime
            return False
        if not isinstance(data, dict):
            with self._lock:
                self._mtime = mtime
            return False
        with self._lock:
            for key in DEFAULTS:
                if key in data:
                    self._values[key] = _clean(key, data[key])
            # Command-line flags stay in effect even if another process edits
            # the file while this one runs.
            self._values.update(self._overrides)
            self._mtime = mtime
        return True

    def reload_if_changed(self) -> bool:
        """True when the file changed since the last read (e.g. another window)."""
        if self._file_mtime() == self._mtime:
            return False
        return self.reload()

    # -- writing -----------------------------------------------------------
    def update(self, **values) -> None:
        """Validate and persist any known keys; unknown keys are ignored."""
        with self._lock:
            for key, value in values.items():
                if key in DEFAULTS:
                    self._values[key] = _clean(key, value)
                    # An explicit change from the UI wins over a command-line
                    # override for the rest of this run.
                    self._overrides.pop(key, None)
            data = dict(self._values)
        self._save(data)

    def override(self, **values) -> None:
        """Change values for this run only (command-line flags), without saving."""
        with self._lock:
            for key, value in values.items():
                if key in DEFAULTS:
                    value = _clean(key, value)
                    self._values[key] = value
                    self._overrides[key] = value

    def _save(self, data: dict) -> None:
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.path)
            with self._lock:
                self._mtime = self._file_mtime()
        except OSError:
            log.exception("could not write settings file %s", self.path)


class UIController:
    """Copies :class:`Settings` onto the live app and owns the settings window."""

    def __init__(self, settings: Settings, app=None, announcer=None,
                 notifier=None, on_restore=None):
        self.settings = settings
        self.app = app
        self.announcer = announcer
        self.notifier = notifier
        self.on_restore = on_restore
        self._window_lock = threading.Lock()
        self._window_open = False

    # -- live state --------------------------------------------------------
    def apply(self) -> None:
        s = self.settings
        if self.app is not None:
            self.app.handle_ads = s.get("mute_ads")
            self.app.handle_dictation = s.get("pause_dictation")
            self.app.pause_needs_setting = s.get("pause_needs_wispr_setting")
        if self.announcer is not None:
            self.announcer.enabled = s.get("announce")
            self.announcer.volume = s.get("announce_volume")
            self.announcer.voice_name = s.get("announce_voice")
        if self.notifier is not None:
            self.notifier.enabled = s.get("notify")

    def update(self, values: dict) -> None:
        self.settings.update(**values)
        self.apply()

    def set(self, key: str, value) -> None:
        self.update({key: value})

    def toggle(self, key: str) -> None:
        self.update({key: not self.settings.get(key)})

    # -- actions -----------------------------------------------------------
    def status_text(self) -> str:
        app = self.app
        if app is not None:
            if getattr(app, "ad_active", False):
                return "Muting an ad"
            if getattr(app, "dictating", False):
                return ("Dictating - Spotify paused" if getattr(app, "paused_by_us", False)
                        else "Dictating")
            if getattr(app, "saved_volume", None) is not None:
                return "Restoring Spotify volume"
            return "Watching Spotify"
        try:
            core = _core_module()
            bits = ["Spotify running" if core.spotify_running() else "Spotify not running"]
            bits.append("Controlify running" if core.controlify_running()
                        else "Controlify not running")
            return " - ".join(bits)
        except Exception:
            return "Idle"

    def restore_volume(self) -> str:
        try:
            if self.on_restore is not None:
                return self.on_restore()
            return _core_module().restore_volume_now()
        except Exception:
            log.exception("could not restore Spotify volume")
            return "Could not restore the volume; see controlify.log."

    def open_log(self) -> str:
        try:
            path = _core_module().LOG_FILE
        except Exception:
            path = os.path.join(HERE, "controlify.log")
        if not os.path.isfile(path):
            return "No log file yet."
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return "Opened the log."
        except OSError:
            log.exception("could not open the log")
            return "Could not open the log; see controlify.log."

    # -- settings window ---------------------------------------------------
    def open_settings_window(self) -> None:
        with self._window_lock:
            if self._window_open:
                return
            self._window_open = True
        try:
            _SettingsWindow(self).run()
        except Exception:
            log.exception("settings window failed")
        finally:
            with self._window_lock:
                self._window_open = False


class _SettingsWindow:
    """A small tkinter window; tkinter is stdlib, so this adds no dependency."""

    def __init__(self, controller: UIController):
        self.c = controller
        self.root = None
        self.status = None
        self.volume = None
        self.voice = None
        self.vars = {}

    def run(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        s = self.c.settings
        root = tk.Tk()
        self.root = root
        root.title("Controlify settings")
        root.resizable(False, False)
        if os.path.isfile(ICON_FILE):
            try:
                root.iconbitmap(default=ICON_FILE)
                root.iconbitmap(ICON_FILE)
            except tk.TclError:
                pass

        style = ttk.Style(root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        frame = ttk.Frame(root, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Controlify", font=("Segoe UI", 15, "bold")).grid(
            row=0, column=0, sticky="w")
        ttk.Label(frame, text="Quiet Spotify ads and step aside while you dictate.",
                  foreground="#555").grid(row=1, column=0, sticky="w", pady=(2, 14))

        # -- behaviour ------------------------------------------------------
        ttk.Label(frame, text="Behaviour", font=("Segoe UI", 10, "bold")).grid(
            row=2, column=0, sticky="w", pady=(0, 4))
        self.vars = {
            "mute_ads": tk.BooleanVar(value=bool(s.get("mute_ads"))),
            "pause_dictation": tk.BooleanVar(value=bool(s.get("pause_dictation"))),
            "pause_needs_wispr_setting": tk.BooleanVar(
                value=bool(s.get("pause_needs_wispr_setting"))),
        }
        self._check(frame, "Mute Spotify ads", "mute_ads", 3)
        self._check(frame, "Pause Spotify while Wispr Flow dictates",
                    "pause_dictation", 4)
        self._check(frame, "  Only when Wispr's \"mute all audio\" is on",
                    "pause_needs_wispr_setting", 5, padx=22)

        # -- cues -----------------------------------------------------------
        ttk.Separator(frame, orient="horizontal").grid(
            row=6, column=0, sticky="ew", pady=12)
        ttk.Label(frame, text="Cues", font=("Segoe UI", 10, "bold")).grid(
            row=7, column=0, sticky="w", pady=(0, 4))
        self.vars["announce"] = tk.BooleanVar(value=bool(s.get("announce")))
        self.vars["notify"] = tk.BooleanVar(value=bool(s.get("notify")))
        self._check(frame, "Speak \"ad start\" quietly", "announce", 8)
        self._check(frame, "Show a Windows notification with the break estimate",
                    "notify", 9)

        row = ttk.Frame(frame)
        row.grid(row=10, column=0, sticky="w", pady=(8, 0))
        ttk.Label(row, text="Cue volume").pack(side="left")
        self.volume = tk.IntVar(value=int(s.get("announce_volume")))
        ttk.Spinbox(row, from_=0, to=100, increment=5, width=5,
                    textvariable=self.volume).pack(side="left", padx=(8, 4))
        ttk.Label(row, text="%").pack(side="left")

        row = ttk.Frame(frame)
        row.grid(row=11, column=0, sticky="w", pady=(6, 0))
        ttk.Label(row, text="Fallback voice").pack(side="left")
        self.voice = tk.StringVar(value=str(s.get("announce_voice")))
        ttk.Entry(row, textvariable=self.voice, width=18).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="Used only if the bundled neural cue clips are missing.",
                  foreground="#777").grid(row=12, column=0, sticky="w", pady=(2, 0))

        # -- status / actions ----------------------------------------------
        ttk.Separator(frame, orient="horizontal").grid(
            row=13, column=0, sticky="ew", pady=12)
        self.status = tk.StringVar(value=self.c.status_text())
        ttk.Label(frame, textvariable=self.status, foreground="#555").grid(
            row=14, column=0, sticky="w")

        actions = ttk.Frame(frame)
        actions.grid(row=15, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Restore Spotify volume",
                   command=self._restore).pack(side="left")
        ttk.Button(actions, text="Open log", command=self._open_log).pack(
            side="left", padx=(8, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=16, column=0, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Save", command=self._save).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=root.destroy).pack(
            side="left", padx=(8, 0))
        root.bind("<Escape>", lambda _e: root.destroy())

        self._sync_pause_options()
        self.vars["pause_dictation"].trace_add(
            "write", lambda *_a: self._sync_pause_options())

        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        x = max(0, (root.winfo_screenwidth() - w) // 2)
        y = max(0, (root.winfo_screenheight() - h) // 2)
        root.geometry(f"+{x}+{y}")
        self._tick_status()
        root.mainloop()

    # -- widgets -----------------------------------------------------------
    def _check(self, parent, text, key, row, padx=0):
        from tkinter import ttk
        cb = ttk.Checkbutton(parent, text=text, variable=self.vars[key])
        cb.grid(row=row, column=0, sticky="w", padx=padx, pady=1)
        if key == "pause_needs_wispr_setting":
            self._only_when = cb
        return cb

    def _sync_pause_options(self):
        if not hasattr(self, "_only_when"):
            return
        enabled = self.vars["pause_dictation"].get()
        self._only_when.configure(state="normal" if enabled else "disabled")

    def _tick_status(self):
        if self.root is None:
            return
        try:
            self.status.set(self.c.status_text())
            self.root.after(1000, self._tick_status)
        except Exception:
            pass

    # -- buttons -----------------------------------------------------------
    def _save(self):
        try:
            volume = int(self.volume.get())
        except Exception:
            volume = DEFAULTS["announce_volume"]
        self.c.update({
            "mute_ads": self.vars["mute_ads"].get(),
            "pause_dictation": self.vars["pause_dictation"].get(),
            "pause_needs_wispr_setting": self.vars["pause_needs_wispr_setting"].get(),
            "announce": self.vars["announce"].get(),
            "notify": self.vars["notify"].get(),
            "announce_volume": volume,
            "announce_voice": self.voice.get().strip() or DEFAULTS["announce_voice"],
        })
        self.root.destroy()

    def _restore(self):
        self.status.set(self.c.restore_volume())

    def _open_log(self):
        self.status.set(self.c.open_log())


class Tray:
    """pystray wrapper; importing pystray/Pillow happens in :meth:`start`."""

    def __init__(self, controller: UIController, quit_event=None):
        self.controller = controller
        self.quit_event = quit_event or threading.Event()
        self._icon = None
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> bool:
        try:
            import pystray
            from pystray import Menu, MenuItem
        except Exception:
            log.warning("tray unavailable: install pystray and Pillow "
                        "(setup.bat installs them); continuing without a tray icon")
            return False

        try:
            image = _icon_image()
            c = self.controller
            menu = Menu(
                MenuItem(lambda item: f"Controlify - {c.status_text()}", None,
                         enabled=False),
                Menu.SEPARATOR,
                MenuItem("Mute Spotify ads", self._toggle("mute_ads"),
                         checked=self._checked("mute_ads")),
                MenuItem("Pause Spotify while dictating", self._toggle("pause_dictation"),
                         checked=self._checked("pause_dictation")),
                MenuItem("  Only when Wispr's mute setting is on",
                         self._toggle("pause_needs_wispr_setting"),
                         checked=self._checked("pause_needs_wispr_setting"),
                         enabled=lambda item: bool(c.settings.get("pause_dictation"))),
                Menu.SEPARATOR,
                MenuItem("Speak the ad cue", self._toggle("announce"),
                         checked=self._checked("announce")),
                MenuItem("Show ad-break notification", self._toggle("notify"),
                         checked=self._checked("notify")),
                Menu.SEPARATOR,
                MenuItem("Settings...", self._open_settings, default=True),
                MenuItem("Restore Spotify volume", self._restore),
                MenuItem("Open log", self._open_log),
                Menu.SEPARATOR,
                MenuItem("Quit Controlify", self._quit),
            )
            self._icon = pystray.Icon("Controlify", image, "Controlify", menu)
            self._icon.run_detached()
        except Exception:
            log.exception("could not start the tray icon")
            self._icon = None
            return False
        self._thread = threading.Thread(target=self._refresh_title, daemon=True)
        self._thread.start()
        log.info("tray icon started")
        return True

    def stop(self) -> None:
        self._stop.set()
        icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass

    # -- menu callbacks ----------------------------------------------------
    def _checked(self, key):
        return lambda item: bool(self.controller.settings.get(key))

    def _toggle(self, key):
        def action(icon, item):
            self.controller.toggle(key)
            try:
                icon.update_menu()
            except Exception:
                pass
        return action

    def _open_settings(self, icon=None, item=None):
        threading.Thread(target=self.controller.open_settings_window, daemon=True).start()

    def _restore(self, icon=None, item=None):
        self.controller.restore_volume()

    def _open_log(self, icon=None, item=None):
        self.controller.open_log()

    def _quit(self, icon=None, item=None):
        self.quit_event.set()
        self.stop()

    def _refresh_title(self):
        while not self._stop.wait(2.0):
            icon = self._icon
            if icon is None:
                continue
            try:
                icon.title = f"Controlify - {self.controller.status_text()}"
            except Exception:
                pass


def _icon_image():
    """Build the tray image, preferring the bundled PNG."""
    from PIL import Image

    png = os.path.join(HERE, "assets", "controlify.png")
    if os.path.isfile(png):
        with Image.open(png) as source:
            return source.convert("RGBA")
    # Minimal fallback: a blue disc with a white dot, so the tray still works
    # if the asset is missing.
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    from PIL import ImageDraw
    d = ImageDraw.Draw(image)
    d.ellipse((4, 4, 60, 60), fill=(59, 130, 246, 255))
    d.ellipse((26, 26, 38, 38), fill=(255, 255, 255, 255))
    return image


def run_settings() -> None:
    """Standalone entry point for ``controlify.py --settings``."""
    settings = Settings()
    controller = UIController(settings)
    controller.open_settings_window()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    run_settings()
