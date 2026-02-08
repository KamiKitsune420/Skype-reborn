import asyncio
import socket
import struct
from uuid import UUID

class UDPClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.transport = None
        self.session_id = None
        self.on_audio_received = None
        self.seq = 0

    async def start(self, session_id: UUID, on_audio_received, user_id=None):
        self.session_id = session_id
        self.on_audio_received = on_audio_received
        
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self,
            remote_addr=(self.host, self.port)
        )
        
        if user_id:
            # Send a small packet to register this address with the user_id on the relay
            self.send_audio(f"HELLO:{user_id}".encode()) 

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        # Header: session_id (16), seq (2), ts (4), codec (1), len (2)
        if len(data) < 25:
            return
        
        # In a real app we'd verify session_id
        payload = data[25:]
        if self.on_audio_received:
            self.on_audio_received(payload)

    def send_audio(self, payload):
        if not self.transport or not self.session_id:
            return
        
        # Header: session_id (16), seq (2), ts (4), codec (1), len (2)
        header = self.session_id.bytes
        header += struct.pack("!H", self.seq)
        header += struct.pack("!I", 0) # ts placeholder
        header += struct.pack("!B", 2) # codec PCM
        header += struct.pack("!H", len(payload))
        
        self.transport.sendto(header + payload)
        self.seq = (self.seq + 1) % 65536

    def stop(self):
        if self.transport:
            self.transport.close()
