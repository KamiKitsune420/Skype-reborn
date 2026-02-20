import httpx
import structlog
from typing import Dict, Any, Optional

logger = structlog.get_logger()


class APIClient:
    """Synchronous HTTP client. Safe to call from any thread."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        # httpx.Client is thread-safe for concurrent requests
        self.client = httpx.Client(base_url=base_url, timeout=10.0)
        self.token: Optional[str] = None
        self.user_id: Optional[str] = None

    def set_token(self, token: str):
        self.token = token
        self.client.headers.update({"Authorization": f"Bearer {token}"})

    def register(self, data: Dict[str, str]):
        try:
            resp = self.client.post("/register", json=data)
            if resp.status_code == 200:
                return True, resp.json().get("message", "Success")
            return False, resp.json().get("detail", "Unknown error")
        except Exception as e:
            logger.error("Registration failed", error=str(e))
            return False, str(e)

    def login(self, username: str, password: str):
        try:
            resp = self.client.post("/login", json={"username": username, "password": password})
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

    def get_contacts(self):
        try:
            resp = self.client.get("/contacts")
            return resp.json() if resp.status_code == 200 else []
        except Exception as e:
            logger.error("Failed to get contacts", error=str(e))
            return []

    def add_contact(self, username: str):
        try:
            resp = self.client.post("/contacts/add", json={"username": username})
            if resp.status_code == 200:
                return True, resp.json().get("message", "Success")
            return False, resp.json().get("detail", "Unknown error")
        except Exception as e:
            logger.error("Failed to add contact", error=str(e))
            return False, str(e)

    def get_messages(self, conversation_id: str):
        try:
            resp = self.client.get(f"/messages/{conversation_id}")
            return resp.json() if resp.status_code == 200 else []
        except Exception as e:
            logger.error("Failed to get messages", error=str(e))
            return []

    def search_users(self, query: str):
        try:
            resp = self.client.get("/users/search", params={"query": query})
            return resp.json() if resp.status_code == 200 else []
        except Exception as e:
            logger.error("Failed to search users", error=str(e))
            return []

    def update_profile(self, display_name: Optional[str] = None):
        try:
            payload: Dict[str, Any] = {"user_id": self.user_id}
            if display_name:
                payload["display_name"] = display_name
            resp = self.client.post("/profile/update", json=payload)
            return resp.status_code == 200
        except Exception as e:
            logger.error("Failed to update profile", error=str(e))
            return False

    def upload_file(self, recipient_id: str, filename: str, file_content: bytes):
        try:
            resp = self.client.post(
                f"/upload/{recipient_id}",
                params={"filename": filename},
                files={"file": (filename, file_content)},
            )
            if resp.status_code == 200:
                return True, resp.json()
            return False, resp.json().get("detail", "Upload failed")
        except Exception as e:
            logger.error("File upload failed", error=str(e))
            return False, str(e)

    def close(self):
        self.client.close()
