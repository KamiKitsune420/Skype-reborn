# Skype™ Reborn

A production-ready Skype 7-style clone built with Python, wxPython, and asyncio.

## Features
- **Accounts:** Registration and Login with JWT authentication.
- **Presence:** Real-time status updates (Online, Away, Busy, etc.).
- **Text Chat:** Real-time messaging via WebSockets with typing indicators.
- **Voice Calls:** Low-latency UDP audio relay with classic Skype ringtones.
- **Echo Service Bot:** A standalone bot for testing audio (Intro -> Record -> Playback).
- **File Transfer:** Chunked upload/download support.
- **Bot API:** Custom SDK for building automated agents.
- **Desktop UI:** Accessible wxPython interface optimized for screen readers (NVDA).
- **Web Client:** A modern browser-based interface for chat and contact management.

## Installation

1. **Clone the repository.**
2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## How to Run

### 1. Start the Server
```bash
python run_server.py
```
The server starts at `http://127.0.0.1:8000`.

### 2. Initialize and Start the Echo Bot
```bash
# Register the bot account (only needs to be done once)
python scripts/init_bots.py

# Start the bot process
python bots/echo_service_bot.py
```

### 3. Launch the Desktop Client
```bash
python run_client.py
```

### 4. Use the Web Client
Open `web/index.html` in your favorite web browser.

## Accessibility (Screen Readers)
- **Descriptive Labels:** All buttons and inputs are labeled for NVDA/Narrator.
- **Optimized Performance:** Throttled UI updates to prevent lag.
- **Keyboard Shortcuts:**
  - `Alt + 1`: Recent Chats
  - `Alt + 2`: Contacts
  - `Ctrl + Shift + S`: Search
  - `Alt + PgUp`: Answer Call
  - `Alt + PgDn`: Hang Up

## Project Structure
- `server/`: FastAPI backend and Voice Relay.
- `client/`: wxPython Desktop application.
- `web/`: Modern Web interface (HTML/JS/Bootstrap).
- `bots/`: Bot SDK and Echo Service bot.
- `shared/`: Protocol models.