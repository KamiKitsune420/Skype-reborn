"""
Run the Skype Reborn client against a LOCAL server on this machine.
No environment variable needed — just:

    python run_client_local.py

Make sure the server is running first:
    python run_server.py
"""
import os

# Set BEFORE importing anything that reads it
os.environ["SKYPE_SERVER_URL"] = "http://127.0.0.1:9433"

from client.app import SkypeRebornApp

if __name__ == "__main__":
    app = SkypeRebornApp()
    app.run()
