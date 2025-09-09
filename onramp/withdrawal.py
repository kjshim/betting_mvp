import uuid
from datetime import datetime
from typing import Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onramp.models import WithdrawalRequest, ChainType
from adapters.onchain.interfaces import OnchainGateway
from domain.services import LedgerService


class WithdrawalService:
    def __init__(self, db: Union[Session, AsyncSession], ledger: LedgerService):
        self.db = db
        self.ledger = ledger

    async def create_withdrawal(
        self,
        user_id: uuid.UUID,
        chain: ChainType,
        destination: str,
        amount_u: int,
        gateway: OnchainGateway
    ) -> WithdrawalRequest:
        """Create withdrawal request"""
        # Check user has sufficient balance
        if isinstance(self.db, AsyncSession):
            balance = await self.ledger.get_balance_async(user_id, "cash")
        else:
            balance = self.ledger.get_balance(user_id, "cash")

        if balance < amount_u:
            raise ValueError(f"Insufficient balance: {balance} < {amount_u}")

        # Validate destination address
        if not await gateway.is_valid_address(destination):
            raise ValueError(f"Invalid destination address: {destination}")

        # Create withdrawal request
        withdrawal = WithdrawalRequest(
            user_id=user_id,
            chain=chain,
            destination=destination,
            requested_u=amount_u,
            min_confirmations=gateway.min_confirmations,
            status="PENDING"
        )
        self.db.add(withdrawal)

        if isinstance(self.db, AsyncSession):
            await self.db.flush()
        else:
            self.db.flush()

        # Lock funds in ledger
        self.ledger.create_entries([
            ("cash", user_id, -amount_u, "withdrawal", withdrawal.id),
            ("pending_withdrawals", user_id, amount_u, "withdrawal", withdrawal.id),
        ])

        return withdrawal

    async def process_withdrawal(
        self,
        withdrawal_id: uuid.UUID,
        gateway: OnchainGateway
    ) -> bool:
        """Process pending withdrawal by broadcasting to chain"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(WithdrawalRequest).where(
                    WithdrawalRequest.id == withdrawal_id,
                    WithdrawalRequest.status == "PENDING"
                )
            )
            withdrawal = result.scalar_one_or_none()
        else:
            withdrawal = self.db.execute(
                select(WithdrawalRequest).where(
                    WithdrawalRequest.id == withdrawal_id,
                    WithdrawalRequest.status == "PENDING"
                )
            ).scalar_one_or_none()

        if not withdrawal:
            return False

        # Check admin approval for high-risk withdrawals
        if not withdrawal.admin_approved:
            return False

        try:
            # Broadcast transaction
            result = await gateway.send_usdc(
                withdrawal.destination,
                withdrawal.requested_u
            )

            if result.success:
                withdrawal.status = "BROADCAST"
                withdrawal.broadcast_tx = result.tx_sig
                withdrawal.updated_at = datetime.utcnow()
                return True
            else:
                # Failed to broadcast - unlock funds
                withdrawal.status = "FAILED"
                withdrawal.updated_at = datetime.utcnow()
                
                # Return funds to cash
                self.ledger.create_entries([
                    ("pending_withdrawals", withdrawal.user_id, -withdrawal.requested_u, "withdrawal_failed", withdrawal.id),
                    ("cash", withdrawal.user_id, withdrawal.requested_u, "withdrawal_failed", withdrawal.id),
                ])
                return False

        except Exception as e:
            withdrawal.status = "FAILED"
            withdrawal.updated_at = datetime.utcnow()
            
            # Return funds to cash
            self.ledger.create_entries([
                ("pending_withdrawals", withdrawal.user_id, -withdrawal.requested_u, "withdrawal_failed", withdrawal.id),
                ("cash", withdrawal.user_id, withdrawal.requested_u, "withdrawal_failed", withdrawal.id),
            ])
            return False

    async def check_withdrawal_confirmations(
        self,
        withdrawal_id: uuid.UUID,
        gateway: OnchainGateway
    ) -> bool:
        """Check if withdrawal has enough confirmations"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(WithdrawalRequest).where(
                    WithdrawalRequest.id == withdrawal_id,
                    WithdrawalRequest.status == "BROADCAST"
                )
            )
            withdrawal = result.scalar_one_or_none()
        else:
            withdrawal = self.db.execute(
                select(WithdrawalRequest).where(
                    WithdrawalRequest.id == withdrawal_id,
                    WithdrawalRequest.status == "BROADCAST"
                )
            ).scalar_one_or_none()

        if not withdrawal or not withdrawal.broadcast_tx:
            return False

        try:
            confirmations = await gateway.get_confirmations(withdrawal.broadcast_tx)
            withdrawal.confirmations = confirmations

            if confirmations >= withdrawal.min_confirmations:
                withdrawal.status = "CONFIRMED"
                withdrawal.updated_at = datetime.utcnow()

                # Complete withdrawal - remove from pending
                self.ledger.create_entries([
                    ("pending_withdrawals", withdrawal.user_id, -withdrawal.requested_u, "withdrawal_confirmed", withdrawal.id),
                    ("house", None, withdrawal.requested_u, "withdrawal_confirmed", withdrawal.id),
                ])
                return True

        except Exception:
            pass

        return False

    async def get_user_withdrawals(
        self,
        user_id: uuid.UUID,
        status: Optional[str] = None
    ) -> list[WithdrawalRequest]:
        """Get user's withdrawal requests"""
        query = select(WithdrawalRequest).where(WithdrawalRequest.user_id == user_id)
        
        if status:
            query = query.where(WithdrawalRequest.status == status)
            
        query = query.order_by(WithdrawalRequest.created_at.desc())

        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(query)
            return result.scalars().all()
        else:
            return self.db.execute(query).scalars().all()

    async def get_pending_withdrawals(self) -> list[WithdrawalRequest]:
        """Get all pending withdrawals for processing"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(WithdrawalRequest).where(
                    WithdrawalRequest.status.in_(["PENDING", "BROADCAST"])
                ).order_by(WithdrawalRequest.created_at)
            )
            return result.scalars().all()
        else:
            return self.db.execute(
                select(WithdrawalRequest).where(
                    WithdrawalRequest.status.in_(["PENDING", "BROADCAST"])
                ).order_by(WithdrawalRequest.created_at)
            ).scalars().all()