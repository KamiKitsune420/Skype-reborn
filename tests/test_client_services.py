from uuid import UUID

from client.services.calls import CallService
from client.services.session import (
    ClientSessionService,
    ChatReceived,
)
from client.ui.controllers.contacts import ContactsController
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


class FakeMessageController:
    def __init__(self):
        self.opened = None

    def open_conversation(self, contact):
        self.opened = contact


class FakeListBox:
    def __init__(self, selection):
        self._selection = selection

    def GetSelection(self):
        return self._selection


class FakeOwner:
    def __init__(self, contacts, selection=0):
        self.is_searching = False
        self.contacts = contacts
        self.search_results = []
        self.contact_list = FakeListBox(selection)
        self.selected_contact = None
        self.messages_controller = FakeMessageController()
        self._status = None

    def SetStatusText(self, value):
        self._status = value


def test_contacts_controller_open_selected_contact_uses_current_selection():
    owner = FakeOwner([{"id": "u1", "display_name": "Alice"}], selection=0)
    controller = ContactsController(owner)

    opened = controller.open_selected_contact()

    assert opened is True
    assert owner.selected_contact["id"] == "u1"
    assert owner._status == "Alice"
    assert owner.messages_controller.opened["id"] == "u1"
