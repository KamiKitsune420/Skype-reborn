"""
Launch the Skype Reborn desktop client.

Remote server (default):
    python run_client.py

Local server (for testing):
    set SKYPE_SERVER_URL=http://127.0.0.1:9433   (Windows cmd)
    $env:SKYPE_SERVER_URL="http://127.0.0.1:9433" (PowerShell)
    SKYPE_SERVER_URL=http://127.0.0.1:9433        (Linux/macOS)
    ... then:
    python run_client.py
"""
from client.app import SkypeRebornApp

if __name__ == "__main__":
    app = SkypeRebornApp()
    app.run()
