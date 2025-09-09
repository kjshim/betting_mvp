import hashlib
import uuid
import asyncio
import logging
from typing import AsyncIterator, Optional, Dict, Any
from urllib.parse import urlencode

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey as PublicKey
from solders.signature import Signature
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction

from adapters.onchain.interfaces import OnchainGateway, DepositEvent, BroadcastResult
from onramp.models import ChainType
from infra.settings import settings

logger = logging.getLogger(__name__)


class SolanaUSDCAdapter(OnchainGateway):
    """Solana USDC adapter using solana-py"""
    
    def __init__(self, rpc_url: str, usdc_mint: str, min_confirmations: int = 1, hot_wallet_keypair: Optional[Keypair] = None):
        self.chain = ChainType.SOL
        self.rpc_url = rpc_url
        self.usdc_mint = usdc_mint
        self.usdc_mint_pubkey = PublicKey(usdc_mint)
        self.min_confirmations = min_confirmations
        self.client = AsyncClient(rpc_url)
        self.derive_seed = bytes.fromhex(settings.solana_derive_seed)
        self.hot_wallet = hot_wallet_keypair or self._generate_hot_wallet()
        
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
        """Watch for USDC deposits by polling confirmed signatures"""
        self._monitoring = True
        
        # Parse start cursor (slot number)
        start_slot = int(start_cursor) if start_cursor else None
        
        logger.info(f"Starting Solana deposit monitoring from slot {start_slot}")
        
        try:
            while self._monitoring:
                try:
                    # Get current slot
                    slot_response = await self.client.get_slot(commitment=Confirmed)
                    current_slot = slot_response.value
                    
                    # If no start slot, start from current
                    if start_slot is None:
                        start_slot = current_slot
                        self._last_processed_slot = current_slot
                        await asyncio.sleep(10)  # Wait for next poll
                        continue
                    
                    # Process slots since last processed
                    from_slot = self._last_processed_slot or start_slot
                    to_slot = min(from_slot + 100, current_slot)  # Process in batches
                    
                    if to_slot > from_slot:
                        await self._process_slot_range(from_slot, to_slot)
                        self._last_processed_slot = to_slot
                    
                    # Wait before next poll
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"Error in deposit monitoring: {e}")
                    await asyncio.sleep(5)  # Wait longer on error
                    
        except asyncio.CancelledError:
            logger.info("Deposit monitoring cancelled")
            self._monitoring = False

    async def _process_slot_range(self, from_slot: int, to_slot: int):
        """Process transactions in a range of slots"""
        # Get confirmed blocks in range
        try:
            blocks_response = await self.client.get_blocks(from_slot, to_slot, commitment=Confirmed)
            slots = blocks_response.value
            
            for slot in slots:
                try:
                    # Get block with transactions
                    block_response = await self.client.get_block(
                        slot, 
                        encoding="json",
                        transaction_details="full",
                        rewards=False,
                        commitment=Confirmed
                    )
                    
                    if not block_response.value:
                        continue
                        
                    block = block_response.value
                    
                    for tx_info in block.transactions:
                        if tx_info.meta and tx_info.meta.err is None:
                            # Process successful transaction
                            await self._process_transaction(tx_info, slot)
                            
                except Exception as e:
                    logger.warning(f"Error processing slot {slot}: {e}")
                    
        except Exception as e:
            logger.error(f"Error getting blocks {from_slot}-{to_slot}: {e}")

    async def _process_transaction(self, tx_info, slot: int):
        """Process a single transaction for USDC transfers"""
        try:
            # Look for SPL token transfers in the transaction
            if not tx_info.meta or not tx_info.meta.post_token_balances:
                return
                
            signature = str(tx_info.transaction.signatures[0])
            
            # Check for USDC transfers by examining token balance changes
            for i, post_balance in enumerate(tx_info.meta.post_token_balances):
                if post_balance.mint != str(self.usdc_mint_pubkey):
                    continue
                    
                # Find corresponding pre-balance
                pre_balance = None
                if tx_info.meta.pre_token_balances and i < len(tx_info.meta.pre_token_balances):
                    pre_balance = tx_info.meta.pre_token_balances[i]
                
                # Calculate amount change
                post_amount = int(post_balance.ui_token_amount.amount)
                pre_amount = int(pre_balance.ui_token_amount.amount) if pre_balance else 0
                amount_change = post_amount - pre_amount
                
                if amount_change > 0:  # This is a deposit
                    recipient = post_balance.owner
                    
                    # Check if this is one of our monitored addresses
                    deposit_event = await self._match_deposit_to_intent(
                        recipient, amount_change, signature, slot
                    )
                    
                    if deposit_event:
                        yield deposit_event
                        
        except Exception as e:
            logger.warning(f"Error processing transaction: {e}")

    async def _match_deposit_to_intent(self, recipient: str, amount_u: int, tx_sig: str, slot: int) -> Optional[DepositEvent]:
        """Match a deposit to a deposit intent"""
        # This would need to query database for deposit intents with matching addresses
        # For now, create a mock event for testing
        # In production, this would:
        # 1. Query database for deposit_intents with matching address
        # 2. Verify the transaction details
        # 3. Return DepositEvent with correct user_id and intent_id
        
        # Mock implementation for testing
        if recipient.startswith("mock_") or len(recipient) > 40:
            return DepositEvent(
                user_id=uuid.uuid4(),  # Would be from database lookup
                intent_id=uuid.uuid4(),  # Would be from database lookup
                tx_sig=tx_sig,
                amount_u=amount_u,
                confirmations=await self.get_confirmations(tx_sig),
                raw_data={
                    "slot": slot,
                    "recipient": recipient,
                    "mint": str(self.usdc_mint_pubkey)
                }
            )
        return None

    async def send_usdc(self, to_address: str, amount_u: int) -> BroadcastResult:
        """Send USDC to address using SPL token transfer"""
        try:
            to_pubkey = PublicKey(to_address)
            
            # Get or create associated token accounts  
            from spl.token.instructions import get_associated_token_address
            
            hot_wallet_ata = get_associated_token_address(
                self.hot_wallet.pubkey(),
                self.usdc_mint_pubkey
            )
            
            to_ata = get_associated_token_address(
                to_pubkey,
                self.usdc_mint_pubkey
            )
            
            # Check if destination ATA exists
            dest_account_info = await self.client.get_account_info(to_ata)
            
            # Build transaction
            transaction = Transaction()
            
            # Create destination ATA if it doesn't exist
            if not dest_account_info.value:
                from spl.token.instructions import create_associated_token_account
                
                create_ata_ix = create_associated_token_account(
                    payer=self.hot_wallet.pubkey(),
                    owner=to_pubkey,
                    mint=self.usdc_mint_pubkey
                )
                transaction.add(create_ata_ix)
            
            # Add transfer instruction
            from spl.token.instructions import transfer_checked, TransferCheckedParams, TOKEN_PROGRAM_ID
            
            transfer_ix = transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=hot_wallet_ata,
                    mint=self.usdc_mint_pubkey,
                    dest=to_ata,
                    owner=self.hot_wallet.pubkey(),
                    amount=amount_u,
                    decimals=6,  # USDC has 6 decimals
                )
            )
            transaction.add(transfer_ix)
            
            # Get recent blockhash
            blockhash_response = await self.client.get_latest_blockhash()
            transaction.recent_blockhash = blockhash_response.value.blockhash
            
            # Sign and send transaction
            transaction.sign(self.hot_wallet)
            
            tx_response = await self.client.send_transaction(
                transaction,
                opts=TxOpts(
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            
            signature = str(tx_response.value)
            
            return BroadcastResult(
                tx_sig=signature,
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
            if tx_sig.startswith("mock_"):
                return self.min_confirmations  # Mock confirmed
                
            signature = Signature.from_string(tx_sig)
            result = await self.client.get_signature_statuses([signature])
            
            if result.value and result.value[0]:
                status = result.value[0]
                if status.confirmation_status:
                    # Map Solana confirmation levels to numbers
                    if status.confirmation_status == "finalized":
                        return 10
                    elif status.confirmation_status == "confirmed":
                        return 1
                    else:
                        return 0
            return 0
        except Exception:
            return 0

    async def get_balance(self, address: str) -> int:
        """Get USDC balance for address"""
        try:
            if address.startswith("mock_"):
                return 1000000  # Mock 1 USDC balance
                
            pubkey = PublicKey(address)
            
            # Get associated token account for USDC
            from spl.token.instructions import get_associated_token_address
            ata = get_associated_token_address(pubkey, self.usdc_mint_pubkey)
            
            try:
                token_account_info = await self.client.get_token_account_balance(ata)
                if token_account_info.value:
                    return int(token_account_info.value.amount)
            except Exception:
                # ATA might not exist, which means 0 balance
                pass
            
            return 0
        except Exception as e:
            logger.warning(f"Error getting balance for {address}: {e}")
            return 0

    async def is_valid_address(self, address: str) -> bool:
        """Validate Solana address format"""
        try:
            if address.startswith("mock_"):
                return True
            PublicKey(address)
            return True
        except Exception:
            return False

    async def stop_monitoring(self):
        """Stop the monitoring loop"""
        self._monitoring = False

    async def airdrop_sol(self, address: str, lamports: int = 1_000_000_000) -> str:
        """Airdrop SOL for testing (only works on devnet/testnet)"""
        try:
            pubkey = PublicKey(address)
            response = await self.client.request_airdrop(pubkey, lamports)
            return str(response.value)
        except Exception as e:
            logger.error(f"Airdrop failed: {e}")
            raise

    async def create_usdc_ata(self, owner: str) -> str:
        """Create associated token account for USDC"""
        try:
            from spl.token.instructions import get_associated_token_address, create_associated_token_account
            
            owner_pubkey = PublicKey(owner)
            ata = get_associated_token_address(owner_pubkey, self.usdc_mint_pubkey)
            
            # Check if already exists
            account_info = await self.client.get_account_info(ata)
            if account_info.value:
                return str(ata)
            
            # Create the ATA
            transaction = Transaction()
            create_ata_ix = create_associated_token_account(
                payer=self.hot_wallet.pubkey(),
                owner=owner_pubkey,
                mint=self.usdc_mint_pubkey
            )
            transaction.add(create_ata_ix)
            
            # Get recent blockhash and send
            blockhash_response = await self.client.get_latest_blockhash()
            transaction.recent_blockhash = blockhash_response.value.blockhash
            transaction.sign(self.hot_wallet)
            
            tx_response = await self.client.send_transaction(transaction)
            
            return str(ata)
            
        except Exception as e:
            logger.error(f"Failed to create USDC ATA: {e}")
            raise