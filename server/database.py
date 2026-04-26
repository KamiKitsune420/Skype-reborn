from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, ForeignKey, Text, Integer
from datetime import datetime
from uuid import uuid4
from .config import settings

engine = create_async_engine(settings.DATABASE_URL)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    first_name: Mapped[str] = mapped_column(String)
    last_name: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="OFFLINE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = "messages"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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

async def get_db():
    async with SessionLocal() as session:
        yield session
