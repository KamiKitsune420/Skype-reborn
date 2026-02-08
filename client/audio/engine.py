import sounddevice as sd
import numpy as np
import asyncio
import struct
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

    def start(self, send_callback):
        self.send_callback = send_callback
        try:
            self.input_stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._input_callback,
                blocksize=self.block_size,
                dtype='int16'
            )
            self.output_stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._output_callback,
                blocksize=self.block_size,
                dtype='int16'
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
            self.input_stream.stop()
            self.input_stream.close()
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
        logger.info("Audio Engine stopped")

    def _input_callback(self, indata, frames, time, status):
        if status:
            logger.warning("Audio Input status", status=status)
        if self.send_callback:
            # indata is numpy array (int16)
            # convert to bytes
            data_bytes = indata.tobytes()
            self.send_callback(data_bytes)

    def _output_callback(self, outdata, frames, time, status):
        if status:
            logger.warning("Audio Output status", status=status)
        if len(self.jitter_buffer) > 0:
            data = self.jitter_buffer.popleft()
            # Ensure data matches outdata shape
            outdata[:len(data)] = np.frombuffer(data, dtype='int16').reshape(-1, self.channels)
        else:
            outdata.fill(0)

    def receive_audio(self, data):
        self.jitter_buffer.append(data)
