"""Integration test for the call signalling flow against the hosted server.

Exercises the full CALL_INITIATE → CALL_ACCEPT → CALL_HANGUP exchange
over a real WebSocket connection.  UDP voice audio is not tested here
(that requires real hardware); this validates the signalling path only.

Run against the hosted server (default):
    pytest tests/test_calling.py -v

Run against a local dev server:
    SKYPE_SERVER_URL=http://127.0.0.1:8000 pytest tests/test_calling.py -v
"""
import asyncio
import os
import unittest
from uuid import uuid4

import httpx
import websockets

from shared.models import CallSignalPayload, Envelope, MessageType

SERVER    = os.environ.get("SKYPE_SERVER_URL", "http://random-gaming.com:9433")
WS_SERVER = SERVER.replace("http://", "ws://").replace("https://", "wss://")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register_and_login(client: httpx.AsyncClient, username: str):
    """Register (ignore 400 = already exists) then login; return (token, user_id)."""
    await client.post(
        "/register",
        json={
            "username": username,
            "password": "Testpass123!",
            "email": f"{username}@calltest.local",
            "first_name": "Call",
            "last_name": "Test",
        },
    )
    login = await client.post(
        "/login", json={"username": username, "password": "Testpass123!"}
    )
    assert login.status_code == 200, f"Login failed for {username}: {login.text}"
    data = login.json()
    return data["token"], data["user_id"]


async def _ws_ticket(client: httpx.AsyncClient, token: str) -> str:
    resp = await client.post(
        "/ws/ticket", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, f"Ticket request failed: {resp.text}"
    return resp.json()["ticket"]


async def _recv_until(ws, predicate, timeout: float = 8.0) -> Envelope:
    """Read envelopes until predicate(envelope) is truthy, then return it."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for envelope matching predicate")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        env = Envelope.model_validate_json(raw)
        if predicate(env):
            return env


# ── Test ──────────────────────────────────────────────────────────────────────

class TestCallSignalling(unittest.IsolatedAsyncioTestCase):
    """Full call-signalling round-trip against the hosted server."""

    async def asyncSetUp(self):
        suffix = uuid4().hex[:8]
        self._alice_name = f"alice_{suffix}"
        self._bob_name   = f"bob_{suffix}"

        async with httpx.AsyncClient(base_url=SERVER, timeout=15) as client:
            alice_token, self._alice_id = await _register_and_login(client, self._alice_name)
            bob_token,   self._bob_id   = await _register_and_login(client, self._bob_name)

            ah = {"Authorization": f"Bearer {alice_token}"}
            bh = {"Authorization": f"Bearer {bob_token}"}

            # Mutual contact so they have permission to call each other
            r1 = await client.post("/contacts/add", json={"username": self._bob_name},   headers=ah)
            r2 = await client.post("/contacts/add", json={"username": self._alice_name}, headers=bh)
            assert r1.status_code == 200, f"Alice → Bob add failed: {r1.text}"
            assert r2.status_code == 200, f"Bob → Alice add failed: {r2.text}"

            self._alice_ticket = await _ws_ticket(client, alice_token)
            self._bob_ticket   = await _ws_ticket(client, bob_token)

    async def test_initiate_accept_hangup(self):
        session_id = str(uuid4())

        async with websockets.connect(f"{WS_SERVER}/ws/{self._alice_ticket}") as alice_ws:
            async with websockets.connect(f"{WS_SERVER}/ws/{self._bob_ticket}") as bob_ws:

                # ── 1. Alice initiates ────────────────────────────────
                await alice_ws.send(Envelope(
                    type=MessageType.CALL_INITIATE,
                    payload=CallSignalPayload(
                        session_id=session_id,
                        target_id=self._bob_id,
                        sender_id=self._alice_id,
                    ).model_dump(),
                ).model_dump_json())

                # ── 2. Bob receives CALL_INITIATE ─────────────────────
                incoming = await _recv_until(
                    bob_ws, lambda e: e.type == MessageType.CALL_INITIATE
                )
                pl = CallSignalPayload(**incoming.payload)
                self.assertEqual(pl.session_id, session_id)
                self.assertEqual(pl.sender_id, self._alice_id)

                # ── 3. Bob accepts ────────────────────────────────────
                await bob_ws.send(Envelope(
                    type=MessageType.CALL_ACCEPT,
                    payload=CallSignalPayload(
                        session_id=session_id,
                        target_id=self._alice_id,
                        sender_id=self._bob_id,
                    ).model_dump(),
                ).model_dump_json())

                # ── 4. Alice receives CALL_ACCEPT ─────────────────────
                accepted = await _recv_until(
                    alice_ws, lambda e: e.type == MessageType.CALL_ACCEPT
                )
                pl = CallSignalPayload(**accepted.payload)
                self.assertEqual(pl.session_id, session_id)
                self.assertEqual(pl.sender_id, self._bob_id)

                # ── 5. Alice hangs up ─────────────────────────────────
                await alice_ws.send(Envelope(
                    type=MessageType.CALL_HANGUP,
                    payload=CallSignalPayload(
                        session_id=session_id,
                        target_id=self._bob_id,
                        sender_id=self._alice_id,
                    ).model_dump(),
                ).model_dump_json())

                # ── 6. Bob receives CALL_HANGUP ───────────────────────
                hung = await _recv_until(
                    bob_ws, lambda e: e.type == MessageType.CALL_HANGUP
                )
                pl = CallSignalPayload(**hung.payload)
                self.assertEqual(pl.session_id, session_id)

    async def test_reject_call(self):
        """Callee can decline; caller should receive CALL_REJECT."""
        session_id = str(uuid4())

        async with websockets.connect(f"{WS_SERVER}/ws/{self._alice_ticket}") as alice_ws:
            async with websockets.connect(f"{WS_SERVER}/ws/{self._bob_ticket}") as bob_ws:

                await alice_ws.send(Envelope(
                    type=MessageType.CALL_INITIATE,
                    payload=CallSignalPayload(
                        session_id=session_id,
                        target_id=self._bob_id,
                        sender_id=self._alice_id,
                    ).model_dump(),
                ).model_dump_json())

                await _recv_until(bob_ws, lambda e: e.type == MessageType.CALL_INITIATE)

                # Bob rejects
                await bob_ws.send(Envelope(
                    type=MessageType.CALL_REJECT,
                    payload=CallSignalPayload(
                        session_id=session_id,
                        target_id=self._alice_id,
                        sender_id=self._bob_id,
                    ).model_dump(),
                ).model_dump_json())

                rejected = await _recv_until(
                    alice_ws, lambda e: e.type == MessageType.CALL_REJECT
                )
                pl = CallSignalPayload(**rejected.payload)
                self.assertEqual(pl.session_id, session_id)


if __name__ == "__main__":
    unittest.main()
