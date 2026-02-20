import asyncio
import wave
import os
import structlog
from uuid import UUID
from server.bots.sdk import BotSDK
from shared.models import Envelope, MessageType, CallSignalPayload, UserStatus

logger = structlog.get_logger()


class EchoServiceBot:
    def __init__(self, bot_sdk: BotSDK):
        self.bot = bot_sdk
        self.active_calls: dict = {}  # session_id -> call state dict

    def start(self):
        """Register all event handlers. Call this BEFORE bot_sdk.connect()."""

        @self.bot.on_event(MessageType.CHAT_RECEIVE)
        async def on_message(envelope: Envelope):
            sender_id = envelope.payload.get("sender_id", "")
            content = envelope.payload.get("content", "")
            if sender_id == self.bot.user_id:
                return  # Ignore our own echoes
            logger.info("EchoBot: chat message received", sender_id=sender_id, content=content)
            await self.bot.send_message(sender_id, f"Echo: {content}")

        @self.bot.on_event(MessageType.CALL_INITIATE)
        async def on_call_init(envelope: Envelope):
            payload = CallSignalPayload(**envelope.payload)
            session_id = payload.session_id
            user_id = payload.sender_id
            logger.info("EchoBot: incoming call", from_user_id=user_id)

            # Signal connecting, then accept after a brief pause
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
            await self.play_wav(session_id, "assets/sounds/echo_intro.wav")
            await self.play_wav(session_id, "assets/sounds/echo_beep.wav")

            # Record for 8 seconds
            call["is_recording"] = True
            await asyncio.sleep(8)
            call["is_recording"] = False

            await self.play_wav(session_id, "assets/sounds/echo_beep.wav")

            # Play back the recording
            for chunk in call["recorded_data"]:
                if not call["is_active"]:
                    break
                self._send_audio(session_id, chunk)
                await asyncio.sleep(0.02)

            await self.play_wav(session_id, "assets/sounds/echo_outro.wav")

            if call["is_active"]:
                await self.bot.send_envelope(Envelope(
                    type=MessageType.CALL_HANGUP,
                    payload=CallSignalPayload(
                        session_id=session_id, target_id=user_id, sender_id=self.bot.user_id
                    ).model_dump(),
                ))
        except Exception as e:
            logger.error("EchoBot: error in echo sequence", session_id=session_id, error=str(e))
        finally:
            # Always clean up, even if something crashes mid-call
            self.active_calls.pop(session_id, None)

    async def play_wav(self, session_id: str, file_path: str):
        if not os.path.exists(file_path):
            return
        call = self.active_calls.get(session_id)
        if not call or not call["is_active"]:
            return

        with wave.open(file_path, "rb") as wf:
            framerate = wf.getframerate()
            chunk_size = 320
            # Calculate correct sleep duration from the WAV's actual sample rate.
            # Old code hard-coded 0.02 s which was wrong for anything other than 16 kHz.
            chunk_duration = chunk_size / framerate

            data = wf.readframes(chunk_size)
            while data and call["is_active"]:
                self._send_audio(session_id, data)
                await asyncio.sleep(chunk_duration)
                data = wf.readframes(chunk_size)

    def _send_audio(self, session_id: str, data: bytes):
        call = self.active_calls.get(session_id)
        if call:
            self.bot.send_udp_packet(UUID(session_id), data, seq=call["seq"])
            call["seq"] = (call["seq"] + 1) % 65536


async def main():
    server_url = os.environ.get("SKYPE_SERVER_URL", "http://127.0.0.1:8000")
    bot_sdk = BotSDK(server_url)

    # Give the server a moment to fully start before connecting
    await asyncio.sleep(2)

    if not await bot_sdk.login("echo_service", "botpassword"):
        logger.error("EchoBot: login failed, run scripts/init_bots.py to register the bot first")
        return

    echo_bot = EchoServiceBot(bot_sdk)

    # Register handlers BEFORE connecting so no messages are missed
    echo_bot.start()

    if not await bot_sdk.connect():
        logger.error("EchoBot: failed to connect to server")
        return

    logger.info("Echo Service Bot is running")
    await bot_sdk.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
