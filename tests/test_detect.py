"""Detection / controller checks against synthetic samples."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import controlify as c
from controlify import Media, is_ad, PLAYING, PAUSED

def m(title="", artist="", album="", status=PLAYING, win=""):
    return Media(title, artist, album, status, win)

SONG = m("Midnight Drive", "Neon Harbor", "Midnight Drive", win="Neon Harbor - Midnight Drive")

def test_song_is_not_ad():
    assert not is_ad(SONG)

def test_track_with_spotify_in_name_is_not_ad():
    assert not is_ad(m("Spotify Blues", "Some Band", "Album", win="Some Band - Spotify Blues"))

def test_advertisement_title():
    assert is_ad(m("Advertisement", "Spotify", ""))

def test_spotify_artist_no_album():
    assert is_ad(m("Brand X", "Spotify", ""))

@pytest.mark.parametrize("win", ["Spotify Free", "Advertisement", "LISTEN NOW", "\u2014", "Spotify"])
def test_non_track_window_title_while_playing_is_ad(win):
    assert is_ad(m("whatever", "x", "y", PLAYING, win))

def test_paused_idle_window_title_is_not_ad():
    assert not is_ad(m(SONG.title, SONG.artist, SONG.album, PAUSED, "Spotify Free"))

def test_missing_window_title_is_not_ad():
    assert not is_ad(m(SONG.title, SONG.artist, SONG.album, PLAYING, ""))

# The exact metadata a podcast episode publishes: no artist, the show as the
# album, and a window title that is just the episode name.
EPISODE = m("Episode 42: The Long Road", "", "The Sample Show",
            PLAYING, "Episode 42: The Long Road")

def test_podcast_episode_is_not_ad():
    assert not is_ad(EPISODE)

def test_podcast_episode_that_reports_an_artist_is_not_ad():
    e = m("Ep 12", "The Show", "The Show", PLAYING, "Ep 12")
    assert not is_ad(e)

def test_ad_break_inside_a_podcast_is_still_an_ad():
    assert is_ad(m("Advertisement", "Spotify", "", PLAYING, "Advertisement"))


# --------------------------------------------------------------------------
# Sample ad metadata modelled on real Spotify ads. Every ad observed during
# development was published with the advertiser as the artist, *no album at
# all*, and a window title that is just the ad's own text.
# --------------------------------------------------------------------------
AD_SAMPLES = [
    ("Acme Health", "Acting now to end overdose."),
    ("Streamly", "Now streaming on Streamly+"),
    ("FoodDash", "Don't pay for delivery."),
    ("RunCo", "Run The Season"),
    ("ListenCo", "LISTEN NOW"),
    ("Sample Bank", "It Pays To Switch"),
    ("Sample University", "Learn more at example.edu"),
    ("Sample Travel", "Discover somewhere new."),
    ("Spotify Advertising", "Spotify Advertising"),
    ("", "\u25b6"),                       # the bare "play" glyph, no artist
]

@pytest.mark.parametrize("artist,title", AD_SAMPLES)
def test_ad_sample_is_detected(artist, title):
    assert is_ad(m(title, artist, "", PLAYING, title))

TRACK_SAMPLES = [
    ("Neon Harbor", "Midnight Drive", "Midnight Drive"),
    ("The Quiet Hours", "Paper Lanterns", "Small Rooms"),
    ("Sample Artist", "A Song Title", "An Album Name"),
    ("Another Artist", "another song title", "another song title"),
]

@pytest.mark.parametrize("artist,title,album", TRACK_SAMPLES)
def test_track_sample_is_not_an_ad(artist, title, album):
    assert not is_ad(m(title, artist, album, PLAYING, f"{artist} - {title}"))

def test_ad_sample_mutes_end_to_end(app):
    ad = m("Streamly", "Now streaming on Streamly+", "", PLAYING,
           "Now streaming on Streamly+")
    run(app, [ad] * 3)
    assert app.vol.v == 0.0
    run(app, [SONG] * 3, t0=1.0)
    assert app.vol.v == 1.0 and app.saved_volume is None

def test_window_showing_the_next_track_is_not_an_ad():
    # Spotify updates the window title before the media session does.
    assert not is_ad(m(SONG.title, SONG.artist, SONG.album, PLAYING,
                       "Other Artist - Other Song"))

def test_track_without_an_album_is_not_an_ad():
    # A track whose album was not reported must not be muted for 3 minutes.
    assert not is_ad(m(SONG.title, SONG.artist, "", PLAYING,
                       f"{SONG.artist} - {SONG.title}"))


class FakeVol:
    def __init__(self, v=1.0): self.v, self.saved = v, None
    def get(self): return self.v
    def set(self, x): self.v = x; return 1

@pytest.fixture
def app(monkeypatch):
    vol = FakeVol()
    monkeypatch.setattr(c, "current_spotify_volume", vol.get)
    monkeypatch.setattr(c, "set_spotify_volume", vol.set)
    monkeypatch.setattr(c, "load_saved_volume", lambda: None)
    monkeypatch.setattr(c, "store_saved_volume", lambda v: None)
    monkeypatch.setattr(c, "load_ad_breaks", lambda: [])
    monkeypatch.setattr(c, "store_ad_breaks", lambda breaks: None)
    a = c.Controlify(None, None)
    a.vol = vol
    return a

def run(app, samples, t0=0.0, dt=0.15):
    for i, s in enumerate(samples):
        app._update_ad(t0 + i * dt, s)

RESUME_GLITCH = m(SONG.title, SONG.artist, SONG.album, PLAYING, "Spotify Free")

def test_one_tick_resume_glitch_does_not_mute(app):
    run(app, [SONG, RESUME_GLITCH, SONG, SONG])
    assert app.vol.v == 1.0

def test_short_stale_title_after_resume_does_not_mute(app):
    run(app, [RESUME_GLITCH] * 2 + [SONG] * 3)       # < weak threshold
    assert app.vol.v == 1.0

def test_media_session_ad_mutes_fast_and_restores(app):
    ad = m("Advertisement", "Spotify", "")
    run(app, [ad, ad])
    assert app.vol.v == 0.0
    run(app, [SONG] * 3, t0=1.0)
    assert app.vol.v == 1.0

def test_window_only_ad_mutes_after_debounce(app):
    ad = m("x", "y", "z", PLAYING, "LISTEN NOW")
    run(app, [ad] * 3)
    assert app.vol.v == 0.0

def test_podcast_play_pause_cycle_never_mutes(app):
    # the real report: an episode played, got paused by hand, and was still
    # muted long after - the mute outlived the ad it thought it saw
    paused = m(EPISODE.title, "", EPISODE.album, PAUSED, "Spotify Free")
    run(app, [EPISODE] * 3 + [paused] * 6 + [EPISODE] * 3)
    assert app.vol.v == 1.0 and not app.ad_active

def test_podcast_ad_break_still_mutes_and_restores(app):
    run(app, [EPISODE] * 2)
    ad = m("Advertisement", "Spotify", "", PLAYING, "Advertisement")
    run(app, [ad, ad], t0=1.0)
    assert app.vol.v == 0.0
    run(app, [EPISODE] * 3, t0=2.0)
    assert app.vol.v == 1.0 and app.saved_volume is None

def test_wispr_unmute_mid_ad_is_reenforced(app):
    ad = m("Advertisement", "Spotify", "")
    run(app, [ad, ad]); app.vol.v = 1.0
    run(app, [ad], t0=1.0)
    assert app.vol.v == 0.0

def test_turning_ads_off_restores_the_volume(app):
    ad = m("Advertisement", "Spotify", "")
    run(app, [ad, ad])
    assert app.vol.v == 0.0
    app.handle_ads = False
    app._stop_ads(1.0)
    assert app.vol.v == 1.0 and app.saved_volume is None

def test_restore_deferred_until_dictation_over(app):
    ad = m("Advertisement", "Spotify", "")
    run(app, [ad, ad]); assert app.vol.v == 0.0
    app.dictating = True
    run(app, [SONG] * 4, t0=1.0)                      # ad ended mid-dictation
    assert app.vol.v == 0.0 and app.saved_volume == 1.0
    app.dictating = False; app._dictation_ended_at = 2.0
    run(app, [SONG], t0=2.2)                          # < 0.5s after dictation end
    assert app.vol.v == 0.0
    run(app, [SONG], t0=2.6)
    assert app.vol.v == 1.0 and app.saved_volume is None

def test_paused_ad_stays_muted_until_playing_again(app):
    ad = m("Advertisement", "Spotify", "")
    run(app, [ad, ad]); assert app.vol.v == 0.0
    paused_ad = m("Advertisement", "Spotify", "", PAUSED, "Spotify Free")
    paused_track = m("t", "a", "al", PAUSED, "Spotify Free")
    run(app, [paused_ad, paused_track] * 5, t0=1.0)   # e.g. paused while dictating
    assert app.vol.v == 0.0
    run(app, [ad], t0=3.0)                            # ad resumes: no leak
    assert app.vol.v == 0.0
    run(app, [SONG] * 3, t0=4.0)
    assert app.vol.v == 1.0


# ---------------------------------------------------------------- dictation
import asyncio

class FakeSession:
    def __init__(self): self.calls = []
    async def try_pause_async(self): self.calls.append("pause"); return True
    async def try_play_async(self): self.calls.append("play"); return True

class FakeWispr:
    def __init__(self): self.mic, self.setting = False, True
    def mic_in_use(self, now): return self.mic
    def mute_setting_enabled(self): return self.setting

AD = m("Advertisement", "Spotify", "", PLAYING, "Advertisement")

@pytest.fixture
def dapp(app):
    app.wispr, app.sess = FakeWispr(), FakeSession()
    app.t = 0.0
    def step(media, mic=None, n=1):
        if mic is not None: app.wispr.mic = mic
        for _ in range(n):
            app.t += 0.15
            app._update_ad(app.t, media)
            asyncio.run(app._update_dictation(app.t, app.sess, media))
    app.step = step
    return app

def test_dictation_over_song_pauses_then_resumes(dapp):
    dapp.step(SONG, mic=True)
    assert dapp.sess.calls == ["pause"]
    paused = m(SONG.title, SONG.artist, SONG.album, PAUSED, "Spotify Free")
    dapp.step(paused, n=3); dapp.step(paused, mic=False, n=4)
    assert dapp.sess.calls == ["pause", "play"]

def test_dictation_during_ad_does_not_pause(dapp):
    dapp.step(AD, n=3)                          # ad detected + muted
    dapp.step(AD, mic=True, n=3)
    dapp.step(AD, mic=False, n=4)
    assert dapp.sess.calls == []

def test_ad_ends_mid_dictation_pauses_at_song_start_then_resumes(dapp):
    dapp.step(AD, n=3)
    dapp.step(AD, mic=True, n=3)
    assert dapp.sess.calls == []
    dapp.step(SONG, n=1)
    assert dapp.sess.calls == []                # one tick is not enough
    dapp.step(SONG, n=1)
    assert dapp.sess.calls == ["pause"]         # pauses right at the start
    paused = m(SONG.title, SONG.artist, SONG.album, PAUSED, "Spotify Free")
    dapp.step(paused, n=5)
    assert dapp.vol.v == 0.0                    # still muted while dictating
    dapp.step(paused, mic=False, n=40)          # dictation ends; volume restored first
    assert dapp.vol.v == 1.0
    assert dapp.sess.calls == ["pause", "play"]

def test_ad_ends_after_dictation_nothing_paused(dapp):
    dapp.step(AD, n=3); dapp.step(AD, mic=True, n=3); dapp.step(AD, mic=False, n=4)
    dapp.step(SONG, n=10)
    assert dapp.sess.calls == []

def _dictate(dapp):
    """One dictation over a playing song: pause on the mic, resume after."""
    paused = m(SONG.title, SONG.artist, SONG.album, PAUSED, "Spotify Free")
    dapp.step(SONG, mic=True, n=3)
    dapp.step(paused, n=3)
    dapp.step(paused, mic=False, n=4)

def test_pauses_even_when_wispr_setting_is_off(dapp):
    # The default: any dictation pauses Spotify, whatever Wispr's own
    # "mute all audio while dictating" switch says.
    dapp.wispr.setting = False
    _dictate(dapp)
    assert dapp.sess.calls == ["pause", "play"]

def test_pause_needs_wispr_setting_opt_in(dapp):
    dapp.pause_needs_setting = True
    dapp.wispr.setting = False
    _dictate(dapp)
    assert dapp.sess.calls == []

def test_pause_needs_wispr_setting_still_pauses_when_on(dapp):
    dapp.pause_needs_setting = True
    dapp.wispr.setting = True
    _dictate(dapp)
    assert dapp.sess.calls == ["pause", "play"]

def test_user_pause_during_dictation_is_not_overridden(dapp):
    dapp.step(SONG, mic=True)                      # we pause
    paused = m(SONG.title, SONG.artist, SONG.album, PAUSED, "Spotify Free")
    dapp.step(paused, n=2)                          # the session shows the pause
    dapp.step(SONG, n=3)                            # user pressed play
    dapp.step(SONG, mic=False, n=4)
    assert dapp.sess.calls == ["pause"]

def test_slow_status_update_does_not_cancel_the_resume(dapp):
    """Spotify can take a second to report PAUSED; that lag must not look
    like the user pressing play, or the music never comes back."""
    dapp.step(SONG, mic=True)                      # we pause
    dapp.step(SONG, n=8)                            # status still says PLAYING
    paused = m(SONG.title, SONG.artist, SONG.album, PAUSED, "Spotify Free")
    dapp.step(paused, n=3)                          # now it reports PAUSED
    dapp.step(paused, mic=False, n=4)               # dictation ends
    assert dapp.sess.calls == ["pause", "play"]


# ------------------------------------------------- dictation signal (Wispr)
def _write_config(path, session, mtime):
    """Write a Wispr config.json; `session` is the activeDictationSession."""
    path.write_text(json.dumps({
        "prefs": {
            "activeDictationSession": session,
            "user": {"shouldMuteAudio": False},
        }
    }), encoding="utf-8")
    os.utime(path, (mtime, mtime))

def test_wispr_config_reports_dictation(tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"uuid": "abc", "startTimestamp": 1}, 1000.0)
    w = c.WisprWatcher(str(cfg))
    assert w.mic_in_use(0.0) is True

def test_wispr_config_reports_no_dictation(tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, None, 1000.0)
    w = c.WisprWatcher(str(cfg))
    assert w.mic_in_use(0.0) is False

def test_wispr_config_signal_follows_the_file(tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, None, 1000.0)
    w = c.WisprWatcher(str(cfg))
    assert w.mic_in_use(0.0) is False
    _write_config(cfg, {"uuid": "abc"}, 2000.0)     # dictation started
    assert w.mic_in_use(0.0) is True
    _write_config(cfg, None, 3000.0)               # dictation ended
    assert w.mic_in_use(0.0) is False

def test_wispr_config_missing_key_falls_back_to_consent_store(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"prefs": {"user": {}}}), encoding="utf-8")
    w = c.WisprWatcher(str(cfg))
    monkeypatch.setattr(w, "_consent_mic_in_use", lambda now: True)
    assert w.mic_in_use(0.0) is True
    monkeypatch.setattr(w, "_consent_mic_in_use", lambda now: False)
    assert w.mic_in_use(0.0) is False

def test_wispr_config_survives_a_broken_read(tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"uuid": "abc"}, 1000.0)
    w = c.WisprWatcher(str(cfg))
    assert w.mic_in_use(0.0) is True
    cfg.write_text("{ this is not json", encoding="utf-8")   # mid-write
    os.utime(cfg, (2000.0, 2000.0))
    assert w.mic_in_use(0.0) is True                          # keeps the last good state
    _write_config(cfg, None, 3000.0)
    assert w.mic_in_use(0.0) is False


# ---------------------------------------------------------------- announcements
def test_ad_start_is_announced_once(app):
    said = []; app.announce = said.append
    ad = m("Advertisement", "Spotify", "")
    run(app, [ad] * 10)
    assert said == ["ad start"]

def test_announces_when_mute_fails(app, monkeypatch):
    said = []; app.announce = said.append
    monkeypatch.setattr(c, "set_spotify_volume", lambda x: 0)   # change never takes effect
    ad = m("Advertisement", "Spotify", "")
    run(app, [ad] * 3)
    assert said == ["ad start, not muted"]

def test_no_announcement_while_dictating(app):
    said = []; app.announce = said.append; app.dictating = True
    run(app, [m("Advertisement", "Spotify", "")] * 3)
    assert said == []


# ---------------------------------------------------------------- notification
@pytest.mark.parametrize("seconds,text", [(45, "45s"), (60, "1:00"), (91, "1:31")])
def test_fmt_mute(seconds, text):
    assert c.fmt_mute(seconds) == text


# ------------------------------------------- ad breaks: count, lengths, prediction
AD1 = m("Now streaming on Streamly+", "Streamly", "", PLAYING,
        "Now streaming on Streamly+")
AD2 = m("Don't pay for delivery.", "FoodDash", "", PLAYING, "Don't pay for delivery.")

def feed(app, media, times):
    for t in times:
        app._update_ad(t, media)

def test_notification_says_ads_and_mute_time(app):
    notes = []; app.notify = lambda title, body: notes.append((title, body))
    app.ad_breaks = [{"ads": [30.0, 30.0], "total": 90.0}]
    run(app, [AD1] * 3)
    assert notes == [("Ads muted for about 1:30", "2 ads, about 30s each")]

def test_notification_says_when_the_mute_failed(app, monkeypatch):
    notes = []; app.notify = lambda title, body: notes.append((title, body))
    monkeypatch.setattr(c, "set_spotify_volume", lambda x: 0)
    run(app, [AD1] * 3)
    assert notes == [("Ads playing - not muted", "2 ads, about 30s each")]

def test_notification_shows_while_dictating(app):
    notes = []; app.notify = lambda title, body: notes.append((title, body))
    app.dictating = True
    run(app, [AD1] * 3)
    assert len(notes) == 1

def test_break_counts_each_ad_and_measures_it(app, monkeypatch):
    saved = []
    monkeypatch.setattr(c, "store_ad_breaks", saved.append)
    feed(app, AD1, [0, 0.15, 0.3])    # detected (and muted) at 0.3s
    feed(app, AD2, [30, 30.15])       # a second ad 30s later
    feed(app, SONG, [60, 60.15, 60.3])
    record = saved[-1][-1]
    assert len(record["ads"]) == 2
    assert record["ads"] == pytest.approx([29.85, 30.15], abs=0.1)
    assert record["total"] == pytest.approx(60.0)

def test_metadata_flicker_is_not_a_second_ad(app, monkeypatch):
    # At a transition the window and the media session disagree for a tick.
    saved = []
    monkeypatch.setattr(c, "store_ad_breaks", saved.append)
    feed(app, AD1, [0, 0.15, 0.3])
    feed(app, m("", "\u25b6", "", PLAYING, "\u25b6"), [0.45, 0.6])
    feed(app, AD1, [0.75, 0.9])
    feed(app, SONG, [30, 30.15, 30.3])
    assert len(saved[-1][-1]["ads"]) == 1

def test_pausing_mid_break_is_not_a_second_ad(app, monkeypatch):
    # A paused break reports the paused track, which has nothing to do with
    # how many ads the break holds.
    saved = []
    monkeypatch.setattr(c, "store_ad_breaks", saved.append)
    feed(app, AD1, [0, 0.15, 0.3])
    paused = m(SONG.title, SONG.artist, SONG.album, PAUSED, "Spotify Free")
    feed(app, paused, [10, 10.15, 10.3, 10.45])
    feed(app, AD1, [20, 20.15])
    feed(app, SONG, [40, 40.15, 40.3])
    assert len(saved[-1][-1]["ads"]) == 1

def test_predicts_the_next_break_from_history(app):
    app.ad_breaks = [
        {"ads": [30.0, 30.0, 31.0], "total": 91.0},
        {"ads": [30.0, 30.0], "total": 60.0},
        {"ads": [60.0], "total": 60.0},
    ]
    assert c.predict_ad_break(app.ad_breaks) == (2, 30.0, 60.0)

def test_impossible_breaks_are_ignored(app):
    # A 0.5s "ad" is a metadata flicker, and a 10-minute break is Spotify
    # left paused halfway through one - neither should teach us anything.
    app.ad_breaks = [{"ads": [0.5], "total": 0.6},
                     {"ads": [30.0], "total": 600.0},
                     {"ads": [30.0, 30.0], "total": 60.0}]
    assert c.predict_ad_break(app.ad_breaks) == (2, 30.0, 60.0)

def test_cue_clips_keep_their_names():
    assert c.CLIPS == {"ad start": "ad_start.wav",
                       "ad start, not muted": "ad_start_not_muted.wav"}

def test_tray_quit_stops_the_watcher_and_keeper(monkeypatch):
    class FakeProc:
        def __init__(self, cmd):
            self.info = {"cmdline": cmd}
            self.terminated = False
        def terminate(self):
            self.terminated = True

    keeper = FakeProc(["python", "controlify.py", "--keep-alive"])
    watcher = FakeProc(["python", "controlify.py", "--watch"])
    app = FakeProc(["python", "controlify.py", "--exit-with-spotify"])
    other = FakeProc(["python", "something_else.py"])

    monkeypatch.setattr(c.psutil, "process_iter",
                        lambda attrs=None: [app, keeper, watcher, other])
    c.stop_supervisors()

    assert keeper.terminated and watcher.terminated
    assert not app.terminated and not other.terminated

