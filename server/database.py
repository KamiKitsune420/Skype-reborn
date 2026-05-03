from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, ForeignKey, Text, Integer, UniqueConstraint, text
from typing import Optional
from datetime import datetime
from uuid import uuid4
from .config import settings

engine = create_async_engine(settings.DATABASE_URL)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id:            Mapped[str]           = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    username:      Mapped[str]           = mapped_column(String, unique=True, index=True)
    email:         Mapped[str]           = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str]           = mapped_column(String)
    first_name:    Mapped[str]           = mapped_column(String)
    last_name:     Mapped[str]           = mapped_column(String)
    display_name:  Mapped[str]           = mapped_column(String)
    status:        Mapped[str]           = mapped_column(String, default="OFFLINE")
    created_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    # Extended profile fields (added post-launch — migrated via init_db)
    mood_message:  Mapped[Optional[str]] = mapped_column(String, nullable=True, default="")
    country:       Mapped[Optional[str]] = mapped_column(String, nullable=True, default="")
    hometown:      Mapped[Optional[str]] = mapped_column(String, nullable=True, default="")
    birthday:      Mapped[Optional[str]] = mapped_column(String, nullable=True, default="")
    avatar_path:   Mapped[Optional[str]] = mapped_column(String, nullable=True, default="")

class Message(Base):
    __tablename__ = "messages"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    recipient_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String, default="text")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    read_at:      Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    type: Mapped[str] = mapped_column(String, default="direct")
    direct_key: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_conversation_user"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, ForeignKey("conversations.id"), index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Contact(Base):
    __tablename__ = "contacts"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    contact_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String, default="ACCEPTED") # PENDING, ACCEPTED, BLOCKED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class FileTransfer(Base):
    __tablename__ = "file_transfers"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    recipient_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String)
    file_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="PENDING") # PENDING, COMPLETED, FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Non-destructive migration: add new columns to existing databases.
        for col, sql_type in [
            ("mood_message", "TEXT DEFAULT ''"),
            ("country",      "TEXT DEFAULT ''"),
            ("hometown",     "TEXT DEFAULT ''"),
            ("birthday",     "TEXT DEFAULT ''"),
            ("avatar_path",  "TEXT DEFAULT ''"),
        ]:
            try:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {sql_type}"))
            except Exception:
                pass  # column already exists

        for col, sql_type in [
            ("recipient_id",  "TEXT"),
            ("message_type",  "TEXT DEFAULT 'text'"),
            ("delivered_at",  "DATETIME"),
            ("read_at",       "DATETIME"),
        ]:
            try:
                await conn.execute(text(f"ALTER TABLE messages ADD COLUMN {col} {sql_type}"))
            except Exception:
                pass  # column already exists

async def get_db():
    async with SessionLocal() as session:
        yield session
