import asyncio
import threading
import structlog
import wx
import websockets
from shared.models import Envelope

logger = structlog.get_logger()


class WSClient:
    """WebSocket client running in a dedicated daemon thread.

    The receive loop runs inside that thread's own asyncio event loop so it
    never competes with wx for the main thread.  All incoming messages are
    delivered to the UI via wx.CallAfter, which guarantees they run on the
    main thread without any manual locking.

    Sending is thread-safe: call send_envelope() from any thread and it
    schedules the coroutine on the WS thread's loop via
    asyncio.run_coroutine_threadsafe().
    """

    def __init__(self, base_url: str, api_client):
        # Accept either http:// or ws:// base URL
        self._ws_base = (
            base_url
            .replace("http://", "ws://")
            .replace("https://", "wss://")
        )
        self.api_client = api_client
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        # Set by MainWindow before connect() is called
        self.on_message_callback = None
        self.on_disconnect_callback = None

    def connect(self):
        """Start the WS daemon thread. Non-blocking, safe to call from main thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._thread_main, daemon=True, name="WSClient"
        )
        self._thread.start()

    # ── Thread entry point ────────────────────────────────────────────

    def _thread_main(self):
        self._loop.run_until_complete(self._run())

    async def _run(self):
        # Fetch one-time ticket via the synchronous HTTP client.
        # We're already in our own thread so blocking here is fine.
        try:
            resp = self.api_client.client.post("/ws/ticket")
            if resp.status_code != 200:
                logger.error("WS: ticket request failed", status=resp.status_code)
                return
            ticket = resp.json()["ticket"]
        except Exception as e:
            logger.error("WS: could not get ticket", error=str(e))
            return

        url = f"{self._ws_base}/ws/{ticket}"
        try:
            async with websockets.connect(url) as ws:
                self._ws = ws
                logger.info("WS: connected")
                async for raw in ws:
                    try:
                        envelope = Envelope.model_validate_json(raw)
                        if self.on_message_callback:
                            # Deliver to main thread — never touch wx from this thread
                            wx.CallAfter(self.on_message_callback, envelope)
                    except Exception as e:
                        logger.error("WS: message parse error", error=str(e))
        except websockets.ConnectionClosed as e:
            logger.info("WS: connection closed", code=getattr(e, "code", "?"))
        except Exception as e:
            logger.error("WS: unexpected error", error=str(e))
        finally:
            self._ws = None
            if self.on_disconnect_callback:
                wx.CallAfter(self.on_disconnect_callback)

    # ── Send ─────────────────────────────────────────────────────────

    def send_envelope(self, envelope: Envelope):
        """Thread-safe. Schedule a send from any thread."""
        if self._ws is None or self._loop is None or self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._send(envelope.model_dump_json()), self._loop)

    async def _send(self, msg: str):
        if self._ws:
            try:
                await self._ws.send(msg)
            except Exception as e:
                logger.error("WS: send failed", error=str(e))

    # ── Lifecycle ────────────────────────────────────────────────────

    def close(self):
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
