"""One quiet, generated chime; no notifications, speech, or repeated alarms."""

from __future__ import annotations

import io
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


def chime_bytes() -> bytes:
    rate = 22050
    duration = 0.55
    frames = bytearray()
    for i in range(int(rate * duration)):
        t = i / rate
        envelope = min(t / 0.02, 1.0) * math.exp(-7 * t) * min((duration - t) / 0.08, 1.0)
        sample = int(32767 * 0.10 * envelope * math.sin(2 * math.pi * 660 * t))
        frames.extend(struct.pack("<h", sample))
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(frames)
    return out.getvalue()


def play() -> None:
    audio = chime_bytes()
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(audio, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        return
    player = shutil.which("afplay" if sys.platform == "darwin" else "paplay")
    player = player or shutil.which("aplay")
    if not player:
        raise OSError("no WAV audio player available")
    with tempfile.TemporaryDirectory(prefix="timeprobe-") as directory:
        path = Path(directory) / "chime.wav"
        path.write_bytes(audio)
        subprocess.run([player, str(path)], check=True, capture_output=True, timeout=10)
