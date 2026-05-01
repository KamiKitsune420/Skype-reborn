import unittest
import asyncio
import threading
import uvicorn
import httpx
import websockets
from uuid import uuid4
from server.main import app
from server.database import engine, Base
from shared.models import Envelope, MessageType, ChatMessagePayload

class TestServer(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # We need to run the server in a thread for integration testing
        cls.server_thread = threading.Thread(
            target=uvicorn.run, 
            args=(app,), 
            kwargs={"host": "127.0.0.1", "port": 8001, "log_level": "error"},
            daemon=True
        )
        cls.server_thread.start()
        # Give it a second to start
        import time
        time.sleep(1)

    async def test_register_and_login(self):
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
            suffix = uuid4().hex[:8]
            username = f"testuser_{suffix}"
            # Register
            reg_data = {
                "username": username,
                "password": "password123",
                "email": f"{username}@example.com",
                "first_name": "Test",
                "last_name": "User"
            }
            reg_resp = await client.post("/register", json=reg_data)
            self.assertEqual(reg_resp.status_code, 200)
            
            # Login
            login_resp = await client.post("/login", json={"username": username, "password": "password123"})
            self.assertEqual(login_resp.status_code, 200)
            data = login_resp.json()
            self.assertIn("token", data)
            token = data["token"]
            
            # Test protected route
            headers = {"Authorization": f"Bearer {token}"}
            contacts_resp = await client.get("/contacts", headers=headers)
            self.assertEqual(contacts_resp.status_code, 200)

    async def test_offline_message_replay_uses_authenticated_sender(self):
        suffix = uuid4().hex[:8]
        alice = f"alice_{suffix}"
        bob = f"bob_{suffix}"

        async with httpx.AsyncClient(base_url="http://127.0.0.1:8001") as client:
            for username in (alice, bob):
                reg_resp = await client.post(
                    "/register",
                    json={
                        "username": username,
                        "password": "password123",
                        "email": f"{username}@example.com",
                        "first_name": username,
                        "last_name": "Test",
                    },
                )
                self.assertEqual(reg_resp.status_code, 200)

            alice_login = await client.post(
                "/login", json={"username": alice, "password": "password123"}
            )
            bob_login = await client.post(
                "/login", json={"username": bob, "password": "password123"}
            )
            self.assertEqual(alice_login.status_code, 200)
            self.assertEqual(bob_login.status_code, 200)
            alice_data = alice_login.json()
            bob_data = bob_login.json()

            alice_headers = {"Authorization": f"Bearer {alice_data['token']}"}
            bob_headers = {"Authorization": f"Bearer {bob_data['token']}"}

            add_resp = await client.post(
                "/contacts/add",
                json={"username": bob},
                headers=alice_headers,
            )
            self.assertEqual(add_resp.status_code, 200)

            ticket_resp = await client.post("/ws/ticket", headers=alice_headers)
            self.assertEqual(ticket_resp.status_code, 200)
            alice_ticket = ticket_resp.json()["ticket"]

            async with websockets.connect(f"ws://127.0.0.1:8001/ws/{alice_ticket}") as alice_ws:
                payload = ChatMessagePayload(
                    conversation_id=bob_data["user_id"],
                    sender_id=bob_data["user_id"],
                    content="queued while offline",
                )
                await alice_ws.send(
                    Envelope(type=MessageType.CHAT_SEND, payload=payload.model_dump()).model_dump_json()
                )
                await asyncio.sleep(0.2)

            ticket_resp = await client.post("/ws/ticket", headers=bob_headers)
            self.assertEqual(ticket_resp.status_code, 200)
            bob_ticket = ticket_resp.json()["ticket"]

        async with websockets.connect(f"ws://127.0.0.1:8001/ws/{bob_ticket}") as bob_ws:
            envelope = None
            for _ in range(5):
                raw = await asyncio.wait_for(bob_ws.recv(), timeout=3)
                candidate = Envelope.model_validate_json(raw)
                if candidate.type == MessageType.CHAT_RECEIVE:
                    envelope = candidate
                    break
            self.assertIsNotNone(envelope)
            self.assertEqual(envelope.type, MessageType.CHAT_RECEIVE)
            self.assertEqual(envelope.payload["content"], "queued while offline")
            self.assertEqual(envelope.payload["sender_id"], alice_data["user_id"])

if __name__ == "__main__":
    unittest.main()
