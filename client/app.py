import asyncio
import wx
from wxasync import WxAsyncApp
from .ui.login import LoginFrame
from .ui.main_window import MainWindow
from .network.api_client import APIClient
from .network.ws_client import WSClient
import structlog

logger = structlog.get_logger()

class SkypeRebornApp:
    def __init__(self):
        self.app = WxAsyncApp()
        self.api_client = APIClient("http://127.0.0.1:8000") 
        self.ws_client = WSClient("ws://127.0.0.1:8000", self.api_client)
        self.login_frame = None
        self.main_window = None

    async def on_login_success(self, user_data):
        logger.info("Login successful", user_id=user_data["user_id"])
        
        # Connect to WebSocket
        ws_success = await self.ws_client.connect()
        if not ws_success:
            logger.error("Failed to connect to WebSocket")
            # Maybe show an error in UI
        
        self.login_frame.Hide()
        self.main_window = MainWindow(self.api_client, self.ws_client, user_data)
        self.main_window.Show()

    async def run(self):
        self.login_frame = LoginFrame(self.api_client, self.on_login_success)
        self.login_frame.Show()
        await self.app.MainLoop()

if __name__ == "__main__":
    skype_app = SkypeRebornApp()
    asyncio.run(skype_app.run())
