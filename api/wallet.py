from typing import Optional, Dict, Any
import uuid

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_user
from domain.models import User
from domain.services import LedgerService
from onramp.models import ChainType, DepositIntent, WithdrawalRequest
from onramp.deposit_intents import DepositIntentService
from onramp.withdrawal import WithdrawalService
from onramp.qr import QRService
from adapters.onchain.interfaces import OnchainGateway
from adapters.onchain.solana_simple import SolanaUSDCAdapterSimple
from infra.db import get_async_db
from infra.settings import settings

router = APIRouter(prefix="/wallet", tags=["Wallet"])


class BalanceResponse(BaseModel):
    cash_u: int
    locked_u: int
    pending_withdrawals_u: int


class DepositIntentRequest(BaseModel):
    min_amount_u: int = 1


class DepositIntentResponse(BaseModel):
    intent_id: str
    address: str
    payment_uri: str
    qr_code: str
    status: str
    expected_min_u: int


class WithdrawRequest(BaseModel):
    destination: str
    amount_u: int


class WithdrawResponse(BaseModel):
    withdrawal_id: str
    status: str
    destination: str
    amount_u: int


def get_gateway() -> OnchainGateway:
    """Get Solana gateway instance"""
    return SolanaUSDCAdapterSimple(
        rpc_url=settings.solana_rpc_url,
        usdc_mint=settings.solana_usdc_mint,
        min_confirmations=settings.solana_min_conf
    )


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Get user wallet balance"""
    ledger = LedgerService(db)
    
    cash_u = await ledger.get_balance_async(current_user.id, "cash")
    locked_u = await ledger.get_balance_async(current_user.id, "locked")
    pending_withdrawals_u = await ledger.get_balance_async(current_user.id, "pending_withdrawals")
    
    return BalanceResponse(
        cash_u=cash_u,
        locked_u=locked_u,
        pending_withdrawals_u=pending_withdrawals_u
    )


@router.post("/deposit-intents", response_model=DepositIntentResponse)
async def create_deposit_intent(
    request: DepositIntentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Create Solana deposit intent with address and QR code"""
    ledger = LedgerService(db)
    intent_service = DepositIntentService(db, ledger)
    gateway = get_gateway()
    
    try:
        # Create deposit intent
        intent = await intent_service.create_intent(
            user_id=current_user.id,
            chain=ChainType.SOL,
            gateway=gateway,
            min_amount_u=request.min_amount_u
        )
        await db.commit()
        
        # Build payment URI
        payment_uri = await gateway.build_payment_uri(
            address=intent.address,
            amount_u=request.min_amount_u,
            intent_id=intent.id
        )
        
        # Generate QR code
        qr_code = QRService.generate_qr_code(payment_uri)
        
        return DepositIntentResponse(
            intent_id=str(intent.id),
            address=intent.address,
            payment_uri=payment_uri,
            qr_code=qr_code,
            status=intent.status.value,
            expected_min_u=intent.expected_min_u
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create deposit intent: {str(e)}"
        )


@router.get("/deposit-intents/{intent_id}")
async def get_deposit_intent(
    intent_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Get deposit intent status"""
    ledger = LedgerService(db)
    intent_service = DepositIntentService(db, ledger)
    
    try:
        intent = await intent_service.get_intent(uuid.UUID(intent_id))
        if not intent or intent.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deposit intent not found"
            )
        
        return {
            "intent_id": str(intent.id),
            "status": intent.status.value,
            "address": intent.address,
            "expected_min_u": intent.expected_min_u,
            "tx_sig": intent.tx_sig,
            "created_at": intent.created_at,
            "seen_at": intent.seen_at,
            "confirmed_at": intent.confirmed_at,
            "credited_at": intent.credited_at
        }
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid intent ID"
        )


@router.post("/withdraw", response_model=WithdrawResponse)
async def withdraw(
    request: WithdrawRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Create Solana withdrawal request"""
    ledger = LedgerService(db)
    withdrawal_service = WithdrawalService(db, ledger)
    gateway = get_gateway()
    
    try:
        withdrawal = await withdrawal_service.create_withdrawal(
            user_id=current_user.id,
            chain=ChainType.SOL,
            destination=request.destination,
            amount_u=request.amount_u,
            gateway=gateway
        )
        await db.commit()
        
        return WithdrawResponse(
            withdrawal_id=str(withdrawal.id),
            status=withdrawal.status,
            destination=withdrawal.destination,
            amount_u=withdrawal.requested_u
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/withdrawals/{withdrawal_id}")
async def get_withdrawal_status(
    withdrawal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Get withdrawal status"""
    ledger = LedgerService(db)
    withdrawal_service = WithdrawalService(db, ledger)
    
    try:
        withdrawals = await withdrawal_service.get_user_withdrawals(current_user.id)
        withdrawal = next((w for w in withdrawals if str(w.id) == withdrawal_id), None)
        
        if not withdrawal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Withdrawal not found"
            )
        
        return {
            "withdrawal_id": str(withdrawal.id),
            "status": withdrawal.status,
            "destination": withdrawal.destination,
            "requested_u": withdrawal.requested_u,
            "broadcast_tx": withdrawal.broadcast_tx,
            "confirmations": withdrawal.confirmations,
            "min_confirmations": withdrawal.min_confirmations,
            "created_at": withdrawal.created_at,
            "updated_at": withdrawal.updated_at
        }
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid withdrawal ID"
        )


@router.get("/withdrawals")
async def get_user_withdrawals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Get user's withdrawal history"""
    ledger = LedgerService(db)
    withdrawal_service = WithdrawalService(db, ledger)
    
    withdrawals = await withdrawal_service.get_user_withdrawals(current_user.id)
    
    return [
        {
            "withdrawal_id": str(w.id),
            "status": w.status,
            "chain": w.chain.value,
            "destination": w.destination,
            "requested_u": w.requested_u,
            "broadcast_tx": w.broadcast_tx,
            "confirmations": w.confirmations,
            "created_at": w.created_at
        }
        for w in withdrawals
    ]


@router.get("/deposit-intents")
async def get_user_deposit_intents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Get user's deposit intent history"""
    ledger = LedgerService(db)
    intent_service = DepositIntentService(db, ledger)
    
    intents = await intent_service.get_user_intents(current_user.id)
    
    return [
        {
            "intent_id": str(intent.id),
            "status": intent.status.value,
            "chain": intent.chain.value,
            "address": intent.address,
            "expected_min_u": intent.expected_min_u,
            "tx_sig": intent.tx_sig,
            "created_at": intent.created_at,
            "credited_at": intent.credited_at
        }
        for intent in intents
    ]