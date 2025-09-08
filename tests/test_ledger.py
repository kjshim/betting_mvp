import uuid
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from domain.services import LedgerService


class TestLedgerService:
    def test_create_entries_valid(self, sync_db, test_user, ledger_service):
        """Test creating valid double-entry ledger entries"""
        ref_id = uuid.uuid4()
        
        entries = [
            ("cash", test_user.id, 1000000, "deposit", ref_id),
            ("fees", None, -1000000, "deposit", ref_id),
        ]
        
        ledger_entries = ledger_service.create_entries(entries)
        sync_db.commit()
        
        assert len(ledger_entries) == 2
        assert all(entry.ref_id == ref_id for entry in ledger_entries)
        
        # Verify balances
        assert ledger_service.get_balance(test_user.id, "cash") == 1000000
        
    def test_create_entries_invalid_sum(self, sync_db, test_user, ledger_service):
        """Test that entries must sum to zero"""
        ref_id = uuid.uuid4()
        
        entries = [
            ("cash", test_user.id, 1000000, "deposit", ref_id),
            ("fees", None, -500000, "deposit", ref_id),  # Doesn't balance
        ]
        
        with pytest.raises(ValueError, match="must sum to zero"):
            ledger_service.create_entries(entries)
    
    def test_get_balance_empty(self, sync_db, test_user, ledger_service):
        """Test balance for user with no transactions"""
        balance = ledger_service.get_balance(test_user.id, "cash")
        assert balance == 0
    
    def test_get_balance_multiple_accounts(self, sync_db, test_user, ledger_service):
        """Test balances across multiple accounts"""
        ref_id = uuid.uuid4()
        
        entries = [
            ("cash", test_user.id, 1000000, "deposit", ref_id),
            ("locked", test_user.id, 500000, "bet", ref_id),
            ("fees", None, -1500000, "misc", ref_id),
        ]
        
        ledger_service.create_entries(entries)
        sync_db.commit()
        
        assert ledger_service.get_balance(test_user.id, "cash") == 1000000
        assert ledger_service.get_balance(test_user.id, "locked") == 500000
    
    @given(st.lists(st.integers(min_value=-1000000, max_value=1000000), min_size=2, max_size=10))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_create_entries_property(self, sync_db, test_user, ledger_service, amounts):
        """Property test: any set of amounts that sum to zero should be valid"""
        # Ensure amounts sum to zero
        total = sum(amounts)
        if total != 0:
            amounts[-1] -= total
        
        ref_id = uuid.uuid4()
        entries = []
        
        for i, amount in enumerate(amounts):
            user_id = test_user.id if i % 2 == 0 else None  # Alternate between user and system accounts
            account = "cash" if user_id else "fees"
            entries.append((account, user_id, amount, "test", ref_id))
        
        # Should not raise an exception
        ledger_entries = ledger_service.create_entries(entries)
        sync_db.commit()
        
        assert len(ledger_entries) == len(amounts)
        
        # Verify total is still zero in database
        total_amount = sum(entry.amount_u for entry in ledger_entries)
        assert total_amount == 0