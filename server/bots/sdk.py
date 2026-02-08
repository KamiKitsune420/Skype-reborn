import asyncio
import httpx
import websockets
import json
import struct
import socket
import threading
from uuid import UUID
from shared.models import Envelope, MessageType, ChatMessagePayload, CallSignalPayload, ChatTypingPayload, PresenceUpdatePayload, UserStatus

class BotSDK:
    def __init__(self, server_url: str):
        self.server_url = server_url 
        self.ws_url = server_url.replace("http", "ws")
        self.token = None
        self.user_id = None
        self.ws = None
        self.handlers = {}
        
        self.udp_addr = ("127.0.0.1", 9000)
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_handlers = [] # list of callbacks(session_id, data)

    async def login(self, username, password):
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(f"{self.server_url}/login", json={"username": username, "password": password})
                if resp.status_code == 200:
                    data = resp.json()
                    self.token = data["token"]
                    self.user_id = data["user_id"]
                    return True
            except Exception as e:
                print(f"BotSDK Login Error: {e}")
            return False

    def on_event(self, event_type: MessageType):
        def decorator(func):
            self.handlers[event_type] = func
            return func
        return decorator

    def on_udp_audio(self, func):
        self.udp_handlers.append(func)
        return func

    async def connect(self):
        # 1. Get ticket
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = await client.post(f"{self.server_url}/ws/ticket", headers=headers)
            if resp.status_code != 200:
                print("BotSDK: Failed to get WS ticket")
                return False
            ticket = resp.json()["ticket"]

        # 2. Connect
        url = f"{self.ws_url}/ws/{ticket}"
        self.ws = await websockets.connect(url)
        asyncio.create_task(self._receive_loop())
        
        # 3. UDP Setup
        self.send_udp_packet(UUID(int=0), b"HELLO:" + self.user_id.encode())
        threading.Thread(target=self._udp_receive_loop, daemon=True).start()
        
        return True

    async def _receive_loop(self):
        async for message in self.ws:
            try:
                envelope = Envelope.model_validate_json(message)
                if envelope.type in self.handlers:
                    await self.handlers[envelope.type](envelope)
            except Exception as e:
                print(f"BotSDK WS Error: {e}")

    def _udp_receive_loop(self):
        while True:
            try:
                data, addr = self.udp_socket.recvfrom(2048)
                if len(data) >= 25:
                    session_id = UUID(bytes=data[:16]).hex
                    audio_data = data[25:]
                    for handler in self.udp_handlers:
                        handler(session_id, audio_data)
            except Exception:
                pass

    async def send_envelope(self, envelope: Envelope):
        if self.ws:
            await self.ws.send(envelope.model_dump_json())

    async def send_message(self, target_id: str, content: str):
        payload = ChatMessagePayload(conversation_id=target_id, sender_id=self.user_id, content=content)
        envelope = Envelope(type=MessageType.CHAT_SEND, payload=payload.model_dump())
        await self.send_envelope(envelope)

    async def update_presence(self, status: UserStatus):
        payload = PresenceUpdatePayload(user_id=self.user_id, status=status)
        envelope = Envelope(type=MessageType.PRESENCE_UPDATE, payload=payload.model_dump())
        await self.send_envelope(envelope)

    def send_udp_packet(self, session_id: UUID, payload: bytes, seq=0):
        header = session_id.bytes
        header += struct.pack("!H", seq)
        header += struct.pack("!I", 0)
        header += struct.pack("!B", 2)
        header += struct.pack("!H", len(payload))
        self.udp_socket.sendto(header + payload, self.udp_addr)

    async def run_forever(self):
        while True:
            await asyncio.sleep(1)