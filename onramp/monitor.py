import asyncio
import uuid
from datetime import datetime
from typing import Optional, Dict, Union
import logging

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onramp.models import DepositIntent, DepositIntentStatus, ChainEvent, ChainType
from onramp.deposit_intents import DepositIntentService
from adapters.onchain.interfaces import OnchainGateway, DepositEvent
from domain.services import LedgerService

logger = logging.getLogger(__name__)


class ChainMonitor:
    """Monitor chain events and process deposits"""
    
    def __init__(
        self, 
        db_factory, 
        ledger_factory,
        gateways: Dict[ChainType, OnchainGateway],
        poll_interval: int = 10
    ):
        self.db_factory = db_factory
        self.ledger_factory = ledger_factory
        self.gateways = gateways
        self.poll_interval = poll_interval
        self.running = False

    async def start_monitoring(self):
        """Start monitoring all enabled chains"""
        self.running = True
        tasks = []
        
        for chain, gateway in self.gateways.items():
            task = asyncio.create_task(
                self._monitor_chain(chain, gateway),
                name=f"monitor_{chain.value}"
            )
            tasks.append(task)
        
        # Wait for all monitoring tasks
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Monitoring error: {e}")
        finally:
            self.running = False

    async def stop_monitoring(self):
        """Stop monitoring"""
        self.running = False

    async def _monitor_chain(self, chain: ChainType, gateway: OnchainGateway):
        """Monitor a specific chain for deposits"""
        logger.info(f"Starting {chain.value} deposit monitoring")
        
        while self.running:
            try:
                async with self.db_factory() as db:
                    ledger = self.ledger_factory(db)
                    intent_service = DepositIntentService(db, ledger)
                    
                    # Get last processed cursor (if any)
                    cursor = await self._get_last_cursor(db, chain)
                    
                    # Process new deposits
                    async for deposit_event in gateway.watch_deposits(cursor):
                        if not self.running:
                            break
                            
                        await self._process_deposit_event(
                            db, intent_service, deposit_event
                        )
                    
                    await db.commit()
                    
            except Exception as e:
                logger.error(f"Error monitoring {chain.value}: {e}")
                
            # Wait before next poll
            if self.running:
                await asyncio.sleep(self.poll_interval)

    async def _process_deposit_event(
        self, 
        db: AsyncSession, 
        intent_service: DepositIntentService,
        event: DepositEvent
    ):
        """Process a single deposit event"""
        try:
            # Check if we've already processed this transaction
            existing = await db.execute(
                select(ChainEvent).where(
                    and_(
                        ChainEvent.tx_sig == event.tx_sig,
                        ChainEvent.log_idx == 0  # Simplified for now
                    )
                )
            )
            
            if existing.scalar_one_or_none():
                logger.debug(f"Already processed tx {event.tx_sig}")
                return

            # Find matching deposit intent
            intent = await intent_service.get_intent(event.intent_id)
            if not intent:
                logger.warning(f"No intent found for {event.intent_id}")
                return

            # Verify the intent belongs to the user
            if intent.user_id != event.user_id:
                logger.warning(f"Intent user mismatch: {intent.user_id} vs {event.user_id}")
                return

            # Process the deposit
            credited = await intent_service.process_deposit(
                intent, event.tx_sig, event.amount_u, event.confirmations
            )

            # Record the event as processed
            chain_event = ChainEvent(
                chain=intent.chain,
                tx_sig=event.tx_sig,
                log_idx=0,  # Simplified
                raw=event.raw_data
            )
            db.add(chain_event)

            logger.info(
                f"Processed deposit: intent={event.intent_id}, "
                f"amount={event.amount_u}, credited={credited}"
            )

        except Exception as e:
            logger.error(f"Error processing deposit event: {e}")
            raise

    async def _get_last_cursor(self, db: AsyncSession, chain: ChainType) -> Optional[str]:
        """Get last processed cursor for chain"""
        # For now, return None to start from beginning
        # In production, store and retrieve the last processed block/slot
        return None

    async def _save_cursor(self, db: AsyncSession, chain: ChainType, cursor: str):
        """Save last processed cursor"""
        # TODO: Implement cursor persistence
        pass


class DepositProcessor:
    """Background service to process pending deposits"""
    
    def __init__(self, db_factory, ledger_factory, gateways: Dict[ChainType, OnchainGateway]):
        self.db_factory = db_factory
        self.ledger_factory = ledger_factory
        self.gateways = gateways

    async def process_pending_confirmations(self):
        """Check confirmation status of pending deposits"""
        async with self.db_factory() as db:
            # Get deposits waiting for confirmations
            result = await db.execute(
                select(DepositIntent).where(
                    DepositIntent.status.in_([
                        DepositIntentStatus.SEEN,
                        DepositIntentStatus.CONFIRMED
                    ]),
                    DepositIntent.tx_sig.isnot(None)
                )
            )
            pending_deposits = result.scalars().all()

            ledger = self.ledger_factory(db)
            intent_service = DepositIntentService(db, ledger)

            for intent in pending_deposits:
                gateway = self.gateways.get(intent.chain)
                if not gateway:
                    continue

                try:
                    confirmations = await gateway.get_confirmations(intent.tx_sig)
                    
                    # Mock deposit event for processing
                    deposit_event = DepositEvent(
                        user_id=intent.user_id,
                        intent_id=intent.id,
                        tx_sig=intent.tx_sig,
                        amount_u=intent.expected_min_u,  # TODO: get actual amount from tx
                        confirmations=confirmations,
                        raw_data={}
                    )
                    
                    await intent_service.process_deposit(
                        intent, intent.tx_sig, intent.expected_min_u, confirmations
                    )
                    
                except Exception as e:
                    logger.error(f"Error checking confirmations for intent {intent.id}: {e}")

            await db.commit()