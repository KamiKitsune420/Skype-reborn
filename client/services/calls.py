from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from shared.models import CallSignalPayload, MessageType
from client.audio.engine import AudioEngine
from client.network.udp_client import UDPClient
from client.services.session import ClientSessionService


@dataclass
class ActiveCall:
    session_id: UUID
    peer_id: str
    peer_name: str
    incoming: bool = False


class CallService:
    """Owns call protocol state and media lifecycle."""

    def __init__(
        self,
        session: ClientSessionService,
        audio_engine: AudioEngine,
        udp_client: UDPClient,
        user_id: str,
    ):
        self.session = session
        self.audio_engine = audio_engine
        self.udp_client = udp_client
        self.user_id = user_id
        self.active_call: ActiveCall | None = None

    @property
    def is_active(self) -> bool:
        return self.active_call is not None

    def is_active_session(self, payload: CallSignalPayload) -> bool:
        return (
            self.active_call is not None
            and str(self.active_call.session_id) == payload.session_id
        )

    def start_outgoing(self, peer_id: str, peer_name: str) -> ActiveCall:
        call = ActiveCall(session_id=uuid4(), peer_id=peer_id, peer_name=peer_name)
        self.active_call = call
        self.session.send_call_signal(
            MessageType.CALL_INITIATE,
            session_id=str(call.session_id),
            target_id=peer_id,
        )
        self._start_udp(call.session_id)
        return call

    def accept(self, payload: CallSignalPayload, peer_name: str) -> ActiveCall:
        call = ActiveCall(
            session_id=UUID(payload.session_id),
            peer_id=payload.sender_id,
            peer_name=peer_name,
            incoming=True,
        )
        self.active_call = call
        self.session.send_call_signal(
            MessageType.CALL_ACCEPT,
            session_id=payload.session_id,
            target_id=payload.sender_id,
        )
        self._start_udp(call.session_id)
        self.audio_engine.start(self.udp_client.send_audio)
        return call

    def reject(self, payload: CallSignalPayload):
        self.session.send_call_signal(
            MessageType.CALL_REJECT,
            session_id=payload.session_id,
            target_id=payload.sender_id,
        )

    def remote_accepted(self):
        if self.active_call:
            self.audio_engine.start(self.udp_client.send_audio)

    def hang_up(self):
        if self.active_call:
            self.session.send_call_signal(
                MessageType.CALL_HANGUP,
                session_id=str(self.active_call.session_id),
                target_id=self.active_call.peer_id,
            )
        self.end_local()

    def end_local(self):
        self.audio_engine.stop()
        self.udp_client.stop()
        self.active_call = None

    def _start_udp(self, session_id: UUID):
        self.udp_client.start(
            session_id,
            self.audio_engine.receive_audio,
            user_id=self.user_id,
        )
