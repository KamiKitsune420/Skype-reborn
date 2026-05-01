from typing import Dict, List, Optional
from uuid import uuid4
from fastapi import WebSocket
import structlog
from shared.models import Envelope, MessageType, UserStatus, PresenceUpdatePayload
from sqlalchemy import select

logger = structlog.get_logger()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.tickets: Dict[str, str] = {} # ticket -> user_id

    def create_ticket(self, user_id: str) -> str:
        ticket = str(uuid4())
        self.tickets[ticket] = user_id
        # In a real app, tickets should expire
        return ticket

    async def connect(self, ticket: str, websocket: WebSocket) -> Optional[str]:
        user_id = self.tickets.get(ticket)
        if not user_id:
            await websocket.close(code=4003)
            return None
        
        # Remove ticket after use
        del self.tickets[ticket]

        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info("User connected", user_id=user_id)
        # Broadcast that this user is online
        await self.broadcast_presence(user_id, UserStatus.ONLINE)
        return user_id

    async def send_initial_statuses(self, user_id: str, contacts: List[Dict]):
        # Send the current status of all contacts to the newly connected user
        for contact in contacts:
            envelope = Envelope(
                type=MessageType.PRESENCE_BROADCAST,
                payload=PresenceUpdatePayload(user_id=contact['id'], status=UserStatus(contact['status'])).model_dump()
            )
            await self.send_personal_message(envelope.model_dump_json(), user_id)

    async def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info("User disconnected", user_id=user_id)
            await self.broadcast_presence(user_id, UserStatus.OFFLINE)

    async def broadcast_presence(self, user_id: str, status: UserStatus):
        payload = PresenceUpdatePayload(user_id=user_id, status=status)
        envelope = Envelope(type=MessageType.PRESENCE_BROADCAST, payload=payload.model_dump())
        msg = envelope.model_dump_json()
        for conn in self.active_connections.values():
            try:
                await conn.send_text(msg)
            except Exception:
                pass

    async def send_personal_message(self, message: str, user_id: str):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_text(message)
                return True
            except Exception:
                return False
        return False

manager = ConnectionManager()
