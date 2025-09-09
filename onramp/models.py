import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, BigInteger, Integer, Text, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from domain.models import Base


class ChainType(str, enum.Enum):
    SOL = "SOL"


class DepositIntentStatus(str, enum.Enum):
    ISSUED = "ISSUED"
    SEEN = "SEEN"
    CONFIRMED = "CONFIRMED"
    CREDITED = "CREDITED"
    EXPIRED = "EXPIRED"


class DepositIntent(Base):
    __tablename__ = "deposit_intents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[ChainType] = mapped_column(String(3), nullable=False)
    token_mint: Mapped[str] = mapped_column(Text, nullable=False)  # USDC mint/contract address
    status: Mapped[DepositIntentStatus] = mapped_column(String(20), default=DepositIntentStatus.ISSUED, nullable=False)
    expected_min_u: Mapped[int] = mapped_column(BigInteger, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    memo_tag: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Solana memo/reference
    tx_sig: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    credited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_deposit_intents_address_chain", address, chain, unique=True),
        Index("ix_deposit_intents_user_status", user_id, status),
        Index("ix_deposit_intents_chain_status", chain, status),
    )


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chain: Mapped[ChainType] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    requested_u: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # PENDING, BROADCAST, CONFIRMED, FAILED
    broadcast_tx: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_confirmations: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    admin_approved: Mapped[bool] = mapped_column(default=True, nullable=False)  # For KYT integration
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_withdrawal_requests_user_status", user_id, status),
        Index("ix_withdrawal_requests_chain_status", chain, status),
    )


class ChainEvent(Base):
    __tablename__ = "chain_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chain: Mapped[ChainType] = mapped_column(String(3), nullable=False)
    tx_sig: Mapped[str] = mapped_column(Text, nullable=False)
    log_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_chain_events_tx_log", tx_sig, log_idx, unique=True),
        Index("ix_chain_events_chain", chain),
    )