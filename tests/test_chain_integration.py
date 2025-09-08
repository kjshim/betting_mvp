"""
Comprehensive chain integration tests.

These tests verify the critical chain operations that handle real money.
Any bugs in chain integration can result in financial losses.
"""

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

import pytest
from hypothesis import given, strategies as st

from adapters.chain import ChainGateway, MockChainGateway
from adapters.oracle import MockOracle, PriceOracle
from domain.models import Transfer, TransferStatus, TransferType
from domain.services import LedgerService


class TestChainGateway:
    """Test the chain gateway interface and mock implementation."""
    
    def test_mock_chain_gateway_deposit_detection(self):
        """Test that deposit detection works correctly."""
        gateway = MockChainGateway()
        user_id = uuid.uuid4()
        
        # Add a deposit
        gateway.add_deposit(user_id, 1000000, confirmations=1)
        
        # Should be detected
        deposits = gateway.get_pending_deposits(min_confirmations=1)
        assert len(deposits) == 1
        assert deposits[0]["user_id"] == user_id
        assert deposits[0]["amount_u"] == 1000000
        assert deposits[0]["confirmations"] >= 1
        
    def test_mock_chain_gateway_confirmation_progression(self):
        """Test that confirmations increase over time."""
        gateway = MockChainGateway()
        user_id = uuid.uuid4()
        
        # Add deposit with 0 confirmations
        gateway.add_deposit(user_id, 1000000, confirmations=0)
        
        # Should not be detected with min_confirmations=1
        deposits = gateway.get_pending_deposits(min_confirmations=1)
        assert len(deposits) == 0
        
        # Simulate block mining
        gateway.mine_blocks(3)
        
        # Should now be detected
        deposits = gateway.get_pending_deposits(min_confirmations=1)
        assert len(deposits) == 1
        assert deposits[0]["confirmations"] >= 1
        
    @pytest.mark.asyncio
    async def test_mock_chain_gateway_withdrawal_creation(self):
        """Test withdrawal transaction creation."""
        gateway = MockChainGateway()
        
        tx_hash = await gateway.create_withdrawal("0x" + "1" * 40, 500000)
        
        # Should return a valid transaction hash
        assert tx_hash.startswith("0x")
        assert len(tx_hash) == 66  # 0x + 64 hex characters
        
        # Should be tracked internally
        withdrawals = gateway.get_pending_withdrawals()
        assert len(withdrawals) == 1
        assert withdrawals[0]["tx_hash"] == tx_hash
        assert withdrawals[0]["amount_u"] == 500000
        
    @pytest.mark.asyncio
    async def test_withdrawal_confirmation_monitoring(self):
        """Test withdrawal confirmation monitoring."""
        gateway = MockChainGateway()
        
        tx_hash = await gateway.create_withdrawal("0x" + "1" * 40, 500000)
        
        # Initially unconfirmed
        status = gateway.get_transaction_status(tx_hash)
        assert status["confirmed"] is False
        assert status["confirmations"] == 0
        
        # Mine blocks to confirm
        gateway.mine_blocks(6)
        
        status = gateway.get_transaction_status(tx_hash)
        assert status["confirmed"] is True
        assert status["confirmations"] >= 6
        
    def test_deposit_deduplication(self):
        """Test that duplicate deposits are handled correctly."""
        gateway = MockChainGateway()
        user_id = uuid.uuid4()
        
        # Add same deposit twice
        tx_hash = "0x" + "a" * 64
        gateway.add_deposit(user_id, 1000000, confirmations=1, tx_hash=tx_hash)
        gateway.add_deposit(user_id, 1000000, confirmations=2, tx_hash=tx_hash)
        
        deposits = gateway.get_pending_deposits(min_confirmations=1)
        assert len(deposits) == 1  # Should not duplicate
        
    @pytest.mark.asyncio
    async def test_chain_gateway_error_handling(self):
        """Test error handling in chain operations."""
        gateway = MockChainGateway()
        
        # Test invalid address
        with pytest.raises(ValueError, match="Invalid address"):
            await gateway.create_withdrawal("invalid_address", 100000)
            
        # Test zero amount
        with pytest.raises(ValueError, match="Amount must be positive"):
            await gateway.create_withdrawal("0x" + "1" * 40, 0)
            
    @pytest.mark.asyncio
    async def test_chain_gateway_gas_estimation(self):
        """Test gas fee estimation."""
        gateway = MockChainGateway()
        
        gas_estimate = await gateway.estimate_withdrawal_gas("0x" + "1" * 40, 100000)
        
        assert gas_estimate > 0
        assert gas_estimate < 1000000  # Reasonable gas limit
        
    @given(
        amount_u=st.integers(min_value=1, max_value=1_000_000_000_000)
    )
    @pytest.mark.asyncio
    async def test_withdrawal_amount_property(self, amount_u):
        """Property test: withdrawal amounts should be preserved exactly."""
        gateway = MockChainGateway()
        address = "0x" + "1" * 40
        
        tx_hash = await gateway.create_withdrawal(address, amount_u)
        
        withdrawals = gateway.get_pending_withdrawals()
        withdrawal = next(w for w in withdrawals if w["tx_hash"] == tx_hash)
        
        assert withdrawal["amount_u"] == amount_u


class TestPriceOracle:
    """Test price oracle functionality."""
    
    @pytest.mark.asyncio
    async def test_mock_oracle_basic_functionality(self):
        """Test basic oracle price retrieval."""
        oracle = MockOracle()
        from datetime import date
        
        test_date = date(2025, 9, 8)
        price = await oracle.get_official_close(test_date)
        
        # Mock should return a reasonable price
        assert price is not None
        assert price > Decimal("0")
        assert price < Decimal("10000")  # Reasonable upper bound
        
    def test_mock_oracle_with_fixture_data(self):
        """Test oracle with predefined fixture data."""
        from datetime import date
        
        fixture_data = {
            date(2025, 9, 8): Decimal("150.25"),
            date(2025, 9, 9): Decimal("149.75"),
        }
        
        oracle = MockOracle(fixture_data)
        
        # Should return exact fixture values
        assert asyncio.run(oracle.get_official_close(date(2025, 9, 8))) == Decimal("150.25")
        assert asyncio.run(oracle.get_official_close(date(2025, 9, 9))) == Decimal("149.75")
        
        # Should generate random for unknown dates
        unknown_price = asyncio.run(oracle.get_official_close(date(2025, 9, 10)))
        assert unknown_price is not None
        assert unknown_price != Decimal("150.25")
        
    @pytest.mark.asyncio
    async def test_oracle_price_consistency(self):
        """Test that oracle returns consistent prices for the same date."""
        oracle = MockOracle()
        from datetime import date
        
        test_date = date(2025, 9, 8)
        
        price1 = await oracle.get_official_close(test_date)
        price2 = await oracle.get_official_close(test_date)
        
        # Should return same price for same date
        assert price1 == price2
        
    @pytest.mark.asyncio
    async def test_oracle_future_date_handling(self):
        """Test oracle behavior with future dates."""
        oracle = MockOracle()
        from datetime import date, timedelta
        
        future_date = date.today() + timedelta(days=30)
        price = await oracle.get_official_close(future_date)
        
        # Should handle gracefully (either None or reasonable price)
        if price is not None:
            assert price > Decimal("0")
            assert price < Decimal("10000")
            
    @pytest.mark.asyncio
    async def test_oracle_error_handling(self):
        """Test oracle error handling."""
        oracle = MockOracle()
        
        # Test with invalid date types
        with pytest.raises(TypeError):
            await oracle.get_official_close("2025-09-08")
            
    @given(
        days_back=st.integers(min_value=1, max_value=365)
    )
    @pytest.mark.asyncio
    async def test_oracle_historical_price_property(self, days_back):
        """Property test: historical prices should be consistent."""
        oracle = MockOracle()
        from datetime import date, timedelta
        
        test_date = date.today() - timedelta(days=days_back)
        
        price1 = await oracle.get_official_close(test_date)
        price2 = await oracle.get_official_close(test_date)
        
        # Same date should return same price
        assert price1 == price2
        
        if price1 is not None:
            assert price1 > Decimal("0")


class TestChainIntegrationFlow:
    """Test end-to-end chain integration flows."""
    
    @pytest.mark.asyncio
    async def test_deposit_flow_integration(self, async_db, async_test_user):
        """Test complete deposit flow from chain to ledger."""
        gateway = MockChainGateway()
        ledger = LedgerService(async_db)
        
        user_id = async_test_user.id
        amount_u = 1000000  # 1 USDC
        
        # Simulate blockchain deposit
        gateway.add_deposit(user_id, amount_u, confirmations=6)
        
        # Process pending deposits
        deposits = gateway.get_pending_deposits(min_confirmations=6)
        assert len(deposits) == 1
        
        deposit = deposits[0]
        
        # Create transfer record
        transfer = Transfer(
            user_id=user_id,
            type=TransferType.DEPOSIT,
            amount_u=amount_u,
            status=TransferStatus.CONFIRMED,
            tx_hash=deposit["tx_hash"]
        )
        async_db.add(transfer)
        await async_db.flush()
        
        # Update ledger
        ledger.create_entries([
            ("cash", user_id, amount_u, "deposit", transfer.id),
            ("house", None, -amount_u, "deposit", transfer.id),
        ])
        
        await async_db.commit()
        
        # Verify ledger balance
        balance = await ledger.get_balance_async(user_id, "cash")
        assert balance == amount_u
        
        # Verify transfer record
        await async_db.refresh(transfer)
        assert transfer.status == TransferStatus.CONFIRMED
        
    @pytest.mark.asyncio
    async def test_withdrawal_flow_integration(self, async_db, async_test_user):
        """Test complete withdrawal flow from ledger to chain."""
        gateway = MockChainGateway()
        ledger = LedgerService(async_db)
        
        user_id = async_test_user.id
        amount_u = 500000  # 0.5 USDC
        
        # Give user initial balance
        deposit_transfer_id = uuid.uuid4()
        ledger.create_entries([
            ("cash", user_id, amount_u, "test_deposit", deposit_transfer_id),
            ("house", None, -amount_u, "test_deposit", deposit_transfer_id),
        ])
        await async_db.commit()
        
        # Verify initial balance
        initial_balance = await ledger.get_balance_async(user_id, "cash")
        assert initial_balance == amount_u
        
        # Create withdrawal
        address = "0x" + "1" * 40
        tx_hash = await gateway.create_withdrawal(address, amount_u)
        
        # Create transfer record
        transfer = Transfer(
            user_id=user_id,
            type=TransferType.WITHDRAWAL,
            amount_u=amount_u,
            status=TransferStatus.PENDING,
            tx_hash=tx_hash
        )
        async_db.add(transfer)
        await async_db.flush()
        
        # Update ledger
        ledger.create_entries([
            ("cash", user_id, -amount_u, "withdrawal", transfer.id),
            ("house", None, amount_u, "withdrawal", transfer.id),
        ])
        
        await async_db.commit()
        
        # Verify ledger balance decreased
        final_balance = await ledger.get_balance_async(user_id, "cash")
        assert final_balance == 0
        
        # Verify withdrawal is tracked on chain
        withdrawals = gateway.get_pending_withdrawals()
        withdrawal = next(w for w in withdrawals if w["tx_hash"] == tx_hash)
        assert withdrawal["amount_u"] == amount_u
        
        # Simulate confirmation
        gateway.mine_blocks(6)
        status = gateway.get_transaction_status(tx_hash)
        assert status["confirmed"] is True
        
        # Update transfer status
        transfer.status = TransferStatus.CONFIRMED
        await async_db.commit()
        
    @pytest.mark.asyncio
    async def test_deposit_reconciliation(self, async_db):
        """Test deposit reconciliation process."""
        gateway = MockChainGateway()
        
        # Add multiple deposits for different users
        user1 = uuid.uuid4()
        user2 = uuid.uuid4()
        
        gateway.add_deposit(user1, 1000000, confirmations=6, tx_hash="0x" + "a" * 64)
        gateway.add_deposit(user2, 2000000, confirmations=6, tx_hash="0x" + "b" * 64)
        gateway.add_deposit(user1, 500000, confirmations=3, tx_hash="0x" + "c" * 64)  # Not confirmed yet
        
        # Get confirmed deposits
        confirmed_deposits = gateway.get_pending_deposits(min_confirmations=6)
        assert len(confirmed_deposits) == 2
        
        total_confirmed = sum(d["amount_u"] for d in confirmed_deposits)
        assert total_confirmed == 3000000
        
        # Get all deposits including unconfirmed
        all_deposits = gateway.get_pending_deposits(min_confirmations=1)
        assert len(all_deposits) == 3
        
    @pytest.mark.asyncio
    async def test_withdrawal_reconciliation(self, async_db):
        """Test withdrawal reconciliation process."""
        gateway = MockChainGateway()
        
        # Create multiple withdrawals
        tx1 = await gateway.create_withdrawal("0x" + "1" * 40, 1000000)
        tx2 = await gateway.create_withdrawal("0x" + "2" * 40, 2000000)
        tx3 = await gateway.create_withdrawal("0x" + "3" * 40, 500000)
        
        # Initially all pending
        withdrawals = gateway.get_pending_withdrawals()
        assert len(withdrawals) == 3
        
        # Confirm some
        gateway.mine_blocks(6)
        
        confirmed_withdrawals = [
            w for w in gateway.get_pending_withdrawals()
            if gateway.get_transaction_status(w["tx_hash"])["confirmed"]
        ]
        
        assert len(confirmed_withdrawals) == 3  # All should be confirmed
        
        total_confirmed = sum(w["amount_u"] for w in confirmed_withdrawals)
        assert total_confirmed == 3500000
        
    @pytest.mark.asyncio
    async def test_chain_reorg_handling(self):
        """Test handling of blockchain reorganizations."""
        gateway = MockChainGateway()
        user_id = uuid.uuid4()
        
        # Add deposit
        gateway.add_deposit(user_id, 1000000, confirmations=6)
        
        # Simulate reorg that reduces confirmations
        deposits = gateway.get_pending_deposits(min_confirmations=1)
        deposit = deposits[0]
        tx_hash = deposit["tx_hash"]
        
        # Simulate reorg (reset confirmations)
        gateway.simulate_reorg([tx_hash], new_confirmations=2)
        
        # Should still be visible with lower confirmation requirement
        deposits_low_conf = gateway.get_pending_deposits(min_confirmations=1)
        assert len(deposits_low_conf) == 1
        
        # Should not be visible with higher confirmation requirement
        deposits_high_conf = gateway.get_pending_deposits(min_confirmations=6)
        assert len(deposits_high_conf) == 0
        
    @given(
        deposit_amount=st.integers(min_value=1, max_value=1_000_000_000),
        withdrawal_amount=st.integers(min_value=1, max_value=1_000_000_000)
    )
    def test_deposit_withdrawal_amounts_property(self, deposit_amount, withdrawal_amount):
        """Property test: deposit and withdrawal amounts should be preserved in gateway."""
        gateway = MockChainGateway()
        user_id = uuid.uuid4()
        
        # Only test valid withdrawal amounts (not more than deposit) 
        if withdrawal_amount > deposit_amount:
            withdrawal_amount = deposit_amount
        
        # Test deposit preservation
        gateway.add_deposit(user_id, deposit_amount, confirmations=6)
        deposits = gateway.get_pending_deposits(min_confirmations=6)
        
        assert len(deposits) == 1
        assert deposits[0]["amount_u"] == deposit_amount
        assert deposits[0]["user_id"] == user_id
        
        # Test withdrawal amount preservation
        if withdrawal_amount > 0:
            import asyncio
            tx_hash = asyncio.run(gateway.create_withdrawal("0x" + "1" * 40, withdrawal_amount))
            withdrawals = gateway.get_pending_withdrawals()
            
            withdrawal = next(w for w in withdrawals if w["tx_hash"] == tx_hash)
            assert withdrawal["amount_u"] == withdrawal_amount


class TestChainGatewayInterface:
    """Test that any ChainGateway implementation follows the interface contract."""
    
    @pytest.mark.asyncio
    async def test_chain_gateway_interface_contract(self):
        """Test that ChainGateway implementations follow the interface contract."""
        gateway = MockChainGateway()
        
        # Test create_withdrawal interface
        tx_hash = await gateway.create_withdrawal("0x" + "1" * 40, 1000000)
        assert isinstance(tx_hash, str)
        assert tx_hash.startswith("0x")
        assert len(tx_hash) == 66
        
        # Test get_pending_deposits interface
        user_id = uuid.uuid4()
        gateway.add_deposit(user_id, 1000000, confirmations=6)
        deposits = gateway.get_pending_deposits(min_confirmations=1)
        
        assert isinstance(deposits, list)
        if deposits:
            deposit = deposits[0]
            assert "user_id" in deposit
            assert "amount_u" in deposit
            assert "tx_hash" in deposit
            assert "confirmations" in deposit
            assert isinstance(deposit["user_id"], uuid.UUID)
            assert isinstance(deposit["amount_u"], int)
            assert isinstance(deposit["tx_hash"], str)
            assert isinstance(deposit["confirmations"], int)
            
        # Test get_transaction_status interface
        status = gateway.get_transaction_status(tx_hash)
        assert isinstance(status, dict)
        assert "confirmed" in status
        assert "confirmations" in status
        assert isinstance(status["confirmed"], bool)
        assert isinstance(status["confirmations"], int)
        
    @pytest.mark.asyncio
    async def test_oracle_interface_contract(self):
        """Test that PriceOracle implementations follow the interface contract."""
        oracle = MockOracle()
        from datetime import date
        
        price = await oracle.get_official_close(date.today())
        
        # Should return Decimal or None
        assert price is None or isinstance(price, Decimal)
        
        if price is not None:
            # Price should be positive
            assert price > Decimal("0")


class TestChainErrorScenarios:
    """Test error scenarios in chain integration."""
    
    @pytest.mark.asyncio
    async def test_network_failure_simulation(self):
        """Test handling of network failures."""
        gateway = MockChainGateway()
        
        # Simulate network failure
        gateway.simulate_network_failure(True)
        
        with pytest.raises(Exception):  # Should raise network-related exception
            await gateway.create_withdrawal("0x" + "1" * 40, 1000000)
            
        # Restore network
        gateway.simulate_network_failure(False)
        
        # Should work again
        tx_hash = await gateway.create_withdrawal("0x" + "1" * 40, 1000000)
        assert tx_hash.startswith("0x")
        
    @pytest.mark.asyncio
    async def test_insufficient_gas_simulation(self):
        """Test handling of insufficient gas scenarios."""
        gateway = MockChainGateway()
        
        # Simulate high gas prices
        gateway.simulate_high_gas_prices(True)
        
        # Should either succeed with warning or fail gracefully
        try:
            tx_hash = await gateway.create_withdrawal("0x" + "1" * 40, 1000000)
            assert tx_hash.startswith("0x")
        except Exception as e:
            # Should be a specific gas-related error
            assert "gas" in str(e).lower() or "fee" in str(e).lower()
            
    def test_address_validation_edge_cases(self):
        """Test address validation with edge cases."""
        gateway = MockChainGateway()
        
        invalid_addresses = [
            "",  # Empty
            "0x",  # Too short
            "0x" + "g" * 40,  # Invalid hex
            "0X" + "1" * 40,  # Wrong case prefix
            "1" * 42,  # Missing 0x
            "0x" + "1" * 39,  # Too short
            "0x" + "1" * 41,  # Too long
        ]
        
        for addr in invalid_addresses:
            with pytest.raises(ValueError):
                asyncio.run(gateway.create_withdrawal(addr, 1000000))
                
        # Valid addresses should work
        valid_addresses = [
            "0x" + "0" * 40,
            "0x" + "1" * 40,
            "0x" + "f" * 40,
            "0x" + "A" * 40,  # Mixed case should work
        ]
        
        for addr in valid_addresses:
            try:
                tx_hash = asyncio.run(gateway.create_withdrawal(addr, 1000000))
                assert tx_hash.startswith("0x")
            except Exception as e:
                pytest.fail(f"Valid address {addr} should not raise exception: {e}")


# Performance and load testing
class TestChainPerformance:
    """Test chain integration performance characteristics."""
    
    @pytest.mark.asyncio
    async def test_concurrent_withdrawals(self):
        """Test handling of concurrent withdrawal requests."""
        gateway = MockChainGateway()
        
        # Create many concurrent withdrawals
        tasks = []
        for i in range(100):
            address = f"0x{i:040d}"  # Generate unique addresses
            task = gateway.create_withdrawal(address, 1000000 + i)
            tasks.append(task)
            
        # Execute concurrently
        tx_hashes = await asyncio.gather(*tasks)
        
        # All should succeed and be unique
        assert len(tx_hashes) == 100
        assert len(set(tx_hashes)) == 100  # All unique
        
        # All should be valid transaction hashes
        for tx_hash in tx_hashes:
            assert tx_hash.startswith("0x")
            assert len(tx_hash) == 66
            
    def test_large_batch_deposit_processing(self):
        """Test processing large batches of deposits."""
        gateway = MockChainGateway()
        
        # Add large number of deposits
        user_ids = [uuid.uuid4() for _ in range(1000)]
        for i, user_id in enumerate(user_ids):
            gateway.add_deposit(user_id, 1000000 + i, confirmations=6)
            
        # Should be able to retrieve all efficiently
        deposits = gateway.get_pending_deposits(min_confirmations=6)
        assert len(deposits) == 1000
        
        # Verify amounts are correct
        amounts = [d["amount_u"] for d in deposits]
        expected_amounts = [1000000 + i for i in range(1000)]
        assert sorted(amounts) == sorted(expected_amounts)