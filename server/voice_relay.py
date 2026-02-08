import asyncio
import structlog
import time

logger = structlog.get_logger()

class VoiceRelayServer:
    def __init__(self, host="0.0.0.0", port=9000):
        self.host = host
        self.port = port
        self.transport = None
        self.sessions = {} # session_id -> {addr: last_seen}
        self.addr_to_user_id = {} # addr -> user_id
        self.cleanup_task = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info("Voice Relay Server started", host=self.host, port=self.port)
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())

    def datagram_received(self, data, addr):
        if len(data) < 25:
            return
        
        session_id_bytes = data[:16]
        session_id = session_id_bytes.hex()
        
        now = time.time()

        # Handle registration
        payload = data[25:]
        if all(b == 0 for b in session_id_bytes) and payload.startswith(b"HELLO:"):
            try:
                user_id = payload.decode().split(":")[1]
                self.addr_to_user_id[addr] = user_id
                logger.info("UDP Registered", user_id=user_id, addr=addr)
            except Exception:
                pass
            return

        # Regular relay
        if session_id not in self.sessions:
            self.sessions[session_id] = {}
        
        self.sessions[session_id][addr] = now
        
        for peer in list(self.sessions[session_id].keys()):
            if peer != addr:
                self.transport.sendto(data, peer)

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(60)
            now = time.time()
            # Cleanup old sessions
            for session_id in list(self.sessions.keys()):
                peers = self.sessions[session_id]
                for peer, last_seen in list(peers.items()):
                    if now - last_seen > 300: # 5 minutes timeout
                        del peers[peer]
                        if peer in self.addr_to_user_id:
                            del self.addr_to_user_id[peer]
                
                if not peers:
                    del self.sessions[session_id]

    def stop(self):
        if self.cleanup_task:
            self.cleanup_task.cancel()

async def start_voice_relay(host="0.0.0.0", port=9000):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: VoiceRelayServer(host, port),
        local_addr=(host, port)
    )
    return transport, protocol
