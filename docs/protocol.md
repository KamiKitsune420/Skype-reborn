# Protocol Specification - Skype Reborn

## 1. Overview
The Skype Reborn protocol is divided into two parts:
1. **Signaling Protocol:** JSON-based messages sent over WebSocket/TLS.
2. **Media Protocol:** Binary packets sent over UDP (or tunneled via WebSocket).

## 2. Signaling Envelope
All signaling messages are wrapped in a standard JSON envelope:

```json
{
  "type": "MESSAGE_TYPE",
  "id": "uuid-v4",
  "timestamp": "ISO-8601-UTC",
  "payload": { ... }
}
```

## 3. Message Types

### 3.1 Authentication
- `AUTH_LOGIN`: Request JWT token.
- `AUTH_SUCCESS`: Token issued.
- `AUTH_FAILURE`: Error details.

### 3.2 Presence
- `PRESENCE_UPDATE`: Client notifies server of status change (Online, Away, Busy, Offline).
- `PRESENCE_BROADCAST`: Server notifies contacts of a user's status change.

### 3.3 Messaging
- `CHAT_SEND`: Client sends a message to a conversation.
- `CHAT_RECEIVE`: Server delivers a message to a recipient.
- `CHAT_ACK`: Acknowledgment of message delivery.
- `CHAT_TYPING`: Notification that a user is typing.

For direct 1:1 messages, clients send the other user's id in
`payload.conversation_id`. The server maps that pair to an internal
conversation record, ignores any client-supplied sender identity, and delivers
events with `payload.sender_id` set to the authenticated sender.

Offline direct messages are stored server-side with delivery metadata. When a
user reconnects to the WebSocket gateway, undelivered messages are replayed in
timestamp order and marked delivered after a successful WebSocket send.

### 3.4 Call Signaling
- `CALL_INITIATE`: Start a new call.
- `CALL_RINGING`: Receiver is being alerted.
- `CALL_ACCEPT`: Receiver accepted the call.
- `CALL_REJECT`: Receiver declined the call.
- `CALL_CANDIDATE`: Exchange network candidates (ICE-like).
- `CALL_HANGUP`: Terminate the session.

## 4. Media Protocol (Binary)
Media packets are sent over UDP with the following header:

| Field | Size | Description |
| :--- | :--- | :--- |
| Session ID | 16 bytes | UUID of the call session |
| Sequence | 2 bytes | Monotonically increasing packet number |
| Timestamp | 4 bytes | Milliseconds since start of call |
| Codec | 1 byte | 0x01: Opus, 0x02: PCM |
| Payload Len| 2 bytes | Length of the media data |
| Payload | Variable | Encoded audio data |

## 5. Error Codes
- `1000`: Success
- `4001`: Unauthorized
- `4002`: Invalid Payload
- `4003`: Forbidden
- `4004`: Not Found
- `5000`: Internal Server Error
