import hashlib
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.chain import ChainGateway, MockChainGateway
from adapters.oracle import MockOracle, PriceOracle
from api.schemas import (
    BetCreate,
    BetResponse,
    DepositWebhook,
    RoundSummary,
    TransferResponse,
    TvlResponse,
    UserCreate,
    UserResponse,
    WalletCreate,
    WalletResponse,
    WithdrawalCreate,
)
from domain.models import (
    Round,
    RoundStatus,
    Transfer,
    TransferStatus,
    TransferType,
    User,
    Wallet,
)
from domain.services import BettingService, LedgerService, TvlService
from infra.db import get_async_db

router = APIRouter()

# Dependency injection - in production these would be configured properly
def get_chain_gateway() -> ChainGateway:
    return MockChainGateway()

def get_price_oracle() -> PriceOracle:
    return MockOracle()


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_async_db)
):
    """Create a new user"""
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    user = User(email=user_data.email)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    return user


@router.post("/wallets", response_model=WalletResponse)
async def create_wallet(
    wallet_data: WalletCreate,
    db: AsyncSession = Depends(get_async_db)
):
    """Create a wallet for a user with deterministic mock address"""
    # Verify user exists
    user = await db.get(User, wallet_data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Generate deterministic address based on user_id
    address_hash = hashlib.sha256(f"{wallet_data.user_id}".encode()).hexdigest()[:40]
    address = f"0x{address_hash}"

    wallet = Wallet(
        user_id=wallet_data.user_id,
        chain="EVM",
        address=address
    )
    db.add(wallet)
    await db.commit()
    await db.refresh(wallet)
    
    return wallet


@router.get("/tvl", response_model=TvlResponse)
async def get_tvl(db: AsyncSession = Depends(get_async_db)):
    """Get Total Value Locked and other metrics"""
    ledger_service = LedgerService(db)
    tvl_service = TvlService(db, ledger_service)
    
    tvl_data = await tvl_service.get_tvl()
    return TvlResponse(**tvl_data)


@router.get("/rounds/current", response_model=Optional[RoundSummary])
async def get_current_round(db: AsyncSession = Depends(get_async_db)):
    """Get the current active round"""
    # Get the most recent open or locked round
    result = await db.execute(
        select(Round)
        .where(Round.status.in_([RoundStatus.OPEN, RoundStatus.LOCKED]))
        .order_by(Round.start_ts.desc())
        .limit(1)
    )
    round_obj = result.scalar_one_or_none()
    
    if not round_obj:
        return None

    # Get pool totals
    betting_service = BettingService(db, LedgerService(db))
    up_pool, down_pool = await betting_service.get_round_pools(round_obj.id)
    
    return RoundSummary(
        id=round_obj.id,
        code=round_obj.code,
        status=round_obj.status,
        result=round_obj.result,
        up_pool_u=up_pool,
        down_pool_u=down_pool,
        lock_ts=round_obj.lock_ts
    )


@router.post("/bets", response_model=BetResponse)
async def place_bet(
    bet_data: BetCreate,
    db: AsyncSession = Depends(get_async_db)
):
    """Place a bet on the current round"""
    # Get current open round
    result = await db.execute(
        select(Round)
        .where(Round.status == RoundStatus.OPEN)
        .order_by(Round.start_ts.desc())
        .limit(1)
    )
    round_obj = result.scalar_one_or_none()
    
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No open round available"
        )

    # Verify user exists
    user = await db.get(User, bet_data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Place bet
    ledger_service = LedgerService(db)
    betting_service = BettingService(db, ledger_service)
    
    try:
        bet = await betting_service.place_bet(
            bet_data.user_id,
            round_obj.id,
            bet_data.side,
            bet_data.stake_u
        )
        await db.commit()
        await db.refresh(bet)
        return bet
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/withdrawals", response_model=TransferResponse)
async def create_withdrawal(
    withdrawal_data: WithdrawalCreate,
    db: AsyncSession = Depends(get_async_db),
    chain_gateway: ChainGateway = Depends(get_chain_gateway)
):
    """Create a withdrawal request"""
    # Verify user exists
    user = await db.get(User, withdrawal_data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check user balance
    ledger_service = LedgerService(db)
    balance = await ledger_service.get_balance(withdrawal_data.user_id, "cash")
    
    if balance < withdrawal_data.amount_u:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance: {balance} < {withdrawal_data.amount_u}"
        )

    # Use user's first wallet address if no address provided
    address = withdrawal_data.address
    if not address:
        wallet_result = await db.execute(
            select(Wallet).where(Wallet.user_id == withdrawal_data.user_id).limit(1)
        )
        wallet = wallet_result.scalar_one_or_none()
        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No wallet found and no address provided"
            )
        address = wallet.address

    try:
        # Create withdrawal transaction via chain gateway
        tx_hash = await chain_gateway.create_withdrawal(address, withdrawal_data.amount_u)
        
        # Create transfer record
        transfer = Transfer(
            user_id=withdrawal_data.user_id,
            type=TransferType.WITHDRAWAL,
            amount_u=withdrawal_data.amount_u,
            status=TransferStatus.PENDING,
            tx_hash=tx_hash
        )
        db.add(transfer)
        
        # Deduct from user's cash balance
        ledger_service.create_entries([
            ("cash", withdrawal_data.user_id, -withdrawal_data.amount_u, "withdrawal", transfer.id),
        ])
        
        await db.commit()
        await db.refresh(transfer)
        return transfer
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Withdrawal failed: {str(e)}"
        )


@router.post("/simulate/deposit_webhook", response_model=TransferResponse)
async def simulate_deposit(
    deposit_data: DepositWebhook,
    db: AsyncSession = Depends(get_async_db)
):
    """Simulate a confirmed deposit (testing only)"""
    # Verify user exists
    user = await db.get(User, deposit_data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Create deposit transfer
    tx_hash = f"0x{uuid.uuid4().hex[:64]}"
    transfer = Transfer(
        user_id=deposit_data.user_id,
        type=TransferType.DEPOSIT,
        amount_u=deposit_data.amount_u,
        status=TransferStatus.CONFIRMED,
        tx_hash=tx_hash
    )
    db.add(transfer)
    await db.flush()

    # Add to user's cash balance
    ledger_service = LedgerService(db)
    ledger_service.create_entries([
        ("cash", deposit_data.user_id, deposit_data.amount_u, "deposit", transfer.id),
    ])

    await db.commit()
    await db.refresh(transfer)
    return transfer