"""Cross-platform, non-blocking WAV player backed by sounddevice.

Replaces wx.adv.Sound so UI sounds work on Linux and macOS as well as Windows.
read_wav_float is also imported by client/ui/settings.py for the preview feature.
"""
import os
import threading

import numpy as np
import sounddevice as sd
import structlog
import wave

logger = structlog.get_logger()


def read_wav_float(path: str):
    """Read a WAV file of any standard bit depth → (float32 ndarray, sample_rate).

    Handles 8-bit unsigned, 16-bit, 24-bit, and 32-bit signed PCM.
    """
    with wave.open(path, "rb") as wf:
        n_frames = wf.getnframes()
        n_ch     = wf.getnchannels()
        sw       = wf.getsampwidth()   # bytes per sample
        fs       = wf.getframerate()
        raw      = wf.readframes(n_frames)

    if sw == 1:                        # 8-bit unsigned
        s = np.frombuffer(raw, np.uint8).astype(np.float32) / 128.0 - 1.0
    elif sw == 2:                      # 16-bit signed LE
        s = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif sw == 3:                      # 24-bit signed LE (3 bytes/sample)
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        i32 = (b[:, 0].astype(np.int32) |
               (b[:, 1].astype(np.int32) << 8) |
               (b[:, 2].astype(np.int32) << 16))
        i32[i32 >= (1 << 23)] -= (1 << 24)  # sign-extend
        s = i32.astype(np.float32) / (1 << 23)
    elif sw == 4:                      # 32-bit signed LE
        s = np.frombuffer(raw, "<i4").astype(np.float32) / 2**31
    else:
        raise ValueError(f"Unsupported WAV sample width: {sw} bytes")

    if n_ch > 1:
        s = s.reshape(-1, n_ch)
    return s, fs


class SoundPlayer:
    """Thread-safe, cross-platform one-shot and looping WAV player.

    Uses sounddevice's default output stream which is independent of the
    AudioEngine's full-duplex stream, so call audio and UI sounds coexist.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def play(self, path: str, loop: bool = False) -> bool:
        """Play path asynchronously.  Returns True on success."""
        if not os.path.exists(path):
            return False
        try:
            data, fs = read_wav_float(path)
            with self._lock:
                sd.play(data, fs, loop=loop)
            return True
        except Exception as e:
            logger.warning("Sound play failed", path=path, error=str(e))
            return False

    def stop(self):
        """Stop any currently playing sound."""
        try:
            with self._lock:
                sd.stop()
        except Exception:
            pass
