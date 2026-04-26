import os
import sys
import heapq
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
    def __init__(self, sample_rate=16000, channels=1, block_size=320):
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size  # 20ms at 16kHz

        self.input_stream = None
        self.output_stream = None
        self.send_callback = None

        # Jitter Buffer: (sequence_number, data)
        self.jitter_buffer = []
        self.buffer_lock = threading.Lock()
        self.next_expected_seq = None

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

        # VAD — optional, degrades gracefully when webrtcvad is absent
        self.vad = None
        if VAD_AVAILABLE:
            try:
                self.vad = _webrtcvad.Vad(2)  # Moderate aggressiveness
            except Exception as e:
                logger.error("Failed to initialize VAD", error=str(e))

    def start(self, send_callback) -> bool:
        self.send_callback = send_callback
        try:
            self.input_stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._input_callback,
                blocksize=self.block_size,
                dtype="int16",
            )
            self.output_stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._output_callback,
                blocksize=self.block_size,
                dtype="int16",
            )
            self.input_stream.start()
            self.output_stream.start()
            self.is_running = True
            logger.info("Audio Engine started (Opus/VAD enabled)")
            return True
        except Exception as e:
            logger.error("Failed to start audio engine", error=str(e))
            self.is_running = False
            return False

    def stop(self):
        self.is_running = False
        if self.input_stream:
            try:
                self.input_stream.stop()
                self.input_stream.close()
            except Exception:
                pass
            self.input_stream = None

        if self.output_stream:
            try:
                self.output_stream.stop()
                self.output_stream.close()
            except Exception:
                pass
            self.output_stream = None

        with self.buffer_lock:
            self.jitter_buffer.clear()
            self.next_expected_seq = None
        logger.info("Audio Engine stopped")

    def _input_callback(self, indata, frames, time, status):
        if status:
            logger.warning("Audio input status", status=status)
        if not (self.send_callback and self.is_running and self.encoder):
            return

        raw_pcm = indata.tobytes()

        if self._muted:
            return

        # VAD: skip silent frames to save bandwidth; pass everything when VAD is absent
        if self.vad is not None:
            try:
                is_speech = self.vad.is_speech(raw_pcm, self.sample_rate)
            except Exception:
                is_speech = True
        else:
            is_speech = True

        if is_speech:
            # 2. Encode with Opus
            try:
                encoded = self.encoder.encode(raw_pcm, self.block_size)
                self.send_callback(encoded)
            except Exception as e:
                logger.error("Opus encoding failed", error=str(e))

    def _output_callback(self, outdata, frames, time, status):
        if status:
            logger.warning("Audio output status", status=status)

        pcm_payload = None
        
        with self.buffer_lock:
            # Buffer must have at least a few packets to start playing (initial jitter delay)
            if self.next_expected_seq is None:
                if len(self.jitter_buffer) >= 3:
                    self.next_expected_seq = self.jitter_buffer[0][0]
                else:
                    outdata.fill(0)
                    return

            # Check if the next expected packet is in the buffer
            if self.jitter_buffer and self.jitter_buffer[0][0] <= self.next_expected_seq:
                seq, encoded_data = heapq.heappop(self.jitter_buffer)
                
                # If we got an old packet (late), discard and try again
                while seq < self.next_expected_seq and self.jitter_buffer:
                    seq, encoded_data = heapq.heappop(self.jitter_buffer)
                
                if seq == self.next_expected_seq:
                    try:
                        pcm_payload = self.decoder.decode(encoded_data, self.block_size)
                    except Exception as e:
                        logger.error("Opus decoding failed", error=str(e))
                
            self.next_expected_seq += 1

        if pcm_payload:
            arr = np.frombuffer(pcm_payload, dtype="int16").reshape(-1, self.channels)
            n = min(len(arr), frames)
            outdata[:n] = arr[:n]
            if n < frames:
                outdata[n:].fill(0)
        else:
            # Packet Loss Concealment (PLC): Opus can decode 'None' to fill the gap
            try:
                if self.decoder:
                    plc_pcm = self.decoder.decode(None, self.block_size)
                    arr = np.frombuffer(plc_pcm, dtype="int16").reshape(-1, self.channels)
                    outdata[:] = arr[:frames]
                else:
                    outdata.fill(0)
            except Exception:
                outdata.fill(0)

    def mute(self):
        self._muted = True

    def unmute(self):
        self._muted = False

    def receive_audio(self, seq: int, data: bytes):
        """Called from network layer with sequence number and encoded data."""
        with self.buffer_lock:
            # Use heapq for priority-based reordering
            heapq.heappush(self.jitter_buffer, (seq, data))
            # Prevent buffer from growing indefinitely
            if len(self.jitter_buffer) > 50:
                heapq.heappop(self.jitter_buffer)
