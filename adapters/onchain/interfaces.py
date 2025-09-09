import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Literal

from onramp.models import ChainType


@dataclass
class DepositEvent:
    """Event emitted when a deposit is detected on-chain"""
    user_id: uuid.UUID
    intent_id: uuid.UUID
    tx_sig: str
    amount_u: int
    confirmations: int
    raw_data: dict


@dataclass
class BroadcastResult:
    """Result of broadcasting a transaction"""
    tx_sig: str
    success: bool
    error: Optional[str] = None


class OnchainGateway(ABC):
    """Abstract interface for on-chain operations"""
    
    chain: ChainType
    usdc_mint: str
    min_confirmations: int

    @abstractmethod
    async def generate_address(self, user_id: uuid.UUID, intent_id: uuid.UUID) -> str:
        """Generate a unique address for deposit intent"""
        pass

    @abstractmethod
    async def build_payment_uri(self, address: str, amount_u: Optional[int], intent_id: Optional[uuid.UUID]) -> str:
        """Build payment URI (Solana Pay / EIP-681)"""
        pass

    @abstractmethod
    async def watch_deposits(self, start_cursor: Optional[str] = None) -> AsyncIterator[DepositEvent]:
        """Watch for deposits to our addresses"""
        pass

    @abstractmethod
    async def send_usdc(self, to_address: str, amount_u: int) -> BroadcastResult:
        """Send USDC to address"""
        pass

    @abstractmethod
    async def get_confirmations(self, tx_sig: str) -> int:
        """Get confirmation count for transaction"""
        pass

    @abstractmethod
    async def get_balance(self, address: str) -> int:
        """Get USDC balance for address (in micro-USDC)"""
        pass

    @abstractmethod
    async def is_valid_address(self, address: str) -> bool:
        """Validate address format"""
        pass