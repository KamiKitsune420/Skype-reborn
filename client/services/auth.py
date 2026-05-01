from __future__ import annotations

from typing import Any

from client.network.api_client import APIClient


class AuthService:
    """Authentication operations for login and registration screens."""

    def __init__(self, api_client: APIClient):
        self._api = api_client

    def login(self, username: str, password: str) -> tuple[bool, Any]:
        return self._api.login(username, password)

    def register(self, data: dict[str, str]) -> tuple[bool, str]:
        return self._api.register(data)
