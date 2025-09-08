import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from domain.models import BetSide, BetStatus, RoundResult, RoundStatus, TransferStatus, TransferType


class UserCreate(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class WalletCreate(BaseModel):
    user_id: uuid.UUID


class WalletResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    chain: str
    address: str
    created_at: datetime

    class Config:
        from_attributes = True


class BetCreate(BaseModel):
    user_id: uuid.UUID
    side: BetSide
    stake_u: int = Field(gt=0, description="Stake in micro USDC (10^-6)")


class BetResponse(BaseModel):
    id: uuid.UUID
    round_id: uuid.UUID
    user_id: uuid.UUID
    side: BetSide
    stake_u: int
    status: BetStatus
    created_at: datetime

    class Config:
        from_attributes = True


class WithdrawalCreate(BaseModel):
    user_id: uuid.UUID
    amount_u: int = Field(gt=0, description="Amount in micro USDC (10^-6)")
    address: Optional[str] = Field(None, description="Withdrawal address (optional)")


class TransferResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: TransferType
    amount_u: int
    status: TransferStatus
    tx_hash: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DepositWebhook(BaseModel):
    user_id: uuid.UUID
    amount_u: int = Field(gt=0, description="Amount in micro USDC (10^-6)")


class RoundSummary(BaseModel):
    id: uuid.UUID
    code: str
    status: RoundStatus
    result: Optional[RoundResult]
    up_pool_u: int
    down_pool_u: int
    lock_ts: datetime

    class Config:
        from_attributes = True


class TvlResponse(BaseModel):
    locked_u: int = Field(description="Total locked funds in micro USDC")
    total_cash_u: int = Field(description="Total cash across all users in micro USDC")
    pending_withdrawals_u: int = Field(description="Total pending withdrawals in micro USDC")