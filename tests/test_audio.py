import pytest
import numpy as np
from client.audio.engine import AudioEngine, OPUS_AVAILABLE

def test_audio_engine_reordering():
    """Test that the jitter buffer correctly reorders out-of-order packets."""
    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    
    pcm = np.zeros(320, dtype="int16").tobytes()
    packet1 = engine.encoder.encode(pcm, 320)
    packet2 = engine.encoder.encode(pcm, 320)
    packet3 = engine.encoder.encode(pcm, 320)

    # Push to jitter buffer OUT OF ORDER
    engine.receive_audio(2, packet2)
    engine.receive_audio(1, packet1)
    engine.receive_audio(3, packet3)

    outdata = np.zeros((320, 1), dtype="int16")
    
    # Turn 1: Should trigger initialization and pop seq 1
    engine._output_callback(outdata, 320, None, None)
    assert engine.next_expected_seq == 2
    
    # Turn 2: Should pop seq 2
    engine._output_callback(outdata, 320, None, None)
    assert engine.next_expected_seq == 3

    # Turn 3: Should pop seq 3
    engine._output_callback(outdata, 320, None, None)
    assert engine.next_expected_seq == 4

def test_opus_codec_integrity():
    """Verify that encoding and decoding raw PCM results in valid audio."""
    if not OPUS_AVAILABLE:
        pytest.skip("Opus C library (libopus) not found on system.")

    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    
    # Create a 440Hz sine wave chunk
    t = np.linspace(0, 0.02, 320, endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 10000).astype("int16")
    raw_pcm = sine.tobytes()
    
    # Encode
    encoded = engine.encoder.encode(raw_pcm, 320)
    assert len(encoded) < len(raw_pcm) # Should be compressed
    
    # Decode
    decoded_pcm = engine.decoder.decode(encoded, 320)
    assert len(decoded_pcm) == len(raw_pcm)
    
    # Check similarity
    decoded_arr = np.frombuffer(decoded_pcm, dtype="int16")
    correlation = np.corrcoef(sine, decoded_arr)[0, 1]
    assert correlation > 0.95

def test_vad_silence_detection():
    """Verify VAD correctly identifies silence vs speech."""
    engine = AudioEngine(sample_rate=16000, channels=1, block_size=320)
    
    # Silence (all zeros)
    silence = np.zeros(320, dtype="int16").tobytes()
    # webrtcvad returns False for silence
    assert engine.vad.is_speech(silence, 16000) == False
    
    # Noise/Speech (Simulated)
    speech = (np.random.randn(320) * 5000).astype("int16").tobytes()
    assert engine.vad.is_speech(speech, 16000) == True
