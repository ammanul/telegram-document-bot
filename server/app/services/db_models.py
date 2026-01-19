from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.app.services.db import Base, engine


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True, index=True)
    role = Column(String(32), nullable=False, default="user")
    processed_documents_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    jobs = relationship("Job", back_populates="user", lazy="selectin")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    telegram_user_id = Column(BigInteger, index=True, nullable=True)
    chat_id = Column(BigInteger, index=True, nullable=True)

    status = Column(String(32), nullable=False, default="queued")
    id_type = Column(String(64), nullable=True)
    output_format = Column(String(16), nullable=True)
    grayscale = Column(Boolean, nullable=True)
    mirror = Column(Boolean, nullable=True)
    brightness = Column(Float, nullable=True)
    saturation = Column(Float, nullable=True)

    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="jobs", lazy="joined")
    files = relationship("JobFile", back_populates="job", lazy="selectin", cascade="all, delete-orphan")


class JobFile(Base):
    __tablename__ = "job_files"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_file_id = Column(Text, nullable=False)
    file_name = Column(Text, nullable=True)
    index_in_job = Column(Integer, nullable=False, default=0)

    processed_successfully = Column(Boolean, nullable=True)
    error_message = Column(Text, nullable=True)

    job = relationship("Job", back_populates="files", lazy="joined")


class PendingRequest(Base):
    """Access request initiated by a Telegram user."""

    __tablename__ = "pending_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PendingGrant(Base):
    """Grant that awaits the target user to start the bot."""

    __tablename__ = "pending_grants"

    username = Column(String(255), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PendingOwnershipTransfer(Base):
    """Ownership transfer invitation awaiting confirmation by target username."""

    __tablename__ = "pending_ownership_transfers"

    username = Column(String(255), primary_key=True)
    from_user_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


def init_db() -> None:
    """Create all tables in the configured Postgres database.

    This is safe to call multiple times.
    """
    Base.metadata.create_all(bind=engine)

    # Drop the old unique constraint on (job_id, telegram_file_id) if it
    # exists so that the same Telegram file can appear multiple times in a
    # single job.
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE job_files DROP CONSTRAINT IF EXISTS uq_jobfile_job_file"))
            conn.commit()
        except Exception:
            # If this fails, we don't want to block app startup; any real
            # issues will surface via normal DB errors.
            pass
