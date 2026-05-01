import asyncio
import os
import httpx
import websockets
from shared.models import Envelope, MessageType, ChatMessagePayload


async def resolve_target_id(client: httpx.AsyncClient, target: str) -> str:
    contacts_resp = await client.get("/contacts")
    if contacts_resp.status_code == 200:
        for contact in contacts_resp.json():
            if target in {
                contact.get("id"),
                contact.get("username"),
                contact.get("display_name"),
            }:
                return contact["id"]

    search_resp = await client.get("/users/search", params={"query": target})
    if search_resp.status_code == 200:
        for user in search_resp.json():
            if target in {
                user.get("id"),
                user.get("username"),
                user.get("display_name"),
            }:
                return user["id"]

    return target


async def run_headless(username, password, target="echo_service"):
    base_url = os.environ.get("SKYPE_SERVER_URL", "http://127.0.0.1:8000")
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    
    async with httpx.AsyncClient() as client:
        # Login
        resp = await client.post(f"{base_url}/login", json={"username": username, "password": password})
        if resp.status_code != 200:
            print("Login failed")
            return
        data = resp.json()
        user_id = data["user_id"]
        client.headers.update({"Authorization": f"Bearer {data['token']}"})

        ticket_resp = await client.post(f"{base_url}/ws/ticket")
        if ticket_resp.status_code != 200:
            print(f"WebSocket ticket failed: {ticket_resp.text}")
            return
        ticket = ticket_resp.json()["ticket"]
        target_id = await resolve_target_id(client, target)

    async with websockets.connect(f"{ws_url}/ws/{ticket}") as ws:
        print(f"Connected as {username}")
        
        # Send a test message
        payload = ChatMessagePayload(
            conversation_id=target_id,
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
        print("Usage: python headless_client.py <username> <password> [target_username_or_id]")
    else:
        target_arg = sys.argv[3] if len(sys.argv) > 3 else "echo_service"
        asyncio.run(run_headless(sys.argv[1], sys.argv[2], target_arg))
