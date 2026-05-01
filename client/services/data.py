from __future__ import annotations

from typing import Any

from client.network.api_client import APIClient


class ClientDataService:
    """HTTP-backed data operations used by UI screens."""

    def __init__(self, api_client: APIClient):
        self._api = api_client

    def get_contacts(self) -> list[dict[str, Any]]:
        return self._api.get_contacts()

    def search_users(self, query: str) -> list[dict[str, Any]]:
        return self._api.search_users(query)

    def add_contact(self, username: str):
        return self._api.add_contact(username)

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._api.get_messages(conversation_id)

    def upload_file(self, recipient_id: str, filename: str, content: bytes):
        return self._api.upload_file(recipient_id, filename, content)

    def get_profile(self) -> dict[str, Any]:
        return self._api.get_profile()

    def update_profile(self, **fields) -> bool:
        return self._api.update_profile(**fields)

    def close(self):
        self._api.close()
