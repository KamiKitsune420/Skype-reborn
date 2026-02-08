import httpx
import structlog
from typing import List, Dict, Any, Optional

logger = structlog.get_logger()

class APIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url)
        self.token = None
        self.user_id = None

    def set_token(self, token: str):
        self.token = token
        self.client.headers.update({"Authorization": f"Bearer {token}"})

    async def register(self, data: Dict[str, str]):
        try:
            resp = await self.client.post("/register", json=data)
            if resp.status_code == 200:
                return True, resp.json().get("message", "Success")
            return False, resp.json().get("detail", "Unknown error")
        except Exception as e:
            logger.error("Registration failed", error=str(e))
            return False, str(e)

    async def login(self, username, password):
        try:
            resp = await self.client.post("/login", json={"username": username, "password": password})
            if resp.status_code == 200:
                data = resp.json()
                self.token = data["token"]
                self.user_id = data["user_id"]
                self.set_token(self.token)
                return True, data
            return False, resp.json().get("detail", "Invalid credentials")
        except Exception as e:
            logger.error("Login failed", error=str(e))
            return False, str(e)

    async def get_contacts(self):
        try:
            resp = await self.client.get("/contacts")
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            logger.error("Failed to get contacts", error=str(e))
            return []

    async def add_contact(self, username: str):
        try:
            resp = await self.client.post("/contacts/add", json={"username": username})
            if resp.status_code == 200:
                return True, resp.json().get("message", "Success")
            return False, resp.json().get("detail", "Unknown error")
        except Exception as e:
            logger.error("Failed to add contact", error=str(e))
            return False, str(e)

    async def get_messages(self, conversation_id: str):
        try:
            resp = await self.client.get(f"/messages/{conversation_id}")
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            logger.error("Failed to get messages", error=str(e))
            return []

    async def search_users(self, query: str):
        try:
            resp = await self.client.get("/users/search", params={"query": query})
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            logger.error("Failed to search users", error=str(e))
            return []

    async def update_profile(self, display_name: Optional[str] = None):
        try:
            payload = {"user_id": self.user_id} # user_id is in payload for shared model but server uses current_user
            if display_name:
                payload["display_name"] = display_name
            resp = await self.client.post("/profile/update", json=payload)
            return resp.status_code == 200
        except Exception as e:
            logger.error("Failed to update profile", error=str(e))
            return False

        async def upload_file(self, recipient_id: str, filename: str, file_content: bytes):

            try:

                files = {'file': (filename, file_content)}

                params = {'filename': filename}

                resp = await self.client.post(f"/upload/{recipient_id}", params=params, files=files)

                if resp.status_code == 200:

                    return True, resp.json()

                return False, resp.json().get("detail", "Upload failed")

            except Exception as e:

                logger.error("File upload failed", error=str(e))

                return False, str(e)

    