import socket
import struct
import threading
import structlog
from uuid import UUID
from cryptography.fernet import Fernet

logger = structlog.get_logger()

# All-zero UUID signals a HELLO registration packet (not audio)
_ZERO_UUID = UUID(int=0)


class UDPClient:
    """UDP audio client with sequence tracking and encryption."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._recv_thread: threading.Thread | None = None
        self._running = False
        self.session_id: UUID | None = None
        self.on_audio_received = None
        self._seq = 0
        
        # Encryption
        self.cipher = None

    def set_encryption_key(self, key: bytes):
        """Set the 32-byte Fernet key for the session."""
        try:
            self.cipher = Fernet(key)
            logger.info("UDP encryption enabled")
        except Exception as e:
            logger.error("Failed to set encryption key", error=str(e))

    def start(self, session_id: UUID, on_audio_received, user_id: str = None):
        """Open socket and start receive thread."""
        self.stop()

        self.session_id = session_id
        self.on_audio_received = on_audio_received
        self._seq = 0

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.connect((self.host, self.port))
        self._sock.settimeout(1.0)

        if user_id:
            self._send_raw(_ZERO_UUID, f"HELLO:{user_id}".encode())

        self._running = True
        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True, name="UDPRecv"
        )
        self._recv_thread.start()

    def _recv_loop(self):
        while self._running:
            try:
                data = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            # Header: session_id(16) seq(2) ts(4) codec(1) len(2) = 25 bytes
            if len(data) < 25:
                continue
            
            header = data[:25]
            payload = data[25:]
            
            # Extract sequence number (bytes 16-17)
            seq = struct.unpack("!H", header[16:18])[0]
            
            if payload and self.on_audio_received:
                # Decrypt if key is set
                if self.cipher:
                    try:
                        payload = self.cipher.decrypt(payload)
                    except Exception:
                        continue # Drop if decryption fails
                
                self.on_audio_received(seq, payload)

    def send_audio(self, payload: bytes):
        if self._sock and self.session_id:
            # Encrypt if key is set
            if self.cipher:
                try:
                    payload = self.cipher.encrypt(payload)
                except Exception as e:
                    logger.error("Encryption failed", error=str(e))
                    return

            self._send_raw(self.session_id, payload)

    def _send_raw(self, session_id: UUID, payload: bytes):
        if not self._sock:
            return
        header = session_id.bytes
        header += struct.pack("!H", self._seq)
        header += struct.pack("!I", 0)       # timestamp placeholder
        header += struct.pack("!B", 3)       # codec: 3 = Opus (was 2=PCM)
        header += struct.pack("!H", len(payload))
        try:
            self._sock.send(header + payload)
        except OSError as e:
            logger.error("UDP send failed", error=str(e))
        self._seq = (self._seq + 1) % 65536

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
