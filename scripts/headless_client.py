import asyncio
import httpx
import websockets
import json
from shared.models import Envelope, MessageType, ChatMessagePayload

async def run_headless(username, password):
    base_url = "http://127.0.0.1:8000"
    ws_url = "ws://127.0.0.1:8000"
    
    async with httpx.AsyncClient() as client:
        # Login
        resp = await client.post(f"{base_url}/login", json={"username": username, "password": password})
        if resp.status_code != 200:
            print("Login failed")
            return
        data = resp.json()
        user_id = data["user_id"]
        
    async with websockets.connect(f"{ws_url}/ws/{user_id}") as ws:
        print(f"Connected as {username}")
        
        # Send a test message
        payload = ChatMessagePayload(
            conversation_id="echo_service",
            sender_id=user_id,
            content="Hello from headless client!"
        )
        envelope = Envelope(type=MessageType.CHAT_SEND, payload=payload.model_dump())
        await ws.send(envelope.model_dump_json())
        
        # Wait for response
        resp_data = await ws.recv()
        print(f"Received: {resp_data}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python headless_client.py <username> <password>")
    else:
        asyncio.run(run_headless(sys.argv[1], sys.argv[2]))
