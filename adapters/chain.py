import asyncio
import re
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

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

    @abstractmethod
    def get_pending_deposits(self, min_confirmations: int = 6) -> List[Dict[str, Any]]:
        """Get pending deposits with minimum confirmations"""
        pass

    @abstractmethod
    def get_pending_withdrawals(self) -> List[Dict[str, Any]]:
        """Get pending withdrawal transactions"""
        pass

    @abstractmethod
    def get_transaction_status(self, tx_hash: str) -> Dict[str, Any]:
        """Get transaction status and confirmation count"""
        pass

    @abstractmethod
    async def estimate_withdrawal_gas(self, address: str, amount_u: int) -> int:
        """Estimate gas needed for withdrawal"""
        pass


class MockChainGateway(ChainGateway):
    def __init__(self):
        self.pending_deposits: List[DepositEvent] = []
        self.withdrawals: Dict[str, Dict[str, Any]] = {}
        self.confirmations: Dict[str, int] = {}
        self.deposit_registry: Dict[str, Dict[str, Any]] = {}  # tx_hash -> deposit info
        self.current_block_height = 1000000
        self.network_failure = False
        self.high_gas_prices = False
        
    async def watch_deposits(self) -> AsyncIterator[DepositEvent]:
        """Mock deposit watcher - yields pending deposits"""
        while True:
            if self.pending_deposits:
                event = self.pending_deposits.pop(0)
                yield event
            else:
                await asyncio.sleep(0.1)

    async def create_withdrawal(self, address: str, amount_u: int) -> str:
        """Mock withdrawal - returns a transaction hash"""
        # Validate inputs
        if not self._is_valid_address(address):
            raise ValueError(f"Invalid address: {address}")
        
        if amount_u <= 0:
            raise ValueError("Amount must be positive")
        
        # Check for simulated failures
        if self.network_failure:
            raise Exception("Network failure: Cannot connect to blockchain")
        
        if self.high_gas_prices:
            # In real implementation, this might fail or require higher gas
            pass
        
        tx_hash = f"0x{uuid.uuid4().hex}{uuid.uuid4().hex[:32]}"
        self.withdrawals[tx_hash] = {
            "address": address,
            "amount_u": amount_u,
            "status": "pending",
            "created_at": time.time(),
            "block_height": self.current_block_height
        }
        # Start with 0 confirmations
        self.confirmations[tx_hash] = 0
        return tx_hash

    async def get_confirmations(self, tx_hash: str) -> int:
        """Mock confirmations - returns stored confirmation count"""
        return self.confirmations.get(tx_hash, 0)
    
    def get_pending_deposits(self, min_confirmations: int = 6) -> List[Dict[str, Any]]:
        """Get deposits with at least min_confirmations"""
        result = []
        for tx_hash, deposit in self.deposit_registry.items():
            confirmations = self.confirmations.get(tx_hash, 0)
            if confirmations >= min_confirmations:
                result.append({
                    "user_id": deposit["user_id"],
                    "amount_u": deposit["amount_u"], 
                    "tx_hash": tx_hash,
                    "confirmations": confirmations
                })
        return result
    
    def get_pending_withdrawals(self) -> List[Dict[str, Any]]:
        """Get all pending withdrawals"""
        result = []
        for tx_hash, withdrawal in self.withdrawals.items():
            confirmations = self.confirmations.get(tx_hash, 0)
            result.append({
                "tx_hash": tx_hash,
                "address": withdrawal["address"],
                "amount_u": withdrawal["amount_u"],
                "status": withdrawal["status"],
                "confirmations": confirmations
            })
        return result
    
    def get_transaction_status(self, tx_hash: str) -> Dict[str, Any]:
        """Get transaction confirmation status"""
        confirmations = self.confirmations.get(tx_hash, 0)
        return {
            "confirmed": confirmations >= 6,
            "confirmations": confirmations,
            "exists": tx_hash in self.confirmations
        }
    
    async def estimate_withdrawal_gas(self, address: str, amount_u: int) -> int:
        """Estimate gas for withdrawal transaction"""
        if not self._is_valid_address(address):
            raise ValueError(f"Invalid address: {address}")
        
        if self.high_gas_prices:
            return 500000  # High gas estimate
        else:
            return 21000   # Standard gas for simple transfer

    def add_deposit(self, user_id: uuid.UUID, amount_u: int, confirmations: int = 1, 
                   tx_hash: Optional[str] = None):
        """Helper method to simulate deposits for testing"""
        if tx_hash is None:
            tx_hash = f"0x{uuid.uuid4().hex}{uuid.uuid4().hex[:32]}"
        
        # Check for duplicates
        if tx_hash not in self.deposit_registry:
            self.deposit_registry[tx_hash] = {
                "user_id": user_id,
                "amount_u": amount_u,
                "created_at": time.time(),
                "block_height": self.current_block_height
            }
        
        # Update confirmations
        self.confirmations[tx_hash] = confirmations
        
        # Also add to pending deposits queue for watch_deposits
        event = DepositEvent(
            user_id=user_id,
            amount_u=amount_u,
            tx_hash=tx_hash,
            confirmations=confirmations
        )
        # Only add if not already in queue
        if not any(e.tx_hash == tx_hash for e in self.pending_deposits):
            self.pending_deposits.append(event)
    
    def mine_blocks(self, count: int):
        """Simulate mining blocks to increase confirmations"""
        self.current_block_height += count
        
        # Increase confirmations for all transactions
        for tx_hash in self.confirmations:
            self.confirmations[tx_hash] += count
    
    def simulate_network_failure(self, failed: bool):
        """Simulate network connectivity issues"""
        self.network_failure = failed
        
    def simulate_high_gas_prices(self, high_gas: bool):
        """Simulate high gas price conditions"""
        self.high_gas_prices = high_gas
        
    def simulate_reorg(self, tx_hashes: List[str], new_confirmations: int):
        """Simulate blockchain reorganization affecting specific transactions"""
        for tx_hash in tx_hashes:
            if tx_hash in self.confirmations:
                self.confirmations[tx_hash] = new_confirmations
    
    def _is_valid_address(self, address: str) -> bool:
        """Validate Ethereum address format"""
        if not isinstance(address, str):
            return False
        
        # Must start with 0x
        if not address.startswith("0x"):
            return False
            
        # Must be exactly 42 characters (0x + 40 hex chars)
        if len(address) != 42:
            return False
            
        # Must contain only valid hex characters after 0x
        hex_part = address[2:]
        return bool(re.match(r'^[0-9a-fA-F]{40}$', hex_part))