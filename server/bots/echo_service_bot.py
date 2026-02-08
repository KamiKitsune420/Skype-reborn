import asyncio
import wave
import os
import struct
from uuid import UUID
from server.bots.sdk import BotSDK
from shared.models import Envelope, MessageType, CallSignalPayload, UserStatus

class EchoServiceBot:
    def __init__(self, bot_sdk: BotSDK):
        self.bot = bot_sdk
        self.active_calls = {} # session_id -> {recorded_data, is_recording, seq}

    async def start(self):
        @self.bot.on_event(MessageType.CHAT_RECEIVE)
        async def on_message(envelope: Envelope):
            content = envelope.payload.get("content", "")
            sender_id = envelope.payload.get("sender_id", "unknown")
            if sender_id == self.bot.user_id: return
            print(f"EchoBot: Received text '{content}' from {sender_id}")
            await self.bot.send_message(sender_id, f"Echo: {content}")

        @self.bot.on_event(MessageType.CALL_INITIATE)
        async def on_call_init(envelope: Envelope):
            payload = CallSignalPayload(**envelope.payload)
            session_id = payload.session_id
            user_id = payload.sender_id
            
            print(f"EchoBot: Incoming call from {user_id}")
            
            # 1. Connecting signal
            await self.bot.send_envelope(Envelope(
                type=MessageType.CALL_CONNECTING,
                payload=CallSignalPayload(session_id=session_id, target_id=user_id, sender_id=self.bot.user_id).model_dump()
            ))
            await asyncio.sleep(1)
            
            # 2. Accept call
            await self.bot.send_envelope(Envelope(
                type=MessageType.CALL_ACCEPT,
                payload=CallSignalPayload(session_id=session_id, target_id=user_id, sender_id=self.bot.user_id).model_dump()
            ))
            
            self.active_calls[session_id] = {
                "recorded_data": [],
                "is_recording": False,
                "seq": 0,
                "user_id": user_id,
                "is_active": True
            }
            
            asyncio.create_task(self.run_echo_sequence(session_id))

        @self.bot.on_event(MessageType.CALL_HANGUP)
        async def on_hangup(envelope: Envelope):
            payload = CallSignalPayload(**envelope.payload)
            if payload.session_id in self.active_calls:
                self.active_calls[payload.session_id]["is_active"] = False

        @self.bot.on_udp_audio
        def on_audio(session_id, data):
            if session_id in self.active_calls:
                call = self.active_calls[session_id]
                if call["is_recording"]:
                    call["recorded_data"].append(data)

    async def run_echo_sequence(self, session_id):
        call = self.active_calls[session_id]
        user_id = call["user_id"]
        
        # Intro
        await self.play_wav(session_id, "assets/sounds/echo_intro.wav")
        # Beep
        await self.play_wav(session_id, "assets/sounds/echo_beep.wav")
        # Record
        call["is_recording"] = True
        await asyncio.sleep(8)
        call["is_recording"] = False
        # Beep
        await self.play_wav(session_id, "assets/sounds/echo_beep.wav")
        
        # Playback
        for chunk in call["recorded_data"]:
            if not call["is_active"]: break
            self.send_audio(session_id, chunk)
            await asyncio.sleep(0.02)
            
        # Outro
        await self.play_wav(session_id, "assets/sounds/echo_outro.wav")
        
        # Hangup
        if call["is_active"]:
            await self.bot.send_envelope(Envelope(
                type=MessageType.CALL_HANGUP,
                payload=CallSignalPayload(session_id=session_id, target_id=user_id, sender_id=self.bot.user_id).model_dump()
            ))
        
        if session_id in self.active_calls:
            del self.active_calls[session_id]

    async def play_wav(self, session_id, file_path):
        if not os.path.exists(file_path): return
        call = self.active_calls.get(session_id)
        if not call or not call["is_active"]: return
        
        with wave.open(file_path, 'rb') as wf:
            chunk_size = 320
            data = wf.readframes(chunk_size)
            while data and call["is_active"]:
                self.send_audio(session_id, data)
                await asyncio.sleep(0.02)
                data = wf.readframes(chunk_size)

    def send_audio(self, session_id, data):
        call = self.active_calls.get(session_id)
        if call:
            self.bot.send_udp_packet(UUID(session_id), data, seq=call["seq"])
            call["seq"] = (call["seq"] + 1) % 65536

async def main():
    bot_sdk = BotSDK("http://127.0.0.1:8000")
    # Wait a bit for server to be ready
    await asyncio.sleep(2)
    
    if not await bot_sdk.login("echo_service", "botpassword"):
        print("EchoBot: Login failed. Is it registered?")
        return
    
    echo_bot = EchoServiceBot(bot_sdk)
    await bot_sdk.connect()
    await echo_bot.start()
    print("Echo Service Bot is running...")
    await bot_sdk.run_forever()

if __name__ == "__main__":
    asyncio.run(main())
