import asyncio
import httpx
import websockets
import struct
import socket
import threading
import structlog
from uuid import UUID
from shared.models import Envelope, MessageType, ChatMessagePayload, CallSignalPayload, ChatTypingPayload, PresenceUpdatePayload, UserStatus

logger = structlog.get_logger()


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
        self.udp_handlers = []  # list of callbacks(session_id, data)
        self._running = False

    async def login(self, username: str, password: str) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.server_url}/login",
                    json={"username": username, "password": password},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self.token = data["token"]
                    self.user_id = data["user_id"]
                    return True
                logger.warning("BotSDK: login failed", status=resp.status_code, body=resp.text)
            except Exception as e:
                logger.error("BotSDK: login error", error=str(e))
        return False

    # ── Event handler registration ────────────────────────────────────

    def on_event(self, event_type: MessageType):
        """Decorator — register an async handler for a message type."""
        def decorator(func):
            self.handlers[event_type] = func
            return func
        return decorator

    def on_udp_audio(self, func):
        """Register a callback(session_id: str, data: bytes) for incoming UDP audio."""
        self.udp_handlers.append(func)
        return func

    # ── Connection ───────────────────────────────────────────────────

    async def connect(self) -> bool:
        # 1. Get one-time WebSocket ticket
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.server_url}/ws/ticket",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
            if resp.status_code != 200:
                logger.warning("BotSDK: WS ticket request failed", status=resp.status_code)
                return False
            ticket = resp.json()["ticket"]
        except Exception as e:
            logger.error("BotSDK: error getting WS ticket", error=str(e))
            return False

        # 2. Open WebSocket
        url = f"{self.ws_url}/ws/{ticket}"
        try:
            self.ws = await websockets.connect(url)
        except Exception as e:
            logger.error("BotSDK: WebSocket connection failed", error=str(e))
            return False

        self._running = True
        asyncio.create_task(self._receive_loop())

        # 3. UDP handshake + receive thread
        self.send_udp_packet(UUID(int=0), b"HELLO:" + self.user_id.encode())
        threading.Thread(target=self._udp_receive_loop, daemon=True).start()

        return True

    # ── WebSocket receive loop ────────────────────────────────────────

    async def _receive_loop(self):
        try:
            async for message in self.ws:
                try:
                    envelope = Envelope.model_validate_json(message)
                    if envelope.type in self.handlers:
                        await self.handlers[envelope.type](envelope)
                except Exception as e:
                    logger.error("BotSDK: error handling message", error=str(e))
        except websockets.ConnectionClosed as e:
            logger.info("BotSDK: WebSocket closed", reason=str(e))
        except Exception as e:
            logger.error("BotSDK: unexpected error in receive loop", error=str(e))
        finally:
            self._running = False
            logger.info("BotSDK: receive loop exited")

    # ── UDP receive loop (runs in a daemon thread) ────────────────────

    def _udp_receive_loop(self):
        self.udp_socket.settimeout(1.0)  # Allow checking _running periodically
        while self._running:
            try:
                data, _ = self.udp_socket.recvfrom(2048)
                if len(data) < 25:
                    continue
                session_id = UUID(bytes=data[:16]).hex
                audio_data = data[25:]
                for handler in self.udp_handlers:
                    handler(session_id, audio_data)
            except socket.timeout:
                continue  # Normal — check _running and loop
            except OSError:
                break  # Socket was closed during shutdown
            except Exception as e:
                logger.error("BotSDK: UDP receive error", error=str(e))

    # ── Send helpers ─────────────────────────────────────────────────

    async def send_envelope(self, envelope: Envelope):
        if self.ws and not self.ws.closed:
            try:
                await self.ws.send(envelope.model_dump_json())
            except websockets.ConnectionClosed:
                logger.warning("BotSDK: cannot send, WebSocket is closed")

    async def send_message(self, target_id: str, content: str):
        payload = ChatMessagePayload(
            conversation_id=target_id, sender_id=self.user_id, content=content
        )
        await self.send_envelope(Envelope(type=MessageType.CHAT_SEND, payload=payload.model_dump()))

    async def update_presence(self, status: UserStatus):
        payload = PresenceUpdatePayload(user_id=self.user_id, status=status)
        await self.send_envelope(Envelope(type=MessageType.PRESENCE_UPDATE, payload=payload.model_dump()))

    def send_udp_packet(self, session_id: UUID, payload: bytes, seq: int = 0, codec: int = 3):
        header = session_id.bytes
        header += struct.pack("!H", seq)
        header += struct.pack("!I", 0)
        header += struct.pack("!B", codec)
        header += struct.pack("!H", len(payload))
        try:
            self.udp_socket.sendto(header + payload, self.udp_addr)
        except OSError as e:
            logger.error("BotSDK: UDP send error", error=str(e))

    # ── Lifecycle ────────────────────────────────────────────────────

    async def run_forever(self):
        """Keep the bot alive while the WebSocket is connected."""
        while self._running:
            await asyncio.sleep(1)
        logger.info("BotSDK: run_forever exiting, connection lost")

    async def close(self):
        """Cleanly shut down the bot."""
        self._running = False
        try:
            self.udp_socket.close()
        except Exception:
            pass
        if self.ws:
            await self.ws.close()
