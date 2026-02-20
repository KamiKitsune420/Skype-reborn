import socket
import struct
import threading
import structlog
from uuid import UUID

logger = structlog.get_logger()

# All-zero UUID signals a HELLO registration packet (not audio)
_ZERO_UUID = UUID(int=0)


class UDPClient:
    """UDP audio client backed by a plain socket + daemon receiver thread.

    No asyncio required — socket I/O is straightforward enough that a
    blocking thread is simpler and faster than an event-loop protocol.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._recv_thread: threading.Thread | None = None
        self._running = False
        self.session_id: UUID | None = None
        self.on_audio_received = None
        self._seq = 0

    def start(self, session_id: UUID, on_audio_received, user_id: str = None):
        """Open socket and start receive thread. Stops any previous session first."""
        self.stop()

        self.session_id = session_id
        self.on_audio_received = on_audio_received
        self._seq = 0

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.connect((self.host, self.port))  # Sets default dest; not a TCP handshake
        self._sock.settimeout(1.0)

        if user_id:
            # Register our address with the relay using the all-zero session_id
            self._send_raw(_ZERO_UUID, f"HELLO:{user_id}".encode())

        self._running = True
        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True, name="UDPRecv"
        )
        self._recv_thread.start()

    # ── Receive loop ─────────────────────────────────────────────────

    def _recv_loop(self):
        while self._running:
            try:
                data = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break  # Socket closed — exit cleanly

            # Packet layout: session_id(16) seq(2) ts(4) codec(1) len(2) = 25 bytes header
            if len(data) < 25:
                continue
            payload = data[25:]
            if payload and self.on_audio_received:
                self.on_audio_received(payload)

    # ── Send ─────────────────────────────────────────────────────────

    def send_audio(self, payload: bytes):
        if self._sock and self.session_id:
            self._send_raw(self.session_id, payload)

    def _send_raw(self, session_id: UUID, payload: bytes):
        if not self._sock:
            return
        header = session_id.bytes
        header += struct.pack("!H", self._seq)
        header += struct.pack("!I", 0)       # timestamp placeholder
        header += struct.pack("!B", 2)       # codec: PCM
        header += struct.pack("!H", len(payload))
        try:
            self._sock.send(header + payload)
        except OSError as e:
            logger.error("UDP send failed", error=str(e))
        self._seq = (self._seq + 1) % 65536

    # ── Lifecycle ────────────────────────────────────────────────────

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self.session_id = None
        self._seq = 0
