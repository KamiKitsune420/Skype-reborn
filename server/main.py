import asyncio
import json
import os
import aiofiles
from contextlib import asynccontextmanager
from typing import List, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from .database import get_db, init_db, User, Message as DBMessage, Contact, SessionLocal
from .auth import get_password_hash, verify_password, create_access_token, get_current_user
from .voice_relay import start_voice_relay
from .manager import manager
from .config import settings
from shared.models import (
    Envelope, MessageType, LoginPayload, AuthSuccessPayload, 
    ChatMessagePayload, ContactAddPayload, CallSignalPayload,
    PresenceUpdatePayload, UserStatus, ProfileUpdatePayload, ChatTypingPayload,
    RegisterPayload, ErrorPayload
)
import structlog

logger = structlog.get_logger()

async def start_bots():
    bot_dir = "server/bots"
    if not os.path.exists(bot_dir):
        return []
    
    bots = [f for f in os.listdir(bot_dir) if f.endswith("_bot.py")]
    processes = []
    for bot in bots:
        bot_path = os.path.join(bot_dir, bot)
        logger.info(f"Starting bot: {bot}")
        # Run as a separate process
        proc = await asyncio.create_subprocess_exec(
            "python", bot_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        processes.append(proc)
    return processes

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
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

# --- Auth Routes ---

@app.post("/register")
async def register(payload: RegisterPayload, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(or_(User.username == payload.username, User.email == payload.email)))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Username or Email already registered")
    
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
    stmt = select(User).join(Contact, Contact.contact_user_id == User.id).where(Contact.user_id == current_user.id)
    result = await db.execute(stmt)
    contacts = result.scalars().all()
    return [{"id": c.id, "username": c.username, "display_name": c.display_name, "status": c.status} for c in contacts]

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
    # In a real app, we should check if current_user is part of conversation_id
    stmt = select(DBMessage).where(DBMessage.conversation_id == conversation_id).order_by(DBMessage.timestamp.asc())
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return messages

@app.get("/users/search")
async def search_users(query: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(or_(User.username.ilike(f"%{query}%"), User.display_name.ilike(f"%{query}%"))).limit(20)
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "status": u.status} for u in users]

@app.post("/profile/update")
async def update_profile(payload: ProfileUpdatePayload, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if payload.display_name:
        current_user.display_name = payload.display_name
    
    await db.commit()
    return {"message": "Profile updated"}

# --- File Transfer ---

@app.post("/upload/{recipient_id}")
async def upload_file(recipient_id: str, filename: str, file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    file_id = str(uuid4())
    file_path = os.path.join(settings.UPLOAD_DIR, file_id)
    
    content = await file.read()
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
                        db_msg = DBMessage(
                            conversation_id=chat_payload.conversation_id,
                            sender_id=user_id,
                            content=chat_payload.content
                        )
                        db.add(db_msg)
                        await db.commit()
                    
                    resp = Envelope(type=MessageType.CHAT_RECEIVE, payload=chat_payload.model_dump())
                    if chat_payload.conversation_id == "echo_service":
                        await manager.send_personal_message(resp.model_dump_json(), user_id)
                    else:
                        await manager.send_personal_message(resp.model_dump_json(), chat_payload.conversation_id)

                elif envelope.type == MessageType.PRESENCE_UPDATE:
                    presence_payload = PresenceUpdatePayload(**envelope.payload)
                    async with SessionLocal() as db:
                        res = await db.execute(select(User).where(User.id == user_id))
                        user = res.scalars().first()
                        if user:
                            user.status = presence_payload.status.value
                            await db.commit()
                            await manager.broadcast_presence(user_id, presence_payload.status)

                elif envelope.type in [MessageType.CALL_INITIATE, MessageType.CALL_ACCEPT, 
                                     MessageType.CALL_REJECT, MessageType.CALL_HANGUP,
                                     MessageType.CALL_RINGING, MessageType.CALL_CANDIDATE,
                                     MessageType.CALL_CONNECTING]:
                    call_payload = CallSignalPayload(**envelope.payload)
                    await manager.send_personal_message(data, call_payload.target_id)
                
            except Exception as e:
                logger.error("Error processing message", error=str(e))
                err_env = Envelope(
                    type=MessageType.ERROR,
                    payload=ErrorPayload(code=400, message=f"Invalid message format or processing error: {str(e)}").model_dump()
                )
                await websocket.send_text(err_env.model_dump_json())
                
    except WebSocketDisconnect:
        await manager.disconnect(user_id)
