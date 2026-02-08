import asyncio
import websockets
import json
import structlog
from shared.models import Envelope, MessageType

logger = structlog.get_logger()

class WSClient:
    def __init__(self, base_url: str, api_client):
        # base_url should be ws://... or wss://...
        self.base_url = base_url
        self.api_client = api_client
        self.websocket = None
        self.on_message_callback = None
        self._receive_task = None

    async def connect(self):
        # 1. Get ticket from API
        try:
            resp = await self.api_client.client.post("/ws/ticket")
            if resp.status_code != 200:
                logger.error("Failed to get WS ticket")
                return False
            ticket = resp.json()["ticket"]
        except Exception as e:
            logger.error("Error getting WS ticket", error=str(e))
            return False

        # 2. Connect with ticket
        url = f"{self.base_url}/ws/{ticket}"
        try:
            self.websocket = await websockets.connect(url)
            logger.info("Connected to WebSocket with ticket")
            self._receive_task = asyncio.create_task(self._receive_loop())
            return True
        except Exception as e:
            logger.error("WebSocket connection failed", error=str(e))
            return False

    async def send_envelope(self, envelope: Envelope):
        if self.websocket:
            await self.websocket.send(envelope.model_dump_json())

    async def _receive_loop(self):
        try:
            async for message in self.websocket:
                try:
                    envelope = Envelope.model_validate_json(message)
                    if self.on_message_callback:
                        await self.on_message_callback(envelope)
                except Exception as e:
                    logger.error("Error parsing WS message", error=str(e))
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error("Error in WS receive loop", error=str(e))

    async def close(self):
        if self.websocket:
            await self.websocket.close()
        if self._receive_task:
            self._receive_task.cancel()
