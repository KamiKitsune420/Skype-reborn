import asyncio
import os
import sys
import aiofiles
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from uuid import uuid4
from .database import (
    get_db,
    init_db,
    User,
    Message as DBMessage,
    Contact,
    Conversation,
    ConversationParticipant,
    FileTransfer,
    SessionLocal,
)
from .auth import get_password_hash, verify_password, create_access_token, get_current_user
from .voice_relay import start_voice_relay
from .manager import manager
from .config import settings
from shared.models import (
    Envelope, MessageType, LoginPayload, AuthSuccessPayload,
    ChatMessagePayload, ContactAddPayload, CallSignalPayload,
    PresenceUpdatePayload, UserStatus, ProfileUpdatePayload, ChatTypingPayload,
    RegisterPayload, ErrorPayload, ChatAckPayload,
)
import structlog

logger = structlog.get_logger()

_BOT_ACCOUNTS = [
    {
        "username":     "echo_service",
        "password":     "botpassword",
        "email":        "echo_service@system.local",
        "first_name":   "Echo",
        "last_name":    "Service",
        "display_name": "Echo / Sound Test",
    },
]


def _is_bot_user(user: User) -> bool:
    return user.username.endswith("_service")


def _direct_conversation_key(user_a: str, user_b: str) -> str:
    return "|".join(sorted([user_a, user_b]))


async def _get_user_by_id_or_username(db: AsyncSession, identifier: str) -> User | None:
    result = await db.execute(
        select(User).where(or_(User.id == identifier, User.username == identifier))
    )
    return result.scalars().first()


async def _users_can_message(db: AsyncSession, sender: User, target: User) -> bool:
    if sender.id == target.id:
        return False
    if _is_bot_user(sender) or _is_bot_user(target):
        return True
    result = await db.execute(
        select(Contact).where(
            Contact.user_id == sender.id,
            Contact.contact_user_id == target.id,
            Contact.status == "ACCEPTED",
        )
    )
    return result.scalars().first() is not None


async def _get_or_create_direct_conversation(
    db: AsyncSession, user_a: str, user_b: str
) -> Conversation:
    direct_key = _direct_conversation_key(user_a, user_b)
    result = await db.execute(
        select(Conversation).where(Conversation.direct_key == direct_key)
    )
    conversation = result.scalars().first()
    if conversation:
        return conversation

    conversation = Conversation(type="direct", direct_key=direct_key)
    db.add(conversation)
    await db.flush()
    db.add_all(
        [
            ConversationParticipant(conversation_id=conversation.id, user_id=user_a),
            ConversationParticipant(conversation_id=conversation.id, user_id=user_b),
        ]
    )
    await db.flush()
    return conversation


def _message_payload_for_recipient(message: DBMessage) -> ChatMessagePayload:
    return ChatMessagePayload(
        conversation_id=message.sender_id,
        sender_id=message.sender_id,
        content=message.content,
        message_type=message.message_type,
        timestamp=message.timestamp,
    )


async def _deliver_offline_messages(user_id: str):
    async with SessionLocal() as db:
        result = await db.execute(
            select(DBMessage)
            .where(DBMessage.recipient_id == user_id, DBMessage.delivered_at.is_(None))
            .order_by(DBMessage.timestamp.asc())
        )
        messages = result.scalars().all()
        delivered_any = False
        for message in messages:
            envelope = Envelope(
                type=MessageType.CHAT_RECEIVE,
                payload=_message_payload_for_recipient(message).model_dump(),
            )
            if await manager.send_personal_message(envelope.model_dump_json(), user_id):
                message.delivered_at = datetime.utcnow()
                delivered_any = True
        if delivered_any:
            await db.commit()

async def ensure_bots_registered():
    """Create bot accounts that don't yet exist and wire them as contacts for all users."""
    async with SessionLocal() as db:
        for spec in _BOT_ACCOUNTS:
            res = await db.execute(select(User).where(User.username == spec["username"]))
            bot_user = res.scalars().first()
            if not bot_user:
                bot_user = User(
                    username=spec["username"],
                    email=spec["email"],
                    password_hash=get_password_hash(spec["password"]),
                    first_name=spec["first_name"],
                    last_name=spec["last_name"],
                    display_name=spec["display_name"],
                    status="ONLINE",
                )
                db.add(bot_user)
                await db.flush()
                logger.info("Bot account created", username=spec["username"])

            # Ensure every existing non-bot user has this bot in their contact list
            all_users = await db.execute(
                select(User).where(User.id != bot_user.id, ~User.username.like("%_service%"))
            )
            for user in all_users.scalars().all():
                exists = await db.execute(
                    select(Contact).where(
                        Contact.user_id == user.id,
                        Contact.contact_user_id == bot_user.id,
                    )
                )
                if not exists.scalars().first():
                    db.add(Contact(user_id=user.id, contact_user_id=bot_user.id))

        await db.commit()


async def start_bots():
    bot_dir = "server/bots"
    if not os.path.exists(bot_dir):
        return []

    # Bots import from the project root (e.g. `from server.bots.sdk import ...`).
    # When launched as a script their sys.path[0] is server/bots/, which breaks
    # those imports.  Pass PYTHONPATH so they can reach the project root.
    project_root = os.getcwd()
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

    bots = [f for f in os.listdir(bot_dir) if f.endswith("_bot.py")]
    processes = []
    for bot in bots:
        bot_path = os.path.join(bot_dir, bot)
        logger.info(f"Starting bot: {bot}")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, bot_path,   # use same Python as server
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        processes.append(proc)
    return processes

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await ensure_bots_registered()
    asyncio.create_task(start_voice_relay())
    if not os.path.exists(settings.UPLOAD_DIR):
        os.makedirs(settings.UPLOAD_DIR)
    logger.info("Database initialized and Voice Relay started")

    bot_processes = await start_bots()

    yield
    # Shutdown
    logger.info("Server shutting down")
    for proc in bot_processes:
        try:
            proc.terminate()
            await proc.wait()
        except Exception:
            pass

app = FastAPI(title="Skype Reborn Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Auth Routes ---

@app.post("/register")
async def register(payload: RegisterPayload, db: AsyncSession = Depends(get_db)):
    taken_user = await db.execute(select(User).where(User.username == payload.username))
    if taken_user.scalars().first():
        raise HTTPException(status_code=400, detail="That Skype Name is already taken. Please choose another.")
    taken_email = await db.execute(select(User).where(User.email == payload.email))
    if taken_email.scalars().first():
        raise HTTPException(status_code=400, detail="An account with that email already exists.")
    
    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        display_name=f"{payload.first_name} {payload.last_name}"
    )
    db.add(user)
    await db.flush() # Get user ID
    
    # Add echo_service as default contact
    res_echo = await db.execute(select(User).where(User.username == "echo_service"))
    echo_user = res_echo.scalars().first()
    if echo_user:
        # Check if already a contact
        existing_contact = await db.execute(select(Contact).where(Contact.user_id == user.id, Contact.contact_user_id == echo_user.id))
        if not existing_contact.scalars().first():
            contact = Contact(user_id=user.id, contact_user_id=echo_user.id)
            db.add(contact)
    
    await db.commit()
    return {"message": "User registered successfully"}

@app.post("/login")
async def login(payload: LoginPayload, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalars().first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.username})
    return {"token": access_token, "user_id": user.id, "username": user.username}

# --- Contact Routes ---

@app.get("/contacts")
async def get_contacts(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 1. Get explicit contacts
    stmt = select(User).join(Contact, Contact.contact_user_id == User.id).where(Contact.user_id == current_user.id)
    result = await db.execute(stmt)
    contacts = list(result.scalars().all())
    
    # 2. Add System Bots (all users that are not the current user and are bots)
    # For simplicity, we assume users with "echo_service" or registered via init_bots are bots.
    # In a real app, you'd have an 'is_bot' flag in the User model.
    bot_stmt = select(User).where(User.username.like("%_service%"), User.id != current_user.id)
    bot_result = await db.execute(bot_stmt)
    bots = bot_result.scalars().all()
    
    # Merge unique
    contact_ids = {c.id for c in contacts}
    for bot in bots:
        if bot.id not in contact_ids:
            contacts.append(bot)

    return [{"id": c.id, "username": c.username, "display_name": c.display_name,
             "status": c.status, "mood_message": c.mood_message or "",
             "is_bot": _is_bot_user(c)} for c in contacts]

@app.post("/contacts/add")
async def add_contact(payload: ContactAddPayload, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).where(User.username == payload.username))
    contact_user = res.scalars().first()
    if not contact_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if contact_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot add yourself")

    existing = await db.execute(select(Contact).where(Contact.user_id == current_user.id, Contact.contact_user_id == contact_user.id))
    if existing.scalars().first():
        return {"message": "Already in contacts"}
    
    contact = Contact(user_id=current_user.id, contact_user_id=contact_user.id)
    contact_rev = Contact(user_id=contact_user.id, contact_user_id=current_user.id)
    db.add_all([contact, contact_rev])
    
    await db.commit()
    
    notification = Envelope(
        type=MessageType.CONTACT_REQUEST,
        payload=ContactAddPayload(username=payload.username, from_user_id=current_user.id, from_username=current_user.username).model_dump()
    )
    await manager.send_personal_message(notification.model_dump_json(), contact_user.id)
    
    return {"message": "Contact added"}

# --- Messaging Routes ---

@app.get("/messages/{conversation_id}")
async def get_messages(conversation_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    peer = await _get_user_by_id_or_username(db, conversation_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Conversation user not found")
    if not await _users_can_message(db, current_user, peer):
        raise HTTPException(status_code=403, detail="Access denied")

    direct_key = _direct_conversation_key(current_user.id, peer.id)
    conv_res = await db.execute(
        select(Conversation).where(Conversation.direct_key == direct_key)
    )
    conversation = conv_res.scalars().first()
    if not conversation:
        return []

    stmt = select(DBMessage).where(DBMessage.conversation_id == conversation.id).order_by(DBMessage.timestamp.asc())
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return messages

@app.get("/users/search")
async def search_users(query: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = (
        select(User)
        .where(
            User.id != current_user.id,
            or_(
                User.username.ilike(f"%{query}%"),
                User.display_name.ilike(f"%{query}%"),
            ),
        )
        .limit(20)
    )
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [
        {
            "id":           u.id,
            "username":     u.username,
            "display_name": u.display_name,
            "status":       u.status,
            "mood_message": u.mood_message or "",
            "is_bot":       "_service" in u.username,
        }
        for u in users
    ]

@app.post("/profile/update")
async def update_profile(payload: ProfileUpdatePayload, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if payload.display_name is not None:
        current_user.display_name = payload.display_name
    if payload.mood is not None:
        current_user.mood_message = payload.mood
    if payload.country is not None:
        current_user.country = payload.country
    if payload.hometown is not None:
        current_user.hometown = payload.hometown
    if payload.birthday is not None:
        current_user.birthday = payload.birthday
    await db.commit()
    return {"message": "Profile updated"}

@app.get("/profile/me")
async def get_my_profile(current_user: User = Depends(get_current_user)):
    return {
        "id":           current_user.id,
        "username":     current_user.username,
        "display_name": current_user.display_name,
        "email":        current_user.email,
        "first_name":   current_user.first_name,
        "last_name":    current_user.last_name,
        "mood_message": current_user.mood_message or "",
        "country":      current_user.country or "",
        "hometown":     current_user.hometown or "",
        "birthday":     current_user.birthday or "",
        "status":       current_user.status,
    }

# --- File Transfer ---

@app.post("/upload/{recipient_id}")
async def upload_file(recipient_id: str, filename: str, file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    file_id = str(uuid4())
    file_path = os.path.join(settings.UPLOAD_DIR, file_id)
    
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
    
    # Track in DB
    transfer = FileTransfer(
        id=file_id,
        conversation_id=recipient_id, # Simplified: recipient_id is the conversation
        sender_id=current_user.id,
        recipient_id=recipient_id,
        filename=filename,
        file_size=len(content),
        status="COMPLETED"
    )
    db.add(transfer)
    await db.commit()

    # Notify recipient via WS
    notification = Envelope(
        type=MessageType.CHAT_RECEIVE,
        payload=ChatMessagePayload(
            conversation_id=current_user.id,
            sender_id=current_user.id,
            content=f"Sent a file: {filename}",
            message_type="file"
        ).model_dump()
    )
    await manager.send_personal_message(notification.model_dump_json(), recipient_id)

    return {"file_id": file_id, "message": "File uploaded"}

@app.get("/transfers/{conversation_id}")
async def get_transfers(conversation_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(FileTransfer).where(FileTransfer.conversation_id == conversation_id).order_by(FileTransfer.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

@app.get("/download/{file_id}")
async def download_file(file_id: str, current_user: User = Depends(get_current_user)):
    file_path = os.path.join(settings.UPLOAD_DIR, file_id)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

# --- Ping ---

@app.get("/ping")
async def ping():
    """Lightweight latency probe — no auth required."""
    return {"pong": True}

# --- WebSocket Gateway ---

@app.post("/ws/ticket")
async def get_ws_ticket(current_user: User = Depends(get_current_user)):
    ticket = manager.create_ticket(current_user.id)
    return {"ticket": ticket}

@app.websocket("/ws/{ticket}")
async def websocket_endpoint(websocket: WebSocket, ticket: str):
    user_id = await manager.connect(ticket, websocket)
    if not user_id:
        return

    # Persist ONLINE status so contact list queries reflect the real state
    async with SessionLocal() as db:
        res = await db.execute(select(User).where(User.id == user_id))
        user = res.scalars().first()
        if user:
            user.status = UserStatus.ONLINE.value
            await db.commit()

    await _deliver_offline_messages(user_id)

    # Send initial statuses of contacts
    async with SessionLocal() as db:
        stmt = select(User).join(Contact, Contact.contact_user_id == User.id).where(Contact.user_id == user_id)
        result = await db.execute(stmt)
        contacts = result.scalars().all()
        contact_list = [{"id": c.id, "status": c.status} for c in contacts]
        await manager.send_initial_statuses(user_id, contact_list)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                envelope = Envelope.model_validate_json(data)
                
                if envelope.type == MessageType.CHAT_SEND:
                    chat_payload = ChatMessagePayload(**envelope.payload)
                    async with SessionLocal() as db:
                        sender = await _get_user_by_id_or_username(db, user_id)
                        target = await _get_user_by_id_or_username(db, chat_payload.conversation_id)
                        if not sender or not target:
                            raise ValueError("Target user not found")
                        if not await _users_can_message(db, sender, target):
                            raise ValueError("You are not allowed to message this user")
                        conversation = await _get_or_create_direct_conversation(
                            db, sender.id, target.id
                        )
                        db_msg = DBMessage(
                            conversation_id=conversation.id,
                            sender_id=user_id,
                            recipient_id=target.id,
                            content=chat_payload.content,
                            message_type=chat_payload.message_type,
                        )
                        db.add(db_msg)
                        await db.commit()
                    
                    resp = Envelope(
                        type=MessageType.CHAT_RECEIVE,
                        payload=_message_payload_for_recipient(db_msg).model_dump(),
                    )
                    if await manager.send_personal_message(resp.model_dump_json(), db_msg.recipient_id):
                        async with SessionLocal() as db:
                            res = await db.execute(
                                select(DBMessage).where(DBMessage.id == db_msg.id)
                            )
                            delivered_msg = res.scalars().first()
                            if delivered_msg:
                                delivered_msg.delivered_at = datetime.utcnow()
                                await db.commit()

                elif envelope.type == MessageType.PRESENCE_UPDATE:
                    presence_payload = PresenceUpdatePayload(**envelope.payload)
                    async with SessionLocal() as db:
                        res = await db.execute(select(User).where(User.id == user_id))
                        user = res.scalars().first()
                        if user:
                            user.status = presence_payload.status.value
                            await db.commit()
                            await manager.broadcast_presence(user_id, presence_payload.status)

                elif envelope.type == MessageType.CHAT_TYPING:
                    typing_payload = ChatTypingPayload(**envelope.payload)
                    async with SessionLocal() as db:
                        sender = await _get_user_by_id_or_username(db, user_id)
                        target = await _get_user_by_id_or_username(db, typing_payload.conversation_id)
                        if not sender or not target:
                            raise ValueError("Target user not found")
                        if not await _users_can_message(db, sender, target):
                            raise ValueError("You are not allowed to message this user")
                    normalized = ChatTypingPayload(
                        conversation_id=user_id,
                        user_id=user_id,
                        is_typing=typing_payload.is_typing,
                    )
                    resp = Envelope(type=MessageType.CHAT_TYPING, payload=normalized.model_dump())
                    await manager.send_personal_message(resp.model_dump_json(), target.id)

                elif envelope.type == MessageType.CHAT_ACK:
                    ack = ChatAckPayload(**envelope.payload)
                    # Mark all unread messages from peer → this user as read
                    async with SessionLocal() as db:
                        res = await db.execute(
                            select(DBMessage).where(
                                DBMessage.sender_id == ack.peer_id,
                                DBMessage.recipient_id == user_id,
                                DBMessage.read_at == None,  # noqa: E711
                            )
                        )
                        for msg in res.scalars().all():
                            msg.read_at = datetime.utcnow()
                        await db.commit()
                    # Forward receipt to the peer so their UI shows "Read"
                    fwd = Envelope(
                        type=MessageType.CHAT_ACK,
                        payload=ChatAckPayload(peer_id=ack.peer_id, reader_id=user_id).model_dump(),
                    )
                    await manager.send_personal_message(fwd.model_dump_json(), ack.peer_id)

                elif envelope.type in [MessageType.CALL_INITIATE, MessageType.CALL_ACCEPT, 
                                     MessageType.CALL_REJECT, MessageType.CALL_HANGUP,
                                     MessageType.CALL_RINGING, MessageType.CALL_CANDIDATE,
                                     MessageType.CALL_CONNECTING]:
                    call_payload = CallSignalPayload(**envelope.payload)
                    async with SessionLocal() as db:
                        sender = await _get_user_by_id_or_username(db, user_id)
                        target = await _get_user_by_id_or_username(db, call_payload.target_id)
                        if not sender or not target:
                            raise ValueError("Target user not found")
                        if not await _users_can_message(db, sender, target):
                            raise ValueError("You are not allowed to call this user")
                    normalized = CallSignalPayload(
                        session_id=call_payload.session_id,
                        target_id=target.id,
                        sender_id=user_id,
                        data=call_payload.data,
                    )
                    resp = Envelope(type=envelope.type, payload=normalized.model_dump())
                    await manager.send_personal_message(resp.model_dump_json(), target.id)
                
            except Exception as e:
                logger.error("Error processing message", error=str(e))
                err_env = Envelope(
                    type=MessageType.ERROR,
                    payload=ErrorPayload(code=400, message=f"Invalid message format or processing error: {str(e)}").model_dump()
                )
                await websocket.send_text(err_env.model_dump_json())
                
    except WebSocketDisconnect:
        await manager.disconnect(user_id)
        async with SessionLocal() as db:
            res = await db.execute(select(User).where(User.id == user_id))
            user = res.scalars().first()
            if user:
                user.status = UserStatus.OFFLINE.value
                await db.commit()
