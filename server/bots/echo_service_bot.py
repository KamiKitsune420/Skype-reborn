import asyncio
import wave
import os
import sys
import structlog
import numpy as np

# On Windows, patch ctypes so opuslib finds the bundled libopus.dll.
# On Linux/macOS, opuslib discovers the system library automatically.
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
    class OpusEncoder:
        def __init__(self, *args, **kwargs): pass
        def encode(self, pcm, frame_size): return pcm
    class OpusDecoder:
        def __init__(self, *args, **kwargs): pass
        def decode(self, data, frame_size): return data if data else b'\x00' * (frame_size * 2)

from pathlib import Path
from uuid import UUID

# Sounds live next to the bot code, not in the client's assets folder.
_SOUNDS_DIR = Path(__file__).parent / "sounds"

def _sound(filename: str) -> str:
    """Return the absolute path to a bot sound file."""
    return str(_SOUNDS_DIR / filename)
from server.bots.sdk import BotSDK
from shared.models import Envelope, MessageType, CallSignalPayload, UserStatus

logger = structlog.get_logger()

# Audio constants matching the client's AudioEngine
_SAMPLE_RATE  = 16000
_CHANNELS     = 1
_CHUNK_FRAMES = 320          # 20ms at 16kHz
_CHUNK_BYTES  = _CHUNK_FRAMES * _CHANNELS * 2   # 16-bit PCM = 640 bytes


class EchoServiceBot:
    def __init__(self, bot_sdk: BotSDK):
        self.bot = bot_sdk
        self.active_calls: dict = {}  # session_id -> call state dict
        self._wav_cache: dict  = {}   # file_path -> resampled 16kHz mono PCM bytes
        try:
            self.encoder = OpusEncoder(_SAMPLE_RATE, _CHANNELS, 'voip')
            self.decoder = OpusDecoder(_SAMPLE_RATE, _CHANNELS)
        except Exception as e:
            logger.error("EchoBot: failed to init Opus codec", error=str(e))
            self.encoder = None
            self.decoder = None

    def start(self):
        """Register all event handlers. Call this BEFORE bot_sdk.connect()."""

        @self.bot.on_event(MessageType.CHAT_RECEIVE)
        async def on_message(envelope: Envelope):
            sender_id = envelope.payload.get("sender_id", "")
            content = envelope.payload.get("content", "")
            if sender_id == self.bot.user_id:
                return
            logger.info("EchoBot: chat message received", sender_id=sender_id, content=content)
            await self.bot.send_message(sender_id, f"Echo: {content}")

        @self.bot.on_event(MessageType.CALL_INITIATE)
        async def on_call_init(envelope: Envelope):
            payload = CallSignalPayload(**envelope.payload)
            session_id = payload.session_id
            user_id = payload.sender_id
            logger.info("EchoBot: incoming call", from_user_id=user_id)

            await self.bot.send_envelope(Envelope(
                type=MessageType.CALL_CONNECTING,
                payload=CallSignalPayload(
                    session_id=session_id, target_id=user_id, sender_id=self.bot.user_id
                ).model_dump(),
            ))
            await asyncio.sleep(1)

            await self.bot.send_envelope(Envelope(
                type=MessageType.CALL_ACCEPT,
                payload=CallSignalPayload(
                    session_id=session_id, target_id=user_id, sender_id=self.bot.user_id
                ).model_dump(),
            ))

            self.active_calls[session_id] = {
                "recorded_data": [],
                "is_recording": False,
                "seq": 0,
                "user_id": user_id,
                "is_active": True,
            }
            asyncio.create_task(self.run_echo_sequence(session_id))

        @self.bot.on_event(MessageType.CALL_HANGUP)
        async def on_hangup(envelope: Envelope):
            payload = CallSignalPayload(**envelope.payload)
            if payload.session_id in self.active_calls:
                self.active_calls[payload.session_id]["is_active"] = False

        @self.bot.on_udp_audio
        def on_audio(session_id: str, data: bytes):
            call = self.active_calls.get(session_id)
            if call and call["is_recording"]:
                call["recorded_data"].append(data)

    # ── Echo call sequence ────────────────────────────────────────────

    async def run_echo_sequence(self, session_id: str):
        call = self.active_calls.get(session_id)
        if not call:
            return

        user_id = call["user_id"]
        try:
            await self.play_wav(session_id, _sound("echo_intro.wav"))
            await self.play_wav(session_id, _sound("echo_beep.wav"))

            # Record for 5 seconds while sending silent frames so the client's
            # jitter buffer keeps its sequence numbers in sync with ours.
            # Without this, next_expected_seq drifts 250 ahead during silence
            # and every packet after the pause is discarded as "too late".
            call["is_recording"] = True
            await self._send_silence(session_id, seconds=5)
            call["is_recording"] = False

            await self.play_wav(session_id, _sound("echo_beep.wav"))

            # Play back the recorded audio with drift compensation.
            # Decode each recorded Opus frame (from the client's encoder) and
            # re-encode it with the bot's encoder so the client's decoder sees
            # a continuous, consistent stream — avoids codec-state glitching.
            if call["recorded_data"]:
                loop    = asyncio.get_running_loop()
                t_start = loop.time()
                for idx, chunk in enumerate(call["recorded_data"], start=1):
                    if not call["is_active"]:
                        break
                    if self.encoder and self.decoder:
                        try:
                            pcm   = self.decoder.decode(chunk, _CHUNK_FRAMES)
                            chunk = self.encoder.encode(pcm, _CHUNK_FRAMES)
                        except Exception:
                            pass  # fall back to the original chunk
                    self._send_audio(session_id, chunk)
                    next_send = t_start + idx * 0.02
                    delay = next_send - loop.time()
                    if delay > 0:
                        await asyncio.sleep(delay)

            # Beep signals end of playback, then play the finish sound
            await self.play_wav(session_id, _sound("echo_beep.wav"))
            await self.play_wav(session_id, _sound("echo_outro.wav"))

        except Exception as e:
            logger.error("EchoBot: error in echo sequence", session_id=session_id, error=str(e))
        finally:
            # Always hang up, even if an exception cut the sequence short
            if self.active_calls.get(session_id, {}).get("is_active"):
                try:
                    await self.bot.send_envelope(Envelope(
                        type=MessageType.CALL_HANGUP,
                        payload=CallSignalPayload(
                            session_id=session_id, target_id=user_id,
                            sender_id=self.bot.user_id,
                        ).model_dump(),
                    ))
                except Exception:
                    pass
            self.active_calls.pop(session_id, None)

    async def preload_wavs(self):
        """Resample all echo WAV files into the cache before any calls arrive.
        This keeps play_wav free of executor waits during live calls so the
        client's jitter buffer never drains at a WAV transition."""
        paths = [
            _sound("echo_intro.wav"),
            _sound("echo_beep.wav"),
            _sound("echo_outro.wav"),
        ]
        loop = asyncio.get_running_loop()
        for path in paths:
            if not os.path.exists(path):
                logger.warning("EchoBot: preload skipped — file not found", path=path)
                continue
            raw = await loop.run_in_executor(None, self._resample_wav, path)
            if raw:
                self._wav_cache[path] = raw
                logger.info("EchoBot: preloaded WAV", path=path, kb=len(raw) // 1024)

    def _resample_wav(self, file_path: str) -> bytes | None:
        """Synchronous: read and resample a WAV file to 16kHz mono PCM bytes."""
        try:
            with wave.open(file_path, "rb") as wf:
                framerate  = wf.getframerate()
                n_channels = wf.getnchannels()
                raw        = wf.readframes(wf.getnframes())
            samples = np.frombuffer(raw, dtype=np.int16)
            if n_channels > 1:
                samples = samples.reshape(-1, n_channels).mean(axis=1).astype(np.int16)
            if framerate != _SAMPLE_RATE:
                n_out = int(len(samples) * _SAMPLE_RATE / framerate)
                samples = np.interp(
                    np.linspace(0, len(samples) - 1, n_out),
                    np.arange(len(samples)),
                    samples,
                ).astype(np.int16)
            return samples.tobytes()
        except Exception as e:
            logger.error("EchoBot: WAV resample failed", path=file_path, error=str(e))
            return None

    async def play_wav(self, session_id: str, file_path: str):
        if not os.path.exists(file_path):
            logger.warning("EchoBot: WAV file not found", path=file_path)
            return
        call = self.active_calls.get(session_id)
        if not call or not call["is_active"]:
            return

        # Resample in a thread pool so numpy never blocks the asyncio event loop.
        # Cache the result — the beep is played three times per call.
        loop = asyncio.get_running_loop()
        raw_16k = self._wav_cache.get(file_path)
        if raw_16k is None:
            raw_16k = await loop.run_in_executor(None, self._resample_wav, file_path)
            if raw_16k is None:
                return
            self._wav_cache[file_path] = raw_16k

        # Re-check after the await — call may have ended while we were resampling
        call = self.active_calls.get(session_id)
        if not call or not call["is_active"]:
            return

        # Stream 320-sample (20ms) chunks with drift compensation so
        # asyncio.sleep imprecision doesn't gradually drain the client's jitter buffer.
        raw_16k   = self._wav_cache[file_path]
        offset    = 0
        chunk_idx = 0
        t_start   = loop.time()

        while offset < len(raw_16k) and call["is_active"]:
            chunk = raw_16k[offset : offset + _CHUNK_BYTES]
            offset    += _CHUNK_BYTES
            chunk_idx += 1
            # Pad the final short chunk to a full frame
            if len(chunk) < _CHUNK_BYTES:
                chunk = chunk + b'\x00' * (_CHUNK_BYTES - len(chunk))

            if self.encoder:
                try:
                    encoded = self.encoder.encode(chunk, _CHUNK_FRAMES)
                    self._send_audio(session_id, encoded)
                except Exception as e:
                    logger.error("EchoBot: encode error", error=str(e))
                    self._send_audio(session_id, chunk)
            else:
                self._send_audio(session_id, chunk)

            # Sleep only as long as needed to hit the next scheduled send time.
            # This compensates for accumulated timer drift across iterations.
            next_send = t_start + chunk_idx * 0.02
            delay = next_send - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)

    async def _send_silence(self, session_id: str, seconds: float):
        """Send Opus-encoded silence for `seconds` to keep the client's
        jitter buffer sequence numbers in sync during a deliberate pause."""
        call        = self.active_calls.get(session_id)
        silence_pcm = b'\x00' * _CHUNK_BYTES
        n_chunks    = int(seconds * 50)   # 50 chunks per second at 20 ms each
        loop        = asyncio.get_running_loop()
        t_start     = loop.time()
        for idx in range(1, n_chunks + 1):
            if not call or not call["is_active"]:
                break
            if self.encoder:
                try:
                    encoded = self.encoder.encode(silence_pcm, _CHUNK_FRAMES)
                except Exception:
                    encoded = silence_pcm
            else:
                encoded = silence_pcm
            self._send_audio(session_id, encoded)
            next_send = t_start + idx * 0.02
            delay = next_send - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)

    def _send_audio(self, session_id: str, data: bytes):
        call = self.active_calls.get(session_id)
        if call:
            self.bot.send_udp_packet(UUID(session_id), data, seq=call["seq"])
            call["seq"] = (call["seq"] + 1) % 65536


async def main():
    server_url = os.environ.get("SKYPE_SERVER_URL", "http://127.0.0.1:9433")
    bot_sdk = BotSDK(server_url, messageable=False)

    await asyncio.sleep(2)

    if not await bot_sdk.login("echo_service", "botpassword"):
        logger.error("EchoBot: login failed, run scripts/init_bots.py to register the bot first")
        return

    echo_bot = EchoServiceBot(bot_sdk)
    echo_bot.start()

    if not await bot_sdk.connect():
        logger.error("EchoBot: failed to connect to server")
        return

    # Pre-load all WAV files so no executor wait occurs during live calls
    await echo_bot.preload_wavs()

    logger.info("Echo Service Bot is running")
    await bot_sdk.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
