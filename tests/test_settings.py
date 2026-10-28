"""Settings persistence and live UI wiring (no tkinter/pystray needed)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ui


def test_defaults_match_the_old_command_line():
    settings = ui.Settings(os.path.join(os.path.dirname(__file__), "no-such.json"))
    assert settings.snapshot() == ui.DEFAULTS


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    first = ui.Settings(str(path))
    first.update(mute_ads=False, announce_volume=40)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["mute_ads"] is False
    assert saved["announce_volume"] == 40

    second = ui.Settings(str(path))
    assert second.get("mute_ads") is False
    assert second.get("announce_volume") == 40


def test_invalid_values_are_sanitized(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "mute_ads": 0,
        "announce_volume": 999,
        "announce_voice": "   ",
        "unknown": "ignored",
    }), encoding="utf-8")

    settings = ui.Settings(str(path))
    assert settings.get("mute_ads") is False
    assert settings.get("announce_volume") == 100
    assert settings.get("announce_voice") == "Zira"
    assert "unknown" not in settings.snapshot()


def test_reload_if_changed(tmp_path):
    path = tmp_path / "settings.json"
    settings = ui.Settings(str(path))
    assert not settings.reload_if_changed()

    path.write_text(json.dumps({"mute_ads": False}), encoding="utf-8")
    assert settings.reload_if_changed()
    assert settings.get("mute_ads") is False


def test_overrides_do_not_touch_the_file(tmp_path):
    path = tmp_path / "settings.json"
    settings = ui.Settings(str(path))
    settings.override(mute_ads=False)
    assert settings.get("mute_ads") is False
    assert not path.exists()


def test_override_survives_a_reload(tmp_path):
    path = tmp_path / "settings.json"
    settings = ui.Settings(str(path))
    settings.override(mute_ads=False)

    path.write_text(json.dumps({"mute_ads": True, "notify": False}),
                    encoding="utf-8")
    settings.reload()

    assert settings.get("mute_ads") is False   # command-line override still wins
    assert settings.get("notify") is False     # other file values still load


class FakeApp:
    handle_ads = True
    handle_dictation = True
    pause_needs_setting = False
    ad_active = False
    dictating = False
    paused_by_us = False
    saved_volume = None


class FakeCue:
    enabled = True
    volume = 15
    voice_name = "Zira"


def test_controller_copies_settings_onto_the_live_app(tmp_path):
    settings = ui.Settings(str(tmp_path / "settings.json"))
    app, cue, note = FakeApp(), FakeCue(), FakeCue()
    controller = ui.UIController(settings, app=app, announcer=cue, notifier=note)

    controller.update({
        "mute_ads": False,
        "pause_dictation": False,
        "pause_needs_wispr_setting": True,
        "announce": False,
        "notify": False,
        "announce_volume": 55,
        "announce_voice": "David",
    })

    assert app.handle_ads is False
    assert app.handle_dictation is False
    assert app.pause_needs_setting is True
    assert cue.enabled is False and note.enabled is False
    assert cue.volume == 55 and cue.voice_name == "David"


def test_status_text_reflects_the_live_app(tmp_path):
    settings = ui.Settings(str(tmp_path / "settings.json"))
    app = FakeApp()
    controller = ui.UIController(settings, app=app)
    assert controller.status_text() == "Watching Spotify"
    app.dictating = True
    app.paused_by_us = True
    assert "paused" in controller.status_text().lower()
