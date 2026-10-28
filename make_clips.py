r"""One-time: generate the spoken cue clips in clips/ with a Piper neural voice (offline).

    .venv\Scripts\python.exe make_clips.py [--voice en_US-ryan-medium]

Needs `pip install piper-tts` and the voice in voices/ (download with:
    python -m piper.download_voices --download-dir voices en_US-ryan-medium).
Controlify itself only plays the saved clips at runtime.

Every phrase Controlify can say is listed in controlify.CLIPS (the "ad start"
cue, how many ads, how long the mute lasts), so this script generates all of
them - re-run it after changing those phrases.
"""
import argparse, os, wave
from piper import PiperVoice

from controlify import CLIPS

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="en_US-ryan-medium")
    voice_name = ap.parse_args().voice
    voice = PiperVoice.load(os.path.join(HERE, "voices", voice_name + ".onnx"))
    os.makedirs(os.path.join(HERE, "clips"), exist_ok=True)
    for text, name in CLIPS.items():
        with wave.open(os.path.join(HERE, "clips", name), "wb") as wf:
            voice.synthesize_wav(text, wf)
        print("wrote", name, "-", text)
