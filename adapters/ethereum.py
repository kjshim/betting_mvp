"""
Ethereum/Base blockchain adapter for production use.

This adapter connects to real Ethereum-compatible networks (Mainnet, Base, etc.)
and handles USDC deposit/withdrawal operations.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass

import aiohttp
from web3 import AsyncWeb3, Web3
from web3.eth import AsyncEth
from web3.exceptions import Web3Exception, ContractLogicError
from eth_account import Account
from eth_typing import Address, HexStr

from adapters.chain import ChainGateway, DepositEvent


logger = logging.getLogger(__name__)


@dataclass
class EthereumConfig:
    """Configuration for Ethereum chain adapter"""
    rpc_url: str
    usdc_contract_address: str
    deposit_wallet_address: str  # Our hot wallet for receiving deposits
    withdrawal_private_key: str  # Private key for withdrawal transactions
    confirmation_blocks: int = 6
    block_poll_interval: int = 12  # seconds
    gas_multiplier: float = 1.2  # Gas price multiplier for reliability
    max_gas_price_gwei: int = 100  # Maximum gas price in gwei
    

class EthereumGateway(ChainGateway):
    """
    Production Ethereum/Base blockchain adapter.
    
    Handles USDC deposits and withdrawals with proper confirmation monitoring.
    """
    
    # Standard ERC-20 Transfer event signature
    TRANSFER_EVENT_SIGNATURE = Web3.keccak(text="Transfer(address,address,uint256)").hex()
    
    # USDC has 6 decimals
    USDC_DECIMALS = 6
    
    def __init__(self, config: EthereumConfig):
        self.config = config
        self.w3: Optional[AsyncWeb3] = None
        self.usdc_contract = None
        self.account = Account.from_key(config.withdrawal_private_key)
        self.session: Optional[aiohttp.ClientSession] = None
        
        # State tracking
        self.last_processed_block = 0
        self.deposit_cache: Dict[str, DepositEvent] = {}
        self.withdrawal_nonces: Dict[str, int] = {}
        
        # Standard ERC-20 ABI (Transfer function and events only)
        self.erc20_abi = [
            {
                "constant": False,
                "inputs": [
                    {"name": "_to", "type": "address"},
                    {"name": "_value", "type": "uint256"}
                ],
                "name": "transfer",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            },
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "from", "type": "address"},
                    {"indexed": True, "name": "to", "type": "address"},
                    {"indexed": False, "name": "value", "type": "uint256"}
                ],
                "name": "Transfer",
                "type": "event"
            }
        ]
        
    async def initialize(self):
        """Initialize the gateway connection"""
        try:
            # Create web3 connection
            self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self.config.rpc_url))
            
            # Verify connection
            if not await self.w3.is_connected():
                raise ConnectionError(f"Unable to connect to Ethereum node at {self.config.rpc_url}")
                
            # Initialize USDC contract
            contract_address = Web3.to_checksum_address(self.config.usdc_contract_address)
            self.usdc_contract = self.w3.eth.contract(
                address=contract_address,
                abi=self.erc20_abi
            )
            
            # Verify contract
            try:
                decimals = await self.usdc_contract.functions.decimals().call()
                if decimals != self.USDC_DECIMALS:
                    logger.warning(f"USDC contract has {decimals} decimals, expected {self.USDC_DECIMALS}")
            except Exception as e:
                logger.warning(f"Could not verify USDC contract decimals: {e}")
                
            # Get current block for starting point
            self.last_processed_block = await self.w3.eth.get_block_number()
            
            logger.info(f"Ethereum gateway initialized, starting from block {self.last_processed_block}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Ethereum gateway: {e}")
            raise
            
    async def close(self):
        """Close connections"""
        if self.session:
            await self.session.close()
            
    async def watch_deposits(self) -> AsyncIterator[DepositEvent]:
        """Watch for USDC deposits to our wallet address"""
        if not self.w3 or not self.usdc_contract:
            raise RuntimeError("Gateway not initialized")
            
        deposit_address = Web3.to_checksum_address(self.config.deposit_wallet_address)
        
        while True:
            try:
                current_block = await self.w3.eth.get_block_number()
                
                # Process new blocks
                if current_block > self.last_processed_block:
                    from_block = self.last_processed_block + 1
                    to_block = min(current_block, from_block + 100)  # Process in chunks
                    
                    # Get Transfer events to our deposit address
                    event_filter = await self.usdc_contract.events.Transfer.create_filter(
                        fromBlock=from_block,
                        toBlock=to_block,
                        argument_filters={'to': deposit_address}
                    )
                    
                    events = await event_filter.get_all_entries()
                    
                    for event in events:
                        try:
                            deposit_event = await self._process_deposit_event(event)
                            if deposit_event:
                                yield deposit_event
                        except Exception as e:
                            logger.error(f"Error processing deposit event {event}: {e}")
                            continue
                    
                    self.last_processed_block = to_block
                    
                await asyncio.sleep(self.config.block_poll_interval)
                
            except Exception as e:
                logger.error(f"Error watching deposits: {e}")
                await asyncio.sleep(self.config.block_poll_interval)
                continue
                
    async def _process_deposit_event(self, event) -> Optional[DepositEvent]:
        """Process a Transfer event and convert to DepositEvent"""
        try:
            tx_hash = event['transactionHash'].hex()
            
            # Skip if we've already processed this
            if tx_hash in self.deposit_cache:
                return None
                
            # Get transaction details to extract user info
            # In a real system, you'd have a mapping from addresses to user_ids
            # For now, we'll extract from transaction data or use a lookup service
            
            block_number = event['blockNumber']
            current_block = await self.w3.eth.get_block_number()
            confirmations = current_block - block_number + 1
            
            # Convert USDC amount (6 decimals) to micro-USDC (our internal format)
            usdc_amount = event['args']['value']  # This is in USDC wei (6 decimals)
            amount_u = usdc_amount  # Already in micro-USDC format
            
            # Extract user_id from transaction memo or address mapping
            # This is application-specific - you might:
            # 1. Use transaction input data for user identification
            # 2. Maintain an address -> user_id mapping
            # 3. Use a deterministic address generation scheme
            
            user_id = await self._extract_user_id_from_transaction(event)
            if not user_id:
                logger.warning(f"Could not extract user_id from deposit transaction {tx_hash}")
                return None
                
            deposit_event = DepositEvent(
                user_id=user_id,
                amount_u=amount_u,
                tx_hash=tx_hash,
                confirmations=confirmations
            )
            
            # Cache to avoid reprocessing
            self.deposit_cache[tx_hash] = deposit_event
            
            logger.info(f"Processed deposit: {amount_u} micro-USDC from user {user_id} (tx: {tx_hash})")
            
            return deposit_event
            
        except Exception as e:
            logger.error(f"Error processing deposit event: {e}")
            return None
            
    async def _extract_user_id_from_transaction(self, event) -> Optional[str]:
        """
        Extract user_id from transaction data.
        
        Implementation depends on your user identification strategy:
        - Transaction memo/data field
        - Address mapping lookup
        - Deterministic address generation
        """
        # TODO: Implement based on your user identification strategy
        # For now, return None to indicate we couldn't extract user_id
        return None
        
    async def create_withdrawal(self, address: str, amount_u: int) -> str:
        """Create a USDC withdrawal transaction"""
        if not self.w3 or not self.usdc_contract:
            raise RuntimeError("Gateway not initialized")
            
        # Validate address
        try:
            to_address = Web3.to_checksum_address(address)
        except ValueError as e:
            raise ValueError(f"Invalid withdrawal address: {address}") from e
            
        if amount_u <= 0:
            raise ValueError("Withdrawal amount must be positive")
            
        try:
            # Check our USDC balance
            our_balance = await self.usdc_contract.functions.balanceOf(self.account.address).call()
            if our_balance < amount_u:
                raise ValueError(f"Insufficient USDC balance: {our_balance} < {amount_u}")
                
            # Get current gas price
            gas_price = await self._get_gas_price()
            
            # Build transaction
            transaction = await self.usdc_contract.functions.transfer(
                to_address, amount_u
            ).build_transaction({
                'from': self.account.address,
                'gas': 100000,  # Standard ERC-20 transfer gas limit
                'gasPrice': gas_price,
                'nonce': await self.w3.eth.get_transaction_count(self.account.address),
            })
            
            # Sign transaction
            signed_txn = self.account.sign_transaction(transaction)
            
            # Send transaction
            tx_hash = await self.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
            tx_hash_hex = tx_hash.hex()
            
            logger.info(f"Created withdrawal transaction: {amount_u} micro-USDC to {address} (tx: {tx_hash_hex})")
            
            return tx_hash_hex
            
        except ContractLogicError as e:
            logger.error(f"Contract logic error during withdrawal: {e}")
            raise ValueError(f"Withdrawal failed: {e}") from e
        except Web3Exception as e:
            logger.error(f"Web3 error during withdrawal: {e}")
            raise RuntimeError(f"Network error during withdrawal: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during withdrawal: {e}")
            raise RuntimeError(f"Withdrawal failed: {e}") from e
            
    async def get_confirmations(self, tx_hash: str) -> int:
        """Get confirmation count for a transaction"""
        if not self.w3:
            raise RuntimeError("Gateway not initialized")
            
        try:
            tx_receipt = await self.w3.eth.get_transaction_receipt(tx_hash)
            if tx_receipt is None:
                return 0
                
            current_block = await self.w3.eth.get_block_number()
            confirmations = current_block - tx_receipt['blockNumber'] + 1
            
            return max(0, confirmations)
            
        except Exception as e:
            logger.error(f"Error getting confirmations for {tx_hash}: {e}")
            return 0
            
    def get_pending_deposits(self, min_confirmations: int = 6) -> List[Dict[str, Any]]:
        """Get deposits with at least min_confirmations"""
        result = []
        
        for tx_hash, deposit_event in self.deposit_cache.items():
            if deposit_event.confirmations >= min_confirmations:
                result.append({
                    "user_id": deposit_event.user_id,
                    "amount_u": deposit_event.amount_u,
                    "tx_hash": tx_hash,
                    "confirmations": deposit_event.confirmations
                })
                
        return result
        
    def get_pending_withdrawals(self) -> List[Dict[str, Any]]:
        """Get pending withdrawal transactions"""
        # In a real implementation, you'd track withdrawal transactions
        # and their confirmation status
        return []
        
    def get_transaction_status(self, tx_hash: str) -> Dict[str, Any]:
        """Get transaction confirmation status"""
        # This would be implemented by checking the transaction on-chain
        return {
            "confirmed": False,
            "confirmations": 0,
            "exists": False
        }
        
    async def estimate_withdrawal_gas(self, address: str, amount_u: int) -> int:
        """Estimate gas needed for withdrawal transaction"""
        if not self.w3 or not self.usdc_contract:
            raise RuntimeError("Gateway not initialized")
            
        try:
            to_address = Web3.to_checksum_address(address)
        except ValueError as e:
            raise ValueError(f"Invalid address: {address}") from e
            
        try:
            # Estimate gas for transfer
            gas_estimate = await self.usdc_contract.functions.transfer(
                to_address, amount_u
            ).estimate_gas({'from': self.account.address})
            
            # Add 20% buffer
            return int(gas_estimate * 1.2)
            
        except Exception as e:
            logger.error(f"Gas estimation failed: {e}")
            # Return conservative estimate
            return 100000
            
    async def _get_gas_price(self) -> int:
        """Get current gas price with safety limits"""
        if not self.w3:
            raise RuntimeError("Gateway not initialized")
            
        try:
            # Get current gas price
            gas_price = await self.w3.eth.gas_price
            
            # Apply multiplier for reliability
            adjusted_gas_price = int(gas_price * self.config.gas_multiplier)
            
            # Cap at maximum
            max_gas_price_wei = self.config.max_gas_price_gwei * 10**9
            final_gas_price = min(adjusted_gas_price, max_gas_price_wei)
            
            logger.debug(f"Using gas price: {final_gas_price / 10**9:.2f} gwei")
            
            return final_gas_price
            
        except Exception as e:
            logger.error(f"Error getting gas price: {e}")
            # Return conservative fallback (20 gwei)
            return 20 * 10**9
            
    async def get_wallet_balance(self) -> int:
        """Get our USDC wallet balance in micro-USDC"""
        if not self.w3 or not self.usdc_contract:
            raise RuntimeError("Gateway not initialized")
            
        try:
            balance = await self.usdc_contract.functions.balanceOf(self.account.address).call()
            return balance
            
        except Exception as e:
            logger.error(f"Error getting wallet balance: {e}")
            return 0
            
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the gateway"""
        if not self.w3:
            return {
                "healthy": False,
                "error": "Gateway not initialized"
            }
            
        try:
            # Check connection
            latest_block = await self.w3.eth.get_block_number()
            
            # Check USDC balance
            balance = await self.get_wallet_balance()
            
            # Check gas price
            gas_price_gwei = (await self.w3.eth.gas_price) / 10**9
            
            return {
                "healthy": True,
                "latest_block": latest_block,
                "last_processed_block": self.last_processed_block,
                "wallet_balance_usdc": balance / 10**6,
                "gas_price_gwei": float(gas_price_gwei),
                "deposit_cache_size": len(self.deposit_cache)
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e)
            }


# Factory function for creating the gateway based on network
def create_ethereum_gateway(network: str = "base-mainnet") -> EthereumGateway:
    """
    Factory function to create EthereumGateway for different networks.
    
    Supported networks:
    - ethereum-mainnet: Ethereum Mainnet
    - base-mainnet: Base L2 (recommended for lower fees)
    - base-sepolia: Base Sepolia testnet
    """
    
    network_configs = {
        "ethereum-mainnet": {
            "rpc_url": "https://eth-mainnet.g.alchemy.com/v2/YOUR_API_KEY",
            "usdc_contract_address": "0xA0b86a33E6441eCDE0650E8Fc18dc72d55e51827"  # USDC on Ethereum
        },
        "base-mainnet": {
            "rpc_url": "https://mainnet.base.org",
            "usdc_contract_address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"  # USDC on Base
        },
        "base-sepolia": {
            "rpc_url": "https://sepolia.base.org", 
            "usdc_contract_address": "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # USDC on Base Sepolia
        }
    }
    
    if network not in network_configs:
        raise ValueError(f"Unsupported network: {network}")
        
    network_config = network_configs[network]
    
    # These would come from environment variables in production
    config = EthereumConfig(
        rpc_url=network_config["rpc_url"],
        usdc_contract_address=network_config["usdc_contract_address"],
        deposit_wallet_address="0x1234567890123456789012345678901234567890",  # Your hot wallet
        withdrawal_private_key="0x" + "0" * 64,  # Your withdrawal private key
        confirmation_blocks=6 if "mainnet" in network else 3,
        block_poll_interval=12 if network == "ethereum-mainnet" else 2,  # Base is faster
    )
    
    return EthereumGateway(config)