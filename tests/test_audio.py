import pytest
import numpy as np
from client.audio.engine import AudioEngine, OPUS_AVAILABLE, VAD_AVAILABLE


def test_audio_engine_reordering():
    """Jitter buffer must correctly reorder out-of-order packets."""
    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    if engine.encoder is None:
        pytest.skip("Opus encoder not initialised")

    pcm = np.zeros(320, dtype="int16").tobytes()
    p1 = engine.encoder.encode(pcm, 320)
    p2 = engine.encoder.encode(pcm, 320)
    p3 = engine.encoder.encode(pcm, 320)

    engine.receive_audio(2, p2)
    engine.receive_audio(1, p1)
    engine.receive_audio(3, p3)

    outdata = np.zeros((320, 1), dtype="int16")

    engine._output_callback(outdata, 320, None, None)
    assert engine.next_expected_seq == 2

    engine._output_callback(outdata, 320, None, None)
    assert engine.next_expected_seq == 3

    engine._output_callback(outdata, 320, None, None)
    assert engine.next_expected_seq == 4


def test_opus_codec_integrity():
    """Encode→decode round-trip: output length matches and signal has energy."""
    if not OPUS_AVAILABLE:
        pytest.skip("Opus C library (libopus) not found on system.")

    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    if engine.encoder is None or engine.decoder is None:
        pytest.skip("Opus codec failed to initialise")

    t = np.linspace(0, 0.02, 320, endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 10000).astype("int16")
    raw_pcm = sine.tobytes()

    encoded = engine.encoder.encode(raw_pcm, 320)
    # Lossy codec — compressed size should be smaller than raw PCM
    assert len(encoded) < len(raw_pcm), "Encoded packet larger than raw PCM"

    decoded_pcm = engine.decoder.decode(encoded, 320)
    assert len(decoded_pcm) == len(raw_pcm), "Decoded length mismatch"

    decoded_arr = np.frombuffer(decoded_pcm, dtype="int16")
    # Opus VOIP mode is lossy — just verify the output has audio energy
    rms = np.sqrt(np.mean(decoded_arr.astype(np.float32) ** 2))
    assert rms > 100, f"Decoded audio is near-silent (RMS={rms:.1f})"


def test_vad_silence_detection():
    """VAD must return False for silence."""
    if not VAD_AVAILABLE:
        pytest.skip("webrtcvad not installed.")

    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    if engine.vad is None:
        pytest.skip("VAD failed to initialise.")

    silence = np.zeros(320, dtype="int16").tobytes()
    assert engine.vad.is_speech(silence, 16000) == False
