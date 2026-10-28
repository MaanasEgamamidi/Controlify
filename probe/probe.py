"""Signal probe: logs changes (with timestamps) in every candidate signal for
dictation / ad detection. Read-only. Usage: python probe.py [seconds] -> probe.log
"""
import asyncio, ctypes, ctypes.wintypes as w, json, os, sys, time, winreg
import psutil
from pycaw.pycaw import AudioUtilities

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 300
LOG = os.path.join(os.path.dirname(__file__), "probe.log")
CFG = os.path.expandvars(r"%APPDATA%\Wispr Flow\config.json")
MIC = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"
u = ctypes.windll.user32
last = {}
t0 = time.time()
out = open(LOG, "w", encoding="utf-8", buffering=1)


def emit(key, val):
    if last.get(key) != val:
        last[key] = val
        out.write(f"{time.time()-t0:8.2f}s  {key} = {val}\n")


def mic_state():
    res = {}
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIC)
    except OSError:
        return res
    i = 0
    while True:
        try:
            name = winreg.EnumKey(k, i)
        except OSError:
            break
        i += 1
        if "Wispr" not in name:
            continue
        try:
            sk = winreg.OpenKey(k, name)
            start = winreg.QueryValueEx(sk, "LastUsedTimeStart")[0]
            stop = winreg.QueryValueEx(sk, "LastUsedTimeStop")[0]
            if start > stop or stop == 0:
                res[name.split("#")[-2]] = "IN_USE"
            res.setdefault("_newest_stop", 0)
            res["_newest_stop"] = max(res["_newest_stop"], stop)
        except OSError:
            pass
    return res


def windows_of(prefixes):
    found = []
    pids = {p.pid: p.name() for p in psutil.process_iter(["name"]) if p.info["name"] and p.info["name"].lower().startswith(prefixes)}

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def cb(h, _):
        pid = w.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            r = w.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            found.append((pids[pid.value], b.value, (r.left, r.top, r.right, r.bottom)))
        return True

    u.EnumWindows(cb, 0)
    return found


def audio_state():
    res = {}
    for s in AudioUtilities.GetAllSessions():
        if s.Process is None:
            continue
        try:
            sv = s._ctl.QueryInterface(__import__("pycaw.pycaw", fromlist=["ISimpleAudioVolume"]).ISimpleAudioVolume)
            res[f"{s.Process.name()}:{s.ProcessId}"] = (round(sv.GetMasterVolume(), 3), bool(sv.GetMute()), s.State)
        except Exception as e:
            res[f"{s.Process.name()}:{s.ProcessId}"] = f"err {e}"
    return res


def cfg_state():
    try:
        with open(CFG, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return {"_err": type(e).__name__}
    found = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("shouldMuteAudio", "shouldPauseAudio", "activeDictationSession"):
                    found[k] = v if k != "activeDictationSession" else ("set" if v else None)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(d)
    return found


async def main():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
    mgr = await M.request_async()
    while time.time() - t0 < DUR:
        emit("mic", mic_state())
        emit("wispr_windows", windows_of(("wispr flow",)))
        emit("spotify_windows", [x[1:] for x in windows_of(("spotify",))])
        a = audio_state()
        for k, v in a.items():
            emit(f"audio[{k}]", v)
        emit("audio_sessions", sorted(a))
        emit("config", cfg_state())
        sessions = mgr.get_sessions()
        smtc = {}
        for s in sessions:
            try:
                p = await s.try_get_media_properties_async()
                pb = s.get_playback_info()
                tl = s.get_timeline_properties()
                smtc[s.source_app_user_model_id] = dict(
                    title=p.title, artist=p.artist, album=p.album_title, track=p.track_number,
                    status=int(pb.playback_status), type=(int(pb.playback_type) if pb.playback_type else None),
                    end=str(tl.end_time),
                )
            except Exception as e:
                smtc[s.source_app_user_model_id] = f"err {e}"
        emit("smtc", smtc)
        await asyncio.sleep(0.1)


asyncio.run(main())
out.close()
