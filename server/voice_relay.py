import asyncio
import structlog
import time

logger = structlog.get_logger()

_HELLO_PREFIX = b"HELLO:"
_HEADER_SIZE = 25
_SESSION_TIMEOUT = 300   # seconds before an idle peer is evicted
_CLEANUP_INTERVAL = 60   # seconds between cleanup sweeps


class VoiceRelayServer(asyncio.DatagramProtocol):
    """UDP relay: forwards audio packets to every peer in the same session.

    Packet layout (must match client/network/udp_client.py):
        bytes  0-15  session_id (UUID bytes; all-zero = HELLO registration)
        bytes 16-17  seq        (uint16 big-endian)
        bytes 18-21  timestamp  (uint32 big-endian, placeholder)
        byte  22     codec      (uint8)
        bytes 23-24  payload_len (uint16 big-endian)
        bytes 25+    payload
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9000):
        self.host = host
        self.port = port
        self.transport = None
        # session_id (hex str) -> { addr: last_seen_timestamp }
        self.sessions: dict[str, dict] = {}
        self._cleanup_task = None

    # ── asyncio DatagramProtocol ──────────────────────────────────────

    def connection_made(self, transport):
        self.transport = transport
        logger.info("Voice Relay started", host=self.host, port=self.port)
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def datagram_received(self, data: bytes, addr):
        if len(data) < _HEADER_SIZE:
            return

        session_id_bytes = data[:16]
        payload = data[_HEADER_SIZE:]

        # HELLO registration: all-zero session_id + "HELLO:<user_id>" payload.
        # We log it but don't need to track addr→user mapping because the relay
        # works purely by session_id — it forwards to every peer that has sent
        # to the same session. (addr_to_user_id was tracked previously but was
        # never read anywhere, so it has been removed.)
        if all(b == 0 for b in session_id_bytes) and payload.startswith(_HELLO_PREFIX):
            try:
                user_id = payload.decode().split(":", 1)[1]
                logger.debug("UDP HELLO", user_id=user_id, addr=addr)
            except Exception:
                pass
            return

        # Regular audio relay
        session_id = session_id_bytes.hex()
        now = time.monotonic()

        peers = self.sessions.setdefault(session_id, {})
        peers[addr] = now

        for peer_addr in list(peers):
            if peer_addr != addr:
                try:
                    self.transport.sendto(data, peer_addr)
                except Exception as e:
                    logger.warning("Relay send failed", peer=peer_addr, error=str(e))

    def error_received(self, exc: Exception):
        logger.error("Voice relay UDP error", error=str(exc))

    def connection_lost(self, exc):
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if exc:
            logger.error("Voice relay connection lost", error=str(exc))

    # ── Session cleanup ───────────────────────────────────────────────

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL)
            now = time.monotonic()
            for session_id in list(self.sessions):
                peers = self.sessions[session_id]
                stale = [a for a, ts in peers.items() if now - ts > _SESSION_TIMEOUT]
                for addr in stale:
                    del peers[addr]
                if not peers:
                    del self.sessions[session_id]
                    logger.debug("Session cleaned up", session_id=session_id)

    def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self.transport:
            self.transport.close()


async def start_voice_relay(host: str = "0.0.0.0", port: int = 9000):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: VoiceRelayServer(host, port),
        local_addr=(host, port),
    )
    return transport, protocol
