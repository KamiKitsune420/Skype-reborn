import sounddevice as sd
import numpy as np
from collections import deque
import structlog

logger = structlog.get_logger()


class AudioEngine:
    def __init__(self, sample_rate=16000, channels=1, block_size=320):
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_size = block_size
        self.input_stream = None
        self.output_stream = None
        self.send_callback = None
        self.jitter_buffer = deque(maxlen=20)
        self.is_running = False

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
            logger.info("Audio Engine started")
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
            self.input_stream = None  # Prevent double-stop crash

        if self.output_stream:
            try:
                self.output_stream.stop()
                self.output_stream.close()
            except Exception:
                pass
            self.output_stream = None  # Prevent double-stop crash

        self.jitter_buffer.clear()
        logger.info("Audio Engine stopped")

    def _input_callback(self, indata, frames, time, status):
        if status:
            logger.warning("Audio input status", status=status)
        if self.send_callback and self.is_running:
            self.send_callback(indata.tobytes())

    def _output_callback(self, outdata, frames, time, status):
        """Fill outdata from the jitter buffer.

        The old code used len(data) (bytes) as a frame index which was wrong —
        it happened to work only when data was exactly block_size * 2 bytes.
        If the incoming chunk is a different size this would raise a shape
        mismatch ValueError inside PortAudio's thread, silencing the output.
        """
        if status:
            logger.warning("Audio output status", status=status)

        if self.jitter_buffer:
            raw = self.jitter_buffer.popleft()
            arr = np.frombuffer(raw, dtype="int16").reshape(-1, self.channels)
            n = min(len(arr), frames)   # work in frames, not bytes
            outdata[:n] = arr[:n]
            if n < frames:
                outdata[n:].fill(0)     # pad remainder with silence
        else:
            outdata.fill(0)             # silence when buffer is empty

    def receive_audio(self, data: bytes):
        """Called from the network layer to push incoming audio into the buffer."""
        self.jitter_buffer.append(data)
