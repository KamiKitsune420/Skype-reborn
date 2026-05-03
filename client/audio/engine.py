import os
import sys
import threading
import numpy as np
import sounddevice as sd
import structlog

logger = structlog.get_logger()

# On Windows, ctypes.util.find_library() searches PATH for "opus.dll" and
# ignores os.add_dll_directory().  Patch find_library so opuslib gets the
# full path to our bundled libopus.dll before it attempts the import.
if sys.platform == "win32":
    _lib_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "lib")
    )
    _dll_path = os.path.join(_lib_dir, "libopus.dll")
    if os.path.exists(_dll_path):
        import ctypes.util as _ctypes_util
        _orig_find = _ctypes_util.find_library
        def _find_opus(name, _orig=_orig_find, _path=_dll_path):
            return _path if name == "opus" else _orig(name)
        _ctypes_util.find_library = _find_opus
        os.add_dll_directory(_lib_dir)

try:
    from opuslib import Encoder as OpusEncoder, Decoder as OpusDecoder
    OPUS_AVAILABLE = True
except Exception:
    OPUS_AVAILABLE = False
    logger.warning("Opus library not found. Falling back to raw PCM.")

    class OpusEncoder:
        def __init__(self, *args, **kwargs): pass
        def encode(self, pcm, frame_size): return pcm

    class OpusDecoder:
        def __init__(self, *args, **kwargs): pass
        def decode(self, data, frame_size):
            return data if data else b'\x00' * (frame_size * 2)

try:
    import webrtcvad as _webrtcvad
    VAD_AVAILABLE = True
except Exception:
    _webrtcvad = None
    VAD_AVAILABLE = False
    logger.warning("webrtcvad not available — VAD disabled, all audio will be sent.")


class AudioEngine:
    _BUF_STARTUP = 3   # frames to accumulate before starting playback
    _BUF_MAX     = 50  # frames to keep; oldest are dropped on overflow
    _BUF_RESYNC  = 20  # frames-ahead gap before jumping forward to recover

    def __init__(self, sample_rate=16000, channels=1, block_size=320):
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size  # 20ms at 16kHz

        self._stream = None
        self.send_callback = None

        # Jitter buffer: dict {seq -> opus_bytes} for O(1) lookup.
        # Research (Speex/PJSIP) confirms: drop oldest on overflow, resync
        # only after a large gap (≥20 frames), never block in the callback.
        self._play_buf: dict = {}
        self._buf_lock = threading.Lock()
        self._next_seq: int | None = None

        self.is_running = False
        self._muted     = False

        # Opus encoder/decoder — uses stub classes when libopus is absent
        try:
            self.encoder = OpusEncoder(self.sample_rate, self.channels, 'voip')
            self.decoder = OpusDecoder(self.sample_rate, self.channels)
        except Exception as e:
            logger.error("Failed to initialize Opus codec", error=str(e))
            self.encoder = None
            self.decoder = None

        # VAD is disabled intentionally: aggressiveness-2 suppresses all frames
        # during silence, which breaks calls when neither party is actively speaking
        # (including same-machine testing).  All captured frames are sent.
        self.vad = None

    def start(self, send_callback) -> bool:
        self.send_callback = send_callback
        try:
            # Full-duplex stream: one device open for both capture and playback,
            # synchronized clock.  Two separate InputStream+OutputStream pairs can
            # conflict when two client instances share the same device.
            self._stream = sd.Stream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._duplex_callback,
                blocksize=self.block_size,
                dtype="int16",
            )
            self._stream.start()
            self.is_running = True
            logger.info("Audio Engine started")
            return True
        except Exception as e:
            logger.error("Failed to start audio engine", error=str(e))
            self.is_running = False
            return False

    def stop(self):
        self.is_running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._buf_lock:
            self._play_buf.clear()
            self._next_seq = None
        logger.info("Audio Engine stopped")

    def _duplex_callback(self, indata, outdata, frames, time, status):
        # Single full-duplex callback — handles both playback and capture.
        # Must NEVER raise: any uncaught exception causes sounddevice to return
        # paAbort and permanently kill the stream.

        # ── Playback (outdata must always be filled) ──────────────────────
        try:
            if status:
                logger.warning("Audio status", status=status)

            opus_data = None
            with self._buf_lock:
                if self._next_seq is not None:
                    if self._play_buf:
                        oldest = min(self._play_buf)
                        if oldest > self._next_seq + self._BUF_RESYNC:
                            self._next_seq = oldest
                    opus_data = self._play_buf.pop(self._next_seq, None)
                    self._next_seq += 1

            try:
                raw = self.decoder.decode(opus_data, self.block_size) if self.decoder else None
            except Exception:
                raw = None

            if raw:
                arr = np.frombuffer(raw, dtype="int16").reshape(-1, self.channels)
                n = min(len(arr), frames)
                outdata[:n] = arr[:n]
                if n < frames:
                    outdata[n:].fill(0)
            else:
                outdata.fill(0)

        except Exception as e:
            logger.error("Playback side crashed", error=str(e))
            try:
                outdata.fill(0)
            except Exception:
                pass

        # ── Capture (mic → encode → send) ────────────────────────────────
        try:
            if self.send_callback and self.is_running and self.encoder and not self._muted:
                try:
                    self.send_callback(
                        self.encoder.encode(indata.tobytes(), self.block_size)
                    )
                except Exception as e:
                    logger.error("Encode/send failed", error=str(e))
        except Exception as e:
            logger.error("Capture side crashed", error=str(e))

    def mute(self):
        self._muted = True

    def unmute(self):
        self._muted = False

    def receive_audio(self, seq: int, data: bytes):
        """Called from the network layer with a sequence number and Opus payload."""
        with self._buf_lock:
            self._play_buf[seq] = data

            # Drop oldest frame when the buffer is full so we always hold the
            # most recent audio (confirmed correct by Speex/PJSIP reference).
            while len(self._play_buf) > self._BUF_MAX:
                del self._play_buf[min(self._play_buf)]

            # Begin playback once the startup buffer is filled.
            if self._next_seq is None and len(self._play_buf) >= self._BUF_STARTUP:
                self._next_seq = min(self._play_buf)
