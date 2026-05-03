import pytest
import numpy as np
from client.audio.engine import AudioEngine, OPUS_AVAILABLE, VAD_AVAILABLE

_SILENCE_PCM = np.zeros((320, 1), dtype="int16")   # indata shape for duplex callback


def test_audio_engine_reordering():
    """Jitter buffer must play packets in sequence order even when received out of order."""
    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    if engine.encoder is None:
        pytest.skip("Opus encoder not initialised")

    pcm = np.zeros(320, dtype="int16").tobytes()
    p1 = engine.encoder.encode(pcm, 320)
    p2 = engine.encoder.encode(pcm, 320)
    p3 = engine.encoder.encode(pcm, 320)

    # Deliver out of order
    engine.receive_audio(2, p2)
    engine.receive_audio(1, p1)
    engine.receive_audio(3, p3)

    # Three packets → startup threshold reached → _next_seq initialised to min = 1
    assert engine._next_seq == 1

    outdata = np.zeros((320, 1), dtype="int16")

    engine._duplex_callback(_SILENCE_PCM, outdata, 320, None, None)
    assert engine._next_seq == 2   # consumed seq=1

    engine._duplex_callback(_SILENCE_PCM, outdata, 320, None, None)
    assert engine._next_seq == 3   # consumed seq=2

    engine._duplex_callback(_SILENCE_PCM, outdata, 320, None, None)
    assert engine._next_seq == 4   # consumed seq=3


def test_jitter_buffer_resync():
    """When _next_seq drifts far behind the buffer, it should jump forward."""
    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    if engine.encoder is None:
        pytest.skip("Opus encoder not initialised")

    pcm = np.zeros(320, dtype="int16").tobytes()

    # Pre-fill startup packets 0-2 to initialise _next_seq = 0
    for i in range(3):
        engine.receive_audio(i, engine.encoder.encode(pcm, 320))
    assert engine._next_seq == 0

    # Simulate a big gap: drain the buffer manually and advance _next_seq
    engine._play_buf.clear()
    engine._next_seq = 5    # pretend 5 PLC frames were played

    # New packets arrive far ahead (seq 30+)
    for i in range(30, 33):
        engine.receive_audio(i, engine.encoder.encode(pcm, 320))

    outdata = np.zeros((320, 1), dtype="int16")
    # The resync threshold is _BUF_RESYNC = 20; 30 > 5+20, so it should jump
    engine._duplex_callback(_SILENCE_PCM, outdata, 320, None, None)
    assert engine._next_seq == 31  # resynced to 30, then incremented


def test_overflow_drops_oldest():
    """When more than _BUF_MAX packets arrive, the oldest are dropped."""
    engine = AudioEngine()
    limit = engine._BUF_MAX

    for i in range(limit + 10):
        engine.receive_audio(i, b"x")

    assert len(engine._play_buf) == limit
    # Oldest keys are gone; newest remain
    assert min(engine._play_buf) == 10


def test_opus_codec_integrity():
    """Encode→decode round-trip: decoded length matches raw and signal has energy."""
    if not OPUS_AVAILABLE:
        pytest.skip("Opus C library (libopus) not found on system.")

    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    if engine.encoder is None or engine.decoder is None:
        pytest.skip("Opus codec failed to initialise")

    t = np.linspace(0, 0.02, 320, endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 10000).astype("int16")
    raw_pcm = sine.tobytes()

    encoded = engine.encoder.encode(raw_pcm, 320)
    assert len(encoded) < len(raw_pcm), "Encoded packet should be smaller than raw PCM"

    decoded_pcm = engine.decoder.decode(encoded, 320)
    assert len(decoded_pcm) == len(raw_pcm), "Decoded length mismatch"

    decoded_arr = np.frombuffer(decoded_pcm, dtype="int16")
    rms = np.sqrt(np.mean(decoded_arr.astype(np.float32) ** 2))
    assert rms > 100, f"Decoded audio is near-silent (RMS={rms:.1f})"


def test_vad_disabled_by_default():
    """VAD is intentionally off so calls work even when neither side is speaking."""
    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    assert engine.vad is None, "VAD should be disabled by default"
