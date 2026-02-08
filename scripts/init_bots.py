import asyncio
import httpx
from server.bots.sdk import BotSDK

async def setup_echo_bot():
    base_url = "http://127.0.0.1:8000"
    username = "echo_service"
    password = "botpassword"
    
    payload = {
        "username": username,
        "password": password,
        "email": "echo@system.local",
        "first_name": "Echo",
        "last_name": "Service"
    }
    
    async with httpx.AsyncClient() as client:
        # Try to register
        print(f"Registering {username}...")
        resp = await client.post(f"{base_url}/register", json=payload)
        if resp.status_code == 200:
            print("Echo service registered successfully.")
        else:
            print(f"Registration note: {resp.json().get('detail', 'Already exists?')}")

if __name__ == "__main__":
    asyncio.run(setup_echo_bot())
