import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Dict, List

from pydantic import BaseModel


class DepositEvent(BaseModel):
    user_id: uuid.UUID
    amount_u: int
    tx_hash: str
    confirmations: int


class ChainGateway(ABC):
    @abstractmethod
    async def watch_deposits(self) -> AsyncIterator[DepositEvent]:
        """Watch for deposit events"""
        pass

    @abstractmethod
    async def create_withdrawal(self, address: str, amount_u: int) -> str:
        """Create a withdrawal transaction, returns tx_hash"""
        pass

    @abstractmethod
    async def get_confirmations(self, tx_hash: str) -> int:
        """Get confirmation count for a transaction"""
        pass


class MockChainGateway(ChainGateway):
    def __init__(self):
        self.pending_deposits: List[DepositEvent] = []
        self.withdrawals: Dict[str, Dict[str, Any]] = {}
        self.confirmations: Dict[str, int] = {}

    async def watch_deposits(self) -> AsyncIterator[DepositEvent]:
        """Mock deposit watcher - yields pending deposits"""
        while True:
            if self.pending_deposits:
                event = self.pending_deposits.pop(0)
                yield event
            else:
                await asyncio.sleep(0.1)

    async def create_withdrawal(self, address: str, amount_u: int) -> str:
        """Mock withdrawal - immediately returns a fake tx_hash"""
        tx_hash = f"0x{uuid.uuid4().hex[:64]}"
        self.withdrawals[tx_hash] = {
            "address": address,
            "amount_u": amount_u,
            "status": "pending"
        }
        # Mock immediate confirmation
        self.confirmations[tx_hash] = 1
        return tx_hash

    async def get_confirmations(self, tx_hash: str) -> int:
        """Mock confirmations - returns stored confirmation count"""
        return self.confirmations.get(tx_hash, 0)

    def add_deposit(self, user_id: uuid.UUID, amount_u: int, confirmations: int = 1):
        """Helper method to simulate deposits for testing"""
        event = DepositEvent(
            user_id=user_id,
            amount_u=amount_u,
            tx_hash=f"0x{uuid.uuid4().hex[:64]}",
            confirmations=confirmations
        )
        self.pending_deposits.append(event)