from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, DefaultDict, TypeVar
from collections import defaultdict

import structlog

from client.network.ws_client import WSClient
from shared.models import (
    Envelope,
    MessageType,
    ChatMessagePayload,
    ChatTypingPayload,
    PresenceUpdatePayload,
    CallSignalPayload,
    ChatAckPayload,
    UserStatus,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class ChatReceived:
    sender_id: str
    content: str
    message_type: str


@dataclass(frozen=True)
class TypingChanged:
    user_id: str
    is_typing: bool


@dataclass(frozen=True)
class PresenceChanged:
    user_id: str
    status: UserStatus


@dataclass(frozen=True)
class ContactRequestReceived:
    pass


@dataclass(frozen=True)
class IncomingCall:
    payload: CallSignalPayload


@dataclass(frozen=True)
class CallConnecting:
    payload: CallSignalPayload


@dataclass(frozen=True)
class CallAccepted:
    payload: CallSignalPayload


@dataclass(frozen=True)
class CallRejected:
    payload: CallSignalPayload


@dataclass(frozen=True)
class CallHungUp:
    payload: CallSignalPayload


@dataclass(frozen=True)
class MessageRead:
    reader_id: str   # the person who read
    peer_id: str     # whose messages they read (= our user_id when we receive this)

@dataclass(frozen=True)
class SessionDisconnected:
    pass


EventT = TypeVar("EventT")
EventHandler = Callable[[object], None]


class ClientSessionService:
    """Protocol-facing client service.

    UI objects call intent methods such as send_message() and subscribe to
    domain events. Raw Envelope construction and dispatch stays here.
    """

    def __init__(self, ws_client: WSClient, user_id: str):
        self.ws_client = ws_client
        self.user_id = user_id
        self._handlers: DefaultDict[type, list[EventHandler]] = defaultdict(list)

    def bind_websocket(self):
        self.ws_client.on_message_callback = self.handle_envelope
        self.ws_client.on_disconnect_callback = self.handle_disconnect

    def on(self, event_type: type[EventT], handler: Callable[[EventT], None]):
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]

    def _emit(self, event: object):
        for handler in self._handlers.get(type(event), []):
            handler(event)

    def send_message(self, peer_id: str, content: str, message_type: str = "text"):
        payload = ChatMessagePayload(
            conversation_id=peer_id,
            sender_id=self.user_id,
            content=content,
            message_type=message_type,
        )
        self._send(MessageType.CHAT_SEND, payload)

    def send_typing(self, peer_id: str, is_typing: bool):
        payload = ChatTypingPayload(
            conversation_id=peer_id,
            user_id=self.user_id,
            is_typing=is_typing,
        )
        self._send(MessageType.CHAT_TYPING, payload)

    def send_read_receipt(self, peer_id: str):
        """Tell the server (and the peer) that we have read their messages."""
        payload = ChatAckPayload(peer_id=peer_id, reader_id=self.user_id)
        self._send(MessageType.CHAT_ACK, payload)

    def send_presence(self, status: UserStatus):
        payload = PresenceUpdatePayload(user_id=self.user_id, status=status)
        self._send(MessageType.PRESENCE_UPDATE, payload)

    def send_call_signal(
        self,
        message_type: MessageType,
        session_id: str,
        target_id: str,
        data: dict | None = None,
    ):
        payload = CallSignalPayload(
            session_id=session_id,
            target_id=target_id,
            sender_id=self.user_id,
            data=data,
        )
        self._send(message_type, payload)

    def _send(self, message_type: MessageType, payload):
        self.ws_client.send_envelope(
            Envelope(type=message_type, payload=payload.model_dump())
        )

    def handle_disconnect(self):
        self._emit(SessionDisconnected())

    def handle_envelope(self, envelope: Envelope):
        try:
            if envelope.type == MessageType.CHAT_RECEIVE:
                payload = ChatMessagePayload(**envelope.payload)
                self._emit(
                    ChatReceived(
                        sender_id=payload.sender_id,
                        content=payload.content,
                        message_type=payload.message_type,
                    )
                )
            elif envelope.type == MessageType.CHAT_TYPING:
                payload = ChatTypingPayload(**envelope.payload)
                self._emit(
                    TypingChanged(user_id=payload.user_id, is_typing=payload.is_typing)
                )
            elif envelope.type == MessageType.PRESENCE_BROADCAST:
                payload = PresenceUpdatePayload(**envelope.payload)
                self._emit(PresenceChanged(user_id=payload.user_id, status=payload.status))
            elif envelope.type == MessageType.CONTACT_REQUEST:
                self._emit(ContactRequestReceived())
            elif envelope.type == MessageType.CALL_INITIATE:
                self._emit(IncomingCall(CallSignalPayload(**envelope.payload)))
            elif envelope.type == MessageType.CALL_CONNECTING:
                self._emit(CallConnecting(CallSignalPayload(**envelope.payload)))
            elif envelope.type == MessageType.CALL_ACCEPT:
                self._emit(CallAccepted(CallSignalPayload(**envelope.payload)))
            elif envelope.type == MessageType.CALL_REJECT:
                self._emit(CallRejected(CallSignalPayload(**envelope.payload)))
            elif envelope.type == MessageType.CALL_HANGUP:
                self._emit(CallHungUp(CallSignalPayload(**envelope.payload)))
            elif envelope.type == MessageType.CHAT_ACK:
                ack = ChatAckPayload(**envelope.payload)
                self._emit(MessageRead(reader_id=ack.reader_id, peer_id=ack.peer_id))
        except Exception as exc:
            logger.error(
                "Client session failed to process envelope",
                type=envelope.type,
                error=str(exc),
            )
