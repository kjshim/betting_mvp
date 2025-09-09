import hashlib
import uuid
import asyncio
import logging
from typing import AsyncIterator, Optional, Dict, Any
from urllib.parse import urlencode

from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey as PublicKey

from adapters.onchain.interfaces import OnchainGateway, DepositEvent, BroadcastResult
from onramp.models import ChainType
from infra.settings import settings

logger = logging.getLogger(__name__)


class SolanaUSDCAdapterSimple(OnchainGateway):
    """Simplified Solana USDC adapter for testing"""
    
    def __init__(self, rpc_url: str, usdc_mint: str, min_confirmations: int = 1):
        self.chain = ChainType.SOL
        self.rpc_url = rpc_url
        self.usdc_mint = usdc_mint
        self.usdc_mint_pubkey = PublicKey.from_string(usdc_mint)
        self.min_confirmations = min_confirmations
        self.client = AsyncClient(rpc_url)
        self.derive_seed = bytes.fromhex(settings.solana_derive_seed)
        self.hot_wallet = self._generate_hot_wallet()
        
        # For monitoring
        self._monitoring = False
        self._last_processed_slot = None

    def _generate_hot_wallet(self) -> Keypair:
        """Generate hot wallet from seed (for development/testing)"""
        hot_seed = hashlib.sha256(self.derive_seed + b"hot_wallet").digest()[:32]
        return Keypair.from_seed(hot_seed)

    def _derive_keypair(self, user_id: uuid.UUID, intent_id: uuid.UUID) -> Keypair:
        """Derive deterministic keypair for deposit intent"""
        seed_data = self.derive_seed + user_id.bytes + intent_id.bytes
        seed_hash = hashlib.sha256(seed_data).digest()[:32]
        return Keypair.from_seed(seed_hash)

    async def generate_address(self, user_id: uuid.UUID, intent_id: uuid.UUID) -> str:
        """Generate unique address for deposit intent"""
        keypair = self._derive_keypair(user_id, intent_id)
        return str(keypair.pubkey())

    async def build_payment_uri(self, address: str, amount_u: Optional[int], intent_id: Optional[uuid.UUID]) -> str:
        """Build Solana Pay URI"""
        params = {
            "recipient": address,
            "spl-token": self.usdc_mint,
            "label": "Betting MVP Deposit"
        }
        
        if amount_u is not None:
            # Convert micro-USDC to USDC (6 decimals)
            params["amount"] = str(amount_u / 1_000_000)
        
        if intent_id is not None:
            # Use intent_id as reference
            params["reference"] = str(intent_id).replace("-", "")
        
        return f"solana:{self.usdc_mint}?" + urlencode(params)

    async def watch_deposits(self, start_cursor: Optional[str] = None) -> AsyncIterator[DepositEvent]:
        """Watch for USDC deposits (simplified implementation)"""
        logger.info("Starting simplified Solana deposit monitoring...")
        
        # For testing, we'll just simulate some events
        await asyncio.sleep(1)
        
        # Mock deposit event
        yield DepositEvent(
            user_id=uuid.uuid4(),
            intent_id=uuid.uuid4(),
            tx_sig=f"solana_test_tx_{uuid.uuid4().hex[:16]}",
            amount_u=1000000,  # 1 USDC
            confirmations=self.min_confirmations,
            raw_data={"slot": 12345, "mock": True}
        )

    async def send_usdc(self, to_address: str, amount_u: int) -> BroadcastResult:
        """Send USDC to address (mock implementation for testing)"""
        try:
            # Simulate transaction
            await asyncio.sleep(0.1)
            
            mock_signature = f"solana_send_tx_{uuid.uuid4().hex[:16]}"
            return BroadcastResult(
                tx_sig=mock_signature,
                success=True
            )
            
        except Exception as e:
            logger.error(f"Failed to send USDC: {e}")
            return BroadcastResult(
                tx_sig="",
                success=False,
                error=str(e)
            )

    async def get_confirmations(self, tx_sig: str) -> int:
        """Get confirmation count for transaction"""
        try:
            if tx_sig.startswith("solana_"):
                return self.min_confirmations  # Mock confirmed
            
            # For real transactions, we'd query the RPC
            return 0
        except Exception:
            return 0

    async def get_balance(self, address: str) -> int:
        """Get USDC balance for address"""
        try:
            if address.startswith("mock_") or len(address) > 40:
                return 1000000  # Mock 1 USDC balance
            
            # For real addresses, we'd query the token account
            return 0
        except Exception as e:
            logger.warning(f"Error getting balance for {address}: {e}")
            return 0

    async def is_valid_address(self, address: str) -> bool:
        """Validate Solana address format"""
        try:
            if address.startswith("mock_"):
                return True
            PublicKey.from_string(address)
            return True
        except Exception:
            return False

    async def stop_monitoring(self):
        """Stop the monitoring loop"""
        self._monitoring = False