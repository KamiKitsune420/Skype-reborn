import unittest
import asyncio
import threading
import uvicorn
import httpx
from server.main import app
from server.database import engine, Base

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
            # Register
            reg_data = {
                "username": "testuser3", 
                "password": "password123",
                "email": "test3@example.com",
                "first_name": "Test",
                "last_name": "User"
            }
            reg_resp = await client.post("/register", json=reg_data)
            self.assertEqual(reg_resp.status_code, 200)
            
            # Login
            login_resp = await client.post("/login", json={"username": "testuser3", "password": "password123"})
            self.assertEqual(login_resp.status_code, 200)
            data = login_resp.json()
            self.assertIn("token", data)
            token = data["token"]
            
            # Test protected route
            headers = {"Authorization": f"Bearer {token}"}
            contacts_resp = await client.get("/contacts", headers=headers)
            self.assertEqual(contacts_resp.status_code, 200)

if __name__ == "__main__":
    unittest.main()
