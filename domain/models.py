import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infra.db import Base


class TransferType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"


class TransferStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class RoundStatus(str, enum.Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RoundResult(str, enum.Enum):
    UP = "UP"
    DOWN = "DOWN"
    VOID = "VOID"


class BetSide(str, enum.Enum):
    UP = "UP"
    DOWN = "DOWN"


class BetStatus(str, enum.Enum):
    PLACED = "PLACED"
    LOST = "LOST"
    WON = "WON"
    REFUNDED = "REFUNDED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    wallets: Mapped[list["Wallet"]] = relationship("Wallet", back_populates="user")
    transfers: Mapped[list["Transfer"]] = relationship("Transfer", back_populates="user")
    bets: Mapped[list["Bet"]] = relationship("Bet", back_populates="user")
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship("LedgerEntry", back_populates="user")


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    chain: Mapped[str] = mapped_column(String(10), default="EVM", nullable=False)
    address: Mapped[str] = mapped_column(String(42), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship("User", back_populates="wallets")


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    type: Mapped[TransferType] = mapped_column(Enum(TransferType), nullable=False)
    amount_u: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[TransferStatus] = mapped_column(Enum(TransferStatus), default=TransferStatus.PENDING)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66))
    risk_score: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship("User", back_populates="transfers")

    __table_args__ = (
        Index("ix_transfers_user_id", user_id),
        Index("ix_transfers_status", status),
    )


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lock_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settle_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[RoundStatus] = mapped_column(Enum(RoundStatus), default=RoundStatus.OPEN)
    result: Mapped[Optional[RoundResult]] = mapped_column(Enum(RoundResult))
    commit_hash: Mapped[Optional[str]] = mapped_column(Text)
    reveal: Mapped[Optional[str]] = mapped_column(Text)

    bets: Mapped[list["Bet"]] = relationship("Bet", back_populates="round")

    __table_args__ = (
        Index("ix_rounds_status", status),
        Index("ix_rounds_code", code),
    )


class Bet(Base):
    __tablename__ = "bets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rounds.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    side: Mapped[BetSide] = mapped_column(Enum(BetSide), nullable=False)
    stake_u: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[BetStatus] = mapped_column(Enum(BetStatus), default=BetStatus.PLACED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    round: Mapped[Round] = relationship("Round", back_populates="bets")
    user: Mapped[User] = relationship("User", back_populates="bets")

    __table_args__ = (
        Index("ix_bets_round_user", round_id, user_id),
        Index("ix_bets_status", status),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    account: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    amount_u: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ref_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    user: Mapped[Optional[User]] = relationship("User", back_populates="ledger_entries")

    __table_args__ = (
        Index("ix_ledger_account_user", account, user_id),
        Index("ix_ledger_ref", ref_type, ref_id),
    )