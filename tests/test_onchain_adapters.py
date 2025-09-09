import pytest
import uuid
from unittest.mock import AsyncMock, patch

from adapters.onchain.solana import SolanaUSDCAdapter
from onramp.models import ChainType


class TestSolanaAdapter:
    def test_adapter_initialization(self):
        """Test Solana adapter initialization"""
        adapter = SolanaUSDCAdapter(
            rpc_url="http://localhost:8899",
            usdc_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            min_confirmations=1
        )
        
        assert adapter.chain == ChainType.SOL
        assert adapter.rpc_url == "http://localhost:8899"
        assert adapter.min_confirmations == 1

    @pytest.mark.asyncio
    async def test_address_generation(self):
        """Test deterministic address generation"""
        adapter = SolanaUSDCAdapter(
            rpc_url="http://localhost:8899",
            usdc_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            min_confirmations=1
        )
        
        user_id = uuid.uuid4()
        intent_id = uuid.uuid4()
        
        # Generate address twice - should be deterministic
        address1 = await adapter.generate_address(user_id, intent_id)
        address2 = await adapter.generate_address(user_id, intent_id)
        
        assert address1 == address2
        assert len(address1) > 32  # Solana addresses are base58 encoded
        
        # Different intent should generate different address
        intent_id2 = uuid.uuid4()
        address3 = await adapter.generate_address(user_id, intent_id2)
        assert address1 != address3

    @pytest.mark.asyncio
    async def test_payment_uri_generation(self):
        """Test Solana Pay URI generation"""
        adapter = SolanaUSDCAdapter(
            rpc_url="http://localhost:8899",
            usdc_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            min_confirmations=1
        )
        
        address = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
        amount_u = 1000000  # 1 USDC
        intent_id = uuid.uuid4()
        
        uri = await adapter.build_payment_uri(address, amount_u, intent_id)
        
        assert uri.startswith("solana:")
        assert adapter.usdc_mint in uri
        assert address in uri
        assert "amount=1.0" in uri
        assert str(intent_id).replace("-", "") in uri

    @pytest.mark.asyncio
    async def test_send_usdc_mock(self):
        """Test USDC sending (mock implementation)"""
        adapter = SolanaUSDCAdapter(
            rpc_url="http://localhost:8899",
            usdc_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            min_confirmations=1
        )
        
        to_address = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
        amount_u = 1000000
        
        result = await adapter.send_usdc(to_address, amount_u)
        
        assert result.success is True
        assert result.tx_sig.startswith("mock_solana_tx_")

    @pytest.mark.asyncio
    async def test_address_validation(self):
        """Test Solana address validation"""
        adapter = SolanaUSDCAdapter(
            rpc_url="http://localhost:8899",
            usdc_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            min_confirmations=1
        )
        
        # Valid mock address
        assert await adapter.is_valid_address("mock_solana_address")
        
        # Invalid addresses
        assert not await adapter.is_valid_address("invalid")
        assert not await adapter.is_valid_address("")


class TestEVMAdapter:
    def test_adapter_initialization(self):
        """Test EVM adapter initialization"""
        adapter = EVMUSDCAdapter(
            rpc_url="http://localhost:8545",
            usdc_token="0xA0b86a33E6417c7C4b0A9764BB2A0E6D1A42AF5C",
            chain_id=31337,
            min_confirmations=2
        )
        
        assert adapter.chain == ChainType.EVM
        assert adapter.rpc_url == "http://localhost:8545"
        assert adapter.chain_id == 31337
        assert adapter.min_confirmations == 2

    @pytest.mark.asyncio
    async def test_address_generation(self):
        """Test deterministic address generation"""
        adapter = EVMUSDCAdapter(
            rpc_url="http://localhost:8545",
            usdc_token="0xA0b86a33E6417c7C4b0A9764BB2A0E6D1A42AF5C",
            chain_id=31337,
            min_confirmations=2
        )
        
        user_id = uuid.uuid4()
        intent_id = uuid.uuid4()
        
        # Generate address twice - should be deterministic
        address1 = await adapter.generate_address(user_id, intent_id)
        address2 = await adapter.generate_address(user_id, intent_id)
        
        assert address1 == address2
        assert address1.startswith("0x")
        assert len(address1) == 42  # Ethereum addresses are 42 chars (0x + 40 hex)
        
        # Different intent should generate different address
        intent_id2 = uuid.uuid4()
        address3 = await adapter.generate_address(user_id, intent_id2)
        assert address1 != address3

    @pytest.mark.asyncio
    async def test_payment_uri_generation(self):
        """Test EIP-681 URI generation"""
        adapter = EVMUSDCAdapter(
            rpc_url="http://localhost:8545",
            usdc_token="0xA0b86a33E6417c7C4b0A9764BB2A0E6D1A42AF5C",
            chain_id=31337,
            min_confirmations=2
        )
        
        address = "0x742d35Cc6634C0532925a3b8D6Ac6dDdf5d6c6e1"
        amount_u = 1000000  # 1 USDC
        
        uri = await adapter.build_payment_uri(address, amount_u, None)
        
        assert uri.startswith("ethereum:")
        assert adapter.usdc_token in uri
        assert str(adapter.chain_id) in uri
        assert address in uri
        assert str(amount_u) in uri

    @pytest.mark.asyncio
    async def test_send_usdc_mock(self):
        """Test USDC sending (mock implementation)"""
        adapter = EVMUSDCAdapter(
            rpc_url="http://localhost:8545",
            usdc_token="0xA0b86a33E6417c7C4b0A9764BB2A0E6D1A42AF5C",
            chain_id=31337,
            min_confirmations=2
        )
        
        to_address = "0x742d35Cc6634C0532925a3b8D6Ac6dDdf5d6c6e1"
        amount_u = 1000000
        
        result = await adapter.send_usdc(to_address, amount_u)
        
        assert result.success is True
        assert result.tx_sig.startswith("0xmock_evm_tx_")

    @pytest.mark.asyncio
    async def test_address_validation(self):
        """Test EVM address validation"""
        adapter = EVMUSDCAdapter(
            rpc_url="http://localhost:8545",
            usdc_token="0xA0b86a33E6417c7C4b0A9764BB2A0E6D1A42AF5C",
            chain_id=31337,
            min_confirmations=2
        )
        
        # Valid mock address
        assert await adapter.is_valid_address("0xmock_evm_address")
        
        # Invalid addresses
        assert not await adapter.is_valid_address("invalid")
        assert not await adapter.is_valid_address("")
        assert not await adapter.is_valid_address("0xinvalid")

    @pytest.mark.asyncio
    async def test_mock_confirmations(self):
        """Test mock confirmation checking"""
        adapter = EVMUSDCAdapter(
            rpc_url="http://localhost:8545",
            usdc_token="0xA0b86a33E6417c7C4b0A9764BB2A0E6D1A42AF5C",
            chain_id=31337,
            min_confirmations=2
        )
        
        # Mock transaction should have enough confirmations
        mock_tx = "0xmock_evm_tx_123"
        confirmations = await adapter.get_confirmations(mock_tx)
        assert confirmations >= adapter.min_confirmations
        
        # Invalid transaction should have 0 confirmations
        confirmations = await adapter.get_confirmations("0xinvalid")
        assert confirmations == 0


class TestAdapterComparison:
    """Test adapter behavior consistency"""
    
    @pytest.mark.asyncio
    async def test_address_uniqueness_across_chains(self):
        """Test that same user/intent generates different addresses on different chains"""
        solana_adapter = SolanaUSDCAdapter(
            rpc_url="http://localhost:8899",
            usdc_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            min_confirmations=1
        )
        
        evm_adapter = EVMUSDCAdapter(
            rpc_url="http://localhost:8545",
            usdc_token="0xA0b86a33E6417c7C4b0A9764BB2A0E6D1A42AF5C",
            chain_id=31337,
            min_confirmations=2
        )
        
        user_id = uuid.uuid4()
        intent_id = uuid.uuid4()
        
        solana_address = await solana_adapter.generate_address(user_id, intent_id)
        evm_address = await evm_adapter.generate_address(user_id, intent_id)
        
        # Addresses should be different (different chains, different formats)
        assert solana_address != evm_address
        assert not solana_address.startswith("0x")
        assert evm_address.startswith("0x")