import asyncio
from client.app import SkypeRebornApp

if __name__ == "__main__":
    app = SkypeRebornApp()
    asyncio.run(app.run())
