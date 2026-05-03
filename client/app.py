import os
import wx
import structlog
from .network.api_client import APIClient
from .network.ws_client import WSClient
from .services.auth import AuthService

logger = structlog.get_logger()

_SERVER_URL = os.environ.get("SKYPE_SERVER_URL", "http://random-gaming.com:9433")


class SkypeRebornApp:
    def __init__(self):
        self.app = wx.App()
        self.api_client = APIClient(_SERVER_URL)
        self.auth_service = AuthService(self.api_client)
        self.ws_client = WSClient(_SERVER_URL, self.api_client)
        self.login_frame = None
        self.main_window = None

    def on_login_success(self, user_data):
        """Runs on the main thread (dispatched via wx.CallAfter from login thread)."""
        logger.info("Login successful", user_id=user_data["user_id"])

        # Import here to keep startup fast
        from .ui.main_window import MainWindow

        # Create main window first — its __init__ registers the WS message callback.
        # We connect the WebSocket AFTER so the callback is guaranteed to be set
        # before any messages can arrive.
        self.main_window = MainWindow(self.api_client, self.ws_client, user_data)
        self.ws_client.connect()

        self.login_frame.Hide()
        self.main_window.Show()

    def run(self):
        from .ui.login import LoginFrame
        self.login_frame = LoginFrame(self.auth_service, self.on_login_success)
        self.login_frame.Show()
        self.app.MainLoop()
