from uuid import UUID

from client.services.calls import CallService
from client.services.session import (
    ClientSessionService,
    ChatReceived,
)
from shared.models import Envelope, MessageType, ChatMessagePayload, CallSignalPayload


class FakeWSClient:
    def __init__(self):
        self.sent = []
        self.on_message_callback = None
        self.on_disconnect_callback = None

    def send_envelope(self, envelope):
        self.sent.append(envelope)


class FakeAudio:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self, send_callback):
        self.started = True

    def stop(self):
        self.stopped = True

    def receive_audio(self, seq, data):
        pass


class FakeUDP:
    def __init__(self):
        self.started = None
        self.stopped = False

    def start(self, session_id, callback, user_id=None):
        self.started = (session_id, user_id)

    def stop(self):
        self.stopped = True

    def send_audio(self, payload):
        pass


def test_session_service_emits_chat_events():
    ws = FakeWSClient()
    service = ClientSessionService(ws, "alice-id")
    received = []
    service.on(ChatReceived, received.append)

    payload = ChatMessagePayload(
        conversation_id="alice-id",
        sender_id="bob-id",
        content="hello",
    )
    service.handle_envelope(
        Envelope(type=MessageType.CHAT_RECEIVE, payload=payload.model_dump())
    )

    assert received == [ChatReceived(sender_id="bob-id", content="hello", message_type="text")]


def test_session_service_sends_authenticated_message_intent():
    ws = FakeWSClient()
    service = ClientSessionService(ws, "alice-id")

    service.send_message("bob-id", "hello")

    assert len(ws.sent) == 1
    envelope = ws.sent[0]
    assert envelope.type == MessageType.CHAT_SEND
    assert envelope.payload["conversation_id"] == "bob-id"
    assert envelope.payload["sender_id"] == "alice-id"


def test_call_service_hangup_uses_active_peer_not_selected_contact():
    ws = FakeWSClient()
    session = ClientSessionService(ws, "alice-id")
    audio = FakeAudio()
    udp = FakeUDP()
    calls = CallService(session, audio, udp, "alice-id")

    active = calls.start_outgoing("bob-id", "Bob")
    ws.sent.clear()
    calls.hang_up()

    assert len(ws.sent) == 1
    envelope = ws.sent[0]
    assert envelope.type == MessageType.CALL_HANGUP
    assert envelope.payload["session_id"] == str(active.session_id)
    assert envelope.payload["target_id"] == "bob-id"
    assert audio.stopped is True
    assert udp.stopped is True


def test_call_service_reject_targets_original_caller():
    ws = FakeWSClient()
    session = ClientSessionService(ws, "bob-id")
    calls = CallService(session, FakeAudio(), FakeUDP(), "bob-id")
    payload = CallSignalPayload(
        session_id=str(UUID(int=1)),
        target_id="bob-id",
        sender_id="alice-id",
    )

    calls.reject(payload)

    assert len(ws.sent) == 1
    envelope = ws.sent[0]
    assert envelope.type == MessageType.CALL_REJECT
    assert envelope.payload["target_id"] == "alice-id"
