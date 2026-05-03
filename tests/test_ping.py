"""Latency test: measures HTTP and WebSocket round-trip time to the server.

Run against the hosted server (default):
    pytest tests/test_ping.py -v -s

Run against a local dev server:
    SKYPE_SERVER_URL=http://127.0.0.1:8000 pytest tests/test_ping.py -v -s

The -s flag is needed to see the timing output printed to stdout.
"""
import asyncio
import os
import statistics
import time
import unittest
from uuid import uuid4

import httpx
import websockets

SERVER    = os.environ.get("SKYPE_SERVER_URL", "http://random-gaming.com:9433")
WS_SERVER = SERVER.replace("http://", "ws://").replace("https://", "wss://")
SAMPLES   = 10
MAX_AVG_MS = 5_000   # fail if average RTT exceeds 5 s


class TestLatency(unittest.IsolatedAsyncioTestCase):

    async def test_http_ping(self):
        """HTTP round-trip time.

        Uses GET /ping when the server supports it; falls back to
        POST /login (expecting 401) on older deployments that predate
        the /ping endpoint.  Either way the measured RTT is accurate.
        """
        times = []
        async with httpx.AsyncClient(base_url=SERVER, timeout=15) as client:
            # Detect whether this server version has /ping
            probe = await client.get("/ping")
            use_ping_endpoint = probe.status_code == 200

            endpoint_label = "GET /ping" if use_ping_endpoint else "POST /login (fallback)"

            for _ in range(SAMPLES):
                t0 = time.perf_counter()
                if use_ping_endpoint:
                    resp = await client.get("/ping")
                    self.assertEqual(resp.status_code, 200)
                else:
                    # POST /login with dummy creds — server always responds quickly
                    resp = await client.post(
                        "/login", json={"username": "_ping_", "password": "_ping_"}
                    )
                    self.assertIn(resp.status_code, (400, 401, 422))
                t1 = time.perf_counter()
                times.append((t1 - t0) * 1000)

        mn  = min(times)
        mx  = max(times)
        avg = statistics.mean(times)
        med = statistics.median(times)
        print(
            f"\n  HTTP {endpoint_label}  ({SAMPLES} samples)\n"
            f"    min={mn:.1f} ms   median={med:.1f} ms   "
            f"avg={avg:.1f} ms   max={mx:.1f} ms"
        )
        self.assertLess(avg, MAX_AVG_MS,
                        f"HTTP average latency {avg:.1f} ms exceeds {MAX_AVG_MS} ms")

    async def test_websocket_ping(self):
        """WebSocket ping/pong round-trip — measures real-time channel latency."""
        suffix = uuid4().hex[:8]
        username = f"pingtest_{suffix}"

        # Register a throw-away user and get a WS ticket
        async with httpx.AsyncClient(base_url=SERVER, timeout=15) as client:
            await client.post("/register", json={
                "username": username,
                "password": "Ping1234!",
                "email": f"{username}@ping.local",
                "first_name": "Ping",
                "last_name": "Test",
            })
            login = await client.post(
                "/login", json={"username": username, "password": "Ping1234!"}
            )
            self.assertEqual(login.status_code, 200,
                             f"Login failed: {login.text}")
            token = login.json()["token"]
            tr = await client.post(
                "/ws/ticket", headers={"Authorization": f"Bearer {token}"}
            )
            self.assertEqual(tr.status_code, 200)
            ticket = tr.json()["ticket"]

        times = []
        async with websockets.connect(f"{WS_SERVER}/ws/{ticket}",
                                      open_timeout=10) as ws:
            for _ in range(SAMPLES):
                t0 = time.perf_counter()
                pong_waiter = await ws.ping()
                await asyncio.wait_for(pong_waiter, timeout=10)
                t1 = time.perf_counter()
                times.append((t1 - t0) * 1000)

        mn  = min(times)
        mx  = max(times)
        avg = statistics.mean(times)
        med = statistics.median(times)
        print(
            f"\n  WebSocket ping  ({SAMPLES} samples)\n"
            f"    min={mn:.1f} ms   median={med:.1f} ms   "
            f"avg={avg:.1f} ms   max={mx:.1f} ms"
        )
        self.assertLess(avg, MAX_AVG_MS,
                        f"WebSocket average latency {avg:.1f} ms exceeds {MAX_AVG_MS} ms")


if __name__ == "__main__":
    unittest.main()
