# Architecture Overview - Skype Reborn

## 1. Introduction
Skype Reborn is a production-ready clone of the classic Skype 7 experience, built using Python, wxPython, and asyncio. It employs a custom open protocol for signaling and real-time communication.

## 2. Transport Layer
- **Signaling (Control Plane):** WebSocket over TLS (WSS). This handles authentication, contact management, presence updates, chat messaging, and call negotiation.
- **Voice/Media (Data Plane):** UDP for low-latency real-time audio. 
    - **Fallback:** If UDP is blocked, media is tunneled through the WebSocket connection.
- **API (Management):** FastAPI-based REST endpoints for initial authentication (registration, login) and large file transfers.

## 3. Core Components
- **Server:**
    - **Gateway:** Handles WebSocket connections and routing.
    - **Auth Service:** Manages user registration, JWT issuance, and session validation.
    - **Presence Service:** Tracks user status (Online, Away, Busy, etc.) and broadcasts changes.
    - **Messaging Service:** Routes real-time messages and manages offline message storage.
    - **Voice Relay:** Forwards UDP audio packets between peers or provides mixing for group calls.
    - **Storage:** Pluggable interface (SQLAlchemy). Defaults to SQLite for development, supports PostgreSQL for production.
- **Client:**
    - **UI Layer (wxPython):** Desktop interface mimicking the Skype 7 aesthetic.
    - **Network Layer:** Manages WSS and UDP connections using asyncio.
    - **Audio Engine:** Uses `sounddevice` and `numpy` for capture/playback. Jitter buffer for smooth audio.
    - **Local Cache:** SQLite for message history and contact list persistence.
- **Bots:**
    - **Bot SDK:** A Python-based SDK for creating automated agents.
    - **Example Bots:** Echo, Help, and Diagnostics bots.

## 4. Security Model
- **Transport Security:** All communication (REST, WSS, UDP) is encrypted via TLS/DTLS.
- **Authentication:** JWT (JSON Web Tokens) for session management.
- **Credential Storage:** Argon2 for password hashing.
- **Privacy:** Transport-level encryption is mandatory. End-to-end encryption (E2EE) is scoped as a future enhancement.

## 5. Data Model
- **User:** ID, Username, Password Hash, Display Name, Avatar, Status.
- **Contact:** User ID, Friend ID, Status (Pending, Accepted, Blocked).
- **Conversation:** ID, Participants, Type (1:1 or Group).
- **Message:** ID, Conversation ID, Sender ID, Content, Timestamp, Type.
- **Call Session:** ID, Initiator, Participants, Status (Initiated, Active, Ended), Start/End Times.

## 6. Accessibility
- Standard wxPython controls with proper focus order.
- Keyboard shortcuts for common actions.
- Sound cues for notifications (logon, message received, incoming call).

## 7. Observability
- **Logging:** Structured JSON logs using `structlog`.
- **Metrics:** Minimal Prometheus-compatible endpoints on the server.
