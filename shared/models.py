from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

class MessageType(str, Enum):
    # Auth
    AUTH_LOGIN = "AUTH_LOGIN"
    AUTH_SUCCESS = "AUTH_SUCCESS"
    AUTH_FAILURE = "AUTH_FAILURE"
    
    # Presence / Profile
    PRESENCE_UPDATE = "PRESENCE_UPDATE"
    PRESENCE_BROADCAST = "PRESENCE_BROADCAST"
    PROFILE_UPDATE = "PROFILE_UPDATE" # New
    
    # Messaging
    CHAT_SEND = "CHAT_SEND"
    CHAT_RECEIVE = "CHAT_RECEIVE"
    CHAT_ACK = "CHAT_ACK"
    CHAT_TYPING = "CHAT_TYPING"
    
    # Call Signaling
    CALL_INITIATE = "CALL_INITIATE"
    CALL_CONNECTING = "CALL_CONNECTING"
    CALL_RINGING = "CALL_RINGING"
    CALL_ACCEPT = "CALL_ACCEPT"
    CALL_REJECT = "CALL_REJECT"
    CALL_CANDIDATE = "CALL_CANDIDATE"
    CALL_HANGUP = "CALL_HANGUP"
    
    # Contacts
    CONTACT_REQUEST = "CONTACT_REQUEST"
    
    # Error
    ERROR = "ERROR"

class UserStatus(str, Enum):
    ONLINE = "ONLINE"
    AWAY = "AWAY"
    BUSY = "BUSY"
    INVISIBLE = "INVISIBLE"
    OFFLINE = "OFFLINE"

class Envelope(BaseModel):
    type: MessageType
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: Optional[Dict[str, Any]] = None

# Specific Payloads
class LoginPayload(BaseModel):
    username: str
    password: str

class RegisterPayload(BaseModel):
    username: str
    password: str
    email: str
    first_name: str
    last_name: str

class AuthSuccessPayload(BaseModel):
    token: str
    user_id: str

class PresenceUpdatePayload(BaseModel):
    user_id: str
    status: UserStatus
    status_message: Optional[str] = None

class ProfileUpdatePayload(BaseModel):
    user_id: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    mood: Optional[str] = None
    country: Optional[str] = None
    hometown: Optional[str] = None
    birthday: Optional[str] = None

class SettingsPayload(BaseModel):
    push_to_talk: bool = False
    notification_sounds: bool = True
    theme: str = "Classic"
    input_device: str = "Default"
    output_device: str = "Default"
    camera_device: str = "Default"
    ringtone: str = "call_ring1.wav"

class ChatMessagePayload(BaseModel):
    conversation_id: str
    sender_id: str
    content: str
    message_type: str = "text"
    timestamp: Optional[datetime] = None

class ChatTypingPayload(BaseModel):
    conversation_id: str
    user_id: str
    is_typing: bool

class ContactAddPayload(BaseModel):
    username: str
    from_user_id: Optional[str] = None
    from_username: Optional[str] = None

class CallSignalPayload(BaseModel):
    session_id: str
    target_id: str
    sender_id: str
    data: Optional[Dict[str, Any]] = None

class ErrorPayload(BaseModel):
    code: int
    message: str