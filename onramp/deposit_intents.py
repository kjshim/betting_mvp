import uuid
from datetime import datetime
from typing import Optional, Union, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onramp.models import DepositIntent, DepositIntentStatus, ChainType
from adapters.onchain.interfaces import OnchainGateway
from domain.services import LedgerService


class DepositIntentService:
    def __init__(self, db: Union[Session, AsyncSession], ledger: LedgerService):
        self.db = db
        self.ledger = ledger

    async def create_intent(
        self, 
        user_id: uuid.UUID, 
        chain: ChainType, 
        gateway: OnchainGateway, 
        min_amount_u: int = 1
    ) -> DepositIntent:
        """Create a new deposit intent"""
        # First create a temporary intent to get an ID
        temp_intent_id = uuid.uuid4()
        
        # Generate unique address
        address = await gateway.generate_address(user_id, temp_intent_id)
        
        # Now create the intent with the address
        intent = DepositIntent(
            id=temp_intent_id,
            user_id=user_id,
            chain=chain,
            token_mint=gateway.usdc_mint,
            expected_min_u=min_amount_u,
            address=address
        )
        
        # For Solana, generate memo tag (reference)
        if chain == ChainType.SOL:
            intent.memo_tag = str(intent.id).replace("-", "")
        
        self.db.add(intent)
        
        # Flush to ensure it's persisted
        if isinstance(self.db, AsyncSession):
            await self.db.flush()
        else:
            self.db.flush()

        return intent

    def create_intent_sync(
        self, 
        user_id: uuid.UUID, 
        chain: ChainType, 
        gateway: OnchainGateway, 
        min_amount_u: int = 1
    ) -> DepositIntent:
        """Create a new deposit intent (sync version)"""
        import asyncio
        
        # First create a temporary intent to get an ID
        temp_intent_id = uuid.uuid4()
        
        # Generate unique address (run async in event loop)
        try:
            address = asyncio.run(gateway.generate_address(user_id, temp_intent_id))
            print(f"Generated address: {address}")  # Debug
        except Exception as e:
            print(f"Error generating address: {e}")  # Debug
            raise
        
        # Now create the intent with the address
        intent = DepositIntent(
            id=temp_intent_id,
            user_id=user_id,
            chain=chain,
            token_mint=gateway.usdc_mint,
            expected_min_u=min_amount_u,
            address=address
        )
        
        # For Solana, generate memo tag (reference)
        if chain == ChainType.SOL:
            intent.memo_tag = str(intent.id).replace("-", "")
        
        self.db.add(intent)
        
        # Flush to ensure it's persisted
        if isinstance(self.db, AsyncSession):
            # This shouldn't happen in sync version
            raise ValueError("Sync method called with async session")
        else:
            self.db.flush()
            
        return intent

    async def get_intent(self, intent_id: uuid.UUID) -> Optional[DepositIntent]:
        """Get deposit intent by ID"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(DepositIntent).where(DepositIntent.id == intent_id)
            )
            return result.scalar_one_or_none()
        else:
            return self.db.get(DepositIntent, intent_id)

    async def get_user_intents(
        self, 
        user_id: uuid.UUID, 
        status: Optional[DepositIntentStatus] = None
    ) -> list[DepositIntent]:
        """Get all deposit intents for a user"""
        query = select(DepositIntent).where(DepositIntent.user_id == user_id)
        
        if status:
            query = query.where(DepositIntent.status == status)
            
        query = query.order_by(DepositIntent.created_at.desc())

        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(query)
            return result.scalars().all()
        else:
            return self.db.execute(query).scalars().all()

    async def process_deposit(
        self, 
        intent: DepositIntent, 
        tx_sig: str, 
        amount_u: int, 
        confirmations: int
    ) -> bool:
        """Process a detected deposit"""
        # Update intent with transaction details
        if intent.status == DepositIntentStatus.ISSUED:
            intent.status = DepositIntentStatus.SEEN
            intent.tx_sig = tx_sig
            intent.seen_at = datetime.utcnow()

        # Check if we have enough confirmations
        if confirmations >= confirmations and intent.status in [DepositIntentStatus.SEEN]:
            intent.status = DepositIntentStatus.CONFIRMED
            intent.confirmed_at = datetime.utcnow()

        # Credit to user account if confirmed and not already credited
        if intent.status == DepositIntentStatus.CONFIRMED and not intent.credited_at:
            # Validate minimum amount
            if amount_u < intent.expected_min_u:
                # Could reject or accept with warning
                pass

            # Credit user account via ledger
            self.ledger.create_entries([
                ("cash", intent.user_id, amount_u, "deposit_intent", intent.id),
                ("house", None, -amount_u, "deposit_intent", intent.id),
            ])

            intent.status = DepositIntentStatus.CREDITED
            intent.credited_at = datetime.utcnow()
            return True

        return False

    async def expire_old_intents(self, hours: int = 24):
        """Mark old intents as expired"""
        from datetime import datetime, timedelta
        
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(DepositIntent).where(
                    DepositIntent.status == DepositIntentStatus.ISSUED,
                    DepositIntent.created_at < cutoff
                )
            )
            old_intents = result.scalars().all()
        else:
            old_intents = self.db.execute(
                select(DepositIntent).where(
                    DepositIntent.status == DepositIntentStatus.ISSUED,
                    DepositIntent.created_at < cutoff
                )
            ).scalars().all()

        for intent in old_intents:
            intent.status = DepositIntentStatus.EXPIRED