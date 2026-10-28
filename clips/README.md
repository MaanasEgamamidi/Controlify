# Spoken cue clips

These are the two base clips Controlify plays when an ad starts:

* `ad_start.wav` - "ad start"
* `ad_start_not_muted.wav` - "ad start, not muted"

They were generated offline with [Piper](https://github.com/rhasspy/piper)
using the `en_US-ryan-medium` voice. That voice's dataset is licensed
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), so these
generated audio files are distributed under the same license. They are not
covered by the repository's MIT license (which applies to the code). The voice
model itself is not committed because it is large; download it only if you want
to regenerate the clips.

To regenerate the clips with a different voice:

```bat
.venv\Scripts\python.exe -m pip install piper-tts
.venv\Scripts\python.exe -m piper.download_voices --download-dir voices en_US-ryan-medium
.venv\Scripts\python.exe make_clips.py --voice en_US-ryan-medium
```

Replace `en_US-ryan-medium` with any voice listed in the
[Piper voices collection](https://huggingface.co/rhasspy/piper-voices).
If the clips are missing, Controlify falls back to the built-in Windows SAPI
voice, so the app still works without them.

Volume-scaled copies (`.v15_ad_start.wav`, etc.) are generated at runtime and
are gitignored.
