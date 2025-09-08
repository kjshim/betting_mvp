import datetime
import uuid
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from domain.models import BetSide, BetStatus, RoundResult, RoundStatus, User
from domain.services import BettingService, LedgerService


class TestPayouts:
    def test_payout_calculation_balanced(self, sync_db, round_scheduler, settlement_service):
        """Test payout calculation with balanced pools"""
        # Create round
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=datetime.timezone.utc)
        round_obj = round_scheduler.create_round(code, start_ts)
        round_obj.status = RoundStatus.LOCKED
        
        # Create users
        user_up = User(email="up@example.com")
        user_down = User(email="down@example.com")
        sync_db.add_all([user_up, user_down])
        sync_db.commit()
        
        # Give initial balances
        ledger = LedgerService(sync_db)
        betting = BettingService(sync_db, ledger)
        
        ledger.create_entries([
            ("cash", user_up.id, 2000000, "deposit", round_obj.id),
            ("cash", user_down.id, 2000000, "deposit", round_obj.id),
            ("house", None, -4000000, "deposit", round_obj.id),  # House provides funds
        ])
        sync_db.commit()
        
        # Place bets: 1 USDC UP, 1 USDC DOWN
        bet_up = betting.place_bet(user_up.id, round_obj.id, BetSide.UP, 1000000)
        bet_down = betting.place_bet(user_down.id, round_obj.id, BetSide.DOWN, 1000000)
        sync_db.commit()
        
        # Get initial balances
        initial_up_balance = ledger.get_balance(user_up.id, "cash")
        initial_down_balance = ledger.get_balance(user_down.id, "cash")
        
        # Settle with UP result
        settlement_service.settle_round(round_obj.id, RoundResult.UP)
        sync_db.commit()
        
        # Check final balances
        final_up_balance = ledger.get_balance(user_up.id, "cash")
        final_down_balance = ledger.get_balance(user_down.id, "cash")
        
        # UP winner should get their stake back plus DOWN's stake minus fees
        fee_amount = (1000000 * 100) // 10000  # 1% fee on loser pool
        expected_payout = 1000000 + (1000000 - fee_amount)  # stake + (loser_pool - fee)
        
        assert final_up_balance == initial_up_balance + expected_payout
        assert final_down_balance == initial_down_balance  # DOWN loses their stake
        
        # Verify bet statuses
        sync_db.refresh(bet_up)
        sync_db.refresh(bet_down)
        assert bet_up.status == BetStatus.WON
        assert bet_down.status == BetStatus.LOST
    
    def test_payout_calculation_unbalanced(self, sync_db, round_scheduler, settlement_service):
        """Test payout calculation with unbalanced pools"""
        # Create round
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=datetime.timezone.utc)
        round_obj = round_scheduler.create_round(code, start_ts)
        round_obj.status = RoundStatus.LOCKED
        
        # Create users
        users = [User(email=f"user{i}@example.com") for i in range(4)]
        sync_db.add_all(users)
        sync_db.commit()
        
        ledger = LedgerService(sync_db)
        betting = BettingService(sync_db, ledger)
        
        # Give initial balances
        balance_entries = []
        for user in users:
            balance_entries.append(("cash", user.id, 5000000, "deposit", round_obj.id))
        balance_entries.append(("house", None, -len(users) * 5000000, "deposit", round_obj.id))
        ledger.create_entries(balance_entries)
        sync_db.commit()
        
        # Unbalanced betting: 3 users bet UP (3 USDC total), 1 user bets DOWN (2 USDC)
        bet_up1 = betting.place_bet(users[0].id, round_obj.id, BetSide.UP, 1000000)
        bet_up2 = betting.place_bet(users[1].id, round_obj.id, BetSide.UP, 1000000)
        bet_up3 = betting.place_bet(users[2].id, round_obj.id, BetSide.UP, 1000000)
        bet_down = betting.place_bet(users[3].id, round_obj.id, BetSide.DOWN, 2000000)
        sync_db.commit()
        
        initial_balances = [ledger.get_balance(user.id, "cash") for user in users]
        
        # Settle with UP result (winners)
        settlement_service.settle_round(round_obj.id, RoundResult.UP)
        sync_db.commit()
        
        final_balances = [ledger.get_balance(user.id, "cash") for user in users]
        
        # Calculate expected payouts
        up_pool = 3000000  # 3 USDC
        down_pool = 2000000  # 2 USDC
        fee_amount = (down_pool * 100) // 10000  # 1% fee
        distributable = down_pool - fee_amount
        
        # Each UP bettor gets their stake back plus pro-rata share
        for i in range(3):  # UP bettors
            stake = 1000000
            payout_share = (stake * distributable) // up_pool
            expected_total_payout = stake + payout_share
            
            actual_payout = final_balances[i] - initial_balances[i]
            assert actual_payout == expected_total_payout
        
        # DOWN bettor loses their stake
        assert final_balances[3] == initial_balances[3]
    
    def test_void_round_refunds(self, sync_db, round_scheduler, settlement_service):
        """Test that VOID rounds refund all bets"""
        # Create round
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=datetime.timezone.utc)
        round_obj = round_scheduler.create_round(code, start_ts)
        round_obj.status = RoundStatus.LOCKED
        
        # Create users and place bets
        users = [User(email=f"user{i}@example.com") for i in range(3)]
        sync_db.add_all(users)
        sync_db.commit()
        
        ledger = LedgerService(sync_db)
        betting = BettingService(sync_db, ledger)
        
        # Give balances and place bets
        balance_entries = []
        for user in users:
            balance_entries.append(("cash", user.id, 5000000, "deposit", round_obj.id))
        balance_entries.append(("house", None, -len(users) * 5000000, "deposit", round_obj.id))
        ledger.create_entries(balance_entries)
        sync_db.commit()
        
        initial_balances = [ledger.get_balance(user.id, "cash") for user in users]
        
        bet1 = betting.place_bet(users[0].id, round_obj.id, BetSide.UP, 1000000)
        bet2 = betting.place_bet(users[1].id, round_obj.id, BetSide.UP, 500000)
        bet3 = betting.place_bet(users[2].id, round_obj.id, BetSide.DOWN, 2000000)
        
        after_bet_balances = [ledger.get_balance(user.id, "cash") for user in users]
        sync_db.commit()
        
        # Settle as VOID
        settlement_service.settle_round(round_obj.id, RoundResult.VOID)
        sync_db.commit()
        
        # All users should get their stakes refunded
        final_balances = [ledger.get_balance(user.id, "cash") for user in users]
        
        for i in range(3):
            assert final_balances[i] == initial_balances[i]  # Back to original balance
        
        # Verify bet statuses
        sync_db.refresh(bet1)
        sync_db.refresh(bet2)
        sync_db.refresh(bet3)
        
        assert bet1.status == BetStatus.REFUNDED
        assert bet2.status == BetStatus.REFUNDED
        assert bet3.status == BetStatus.REFUNDED
    
    def test_one_sided_betting(self, sync_db, round_scheduler, settlement_service):
        """Test edge case where all bets are on one side"""
        # Create round
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=datetime.timezone.utc)
        round_obj = round_scheduler.create_round(code, start_ts)
        round_obj.status = RoundStatus.LOCKED
        
        # Create users - all bet UP
        users = [User(email=f"user{i}@example.com") for i in range(3)]
        sync_db.add_all(users)
        sync_db.commit()
        
        ledger = LedgerService(sync_db)
        betting = BettingService(sync_db, ledger)
        
        balance_entries = []
        for user in users:
            balance_entries.append(("cash", user.id, 2000000, "deposit", round_obj.id))
        balance_entries.append(("house", None, -len(users) * 2000000, "deposit", round_obj.id))
        ledger.create_entries(balance_entries)
        sync_db.commit()
        
        initial_balances = [ledger.get_balance(user.id, "cash") for user in users]
        
        # All bet UP
        bets = []
        for user in users:
            bet = betting.place_bet(user.id, round_obj.id, BetSide.UP, 1000000)
            bets.append(bet)
        sync_db.commit()
        
        # UP wins (but there's no DOWN pool to distribute)
        settlement_service.settle_round(round_obj.id, RoundResult.UP)
        sync_db.commit()
        
        # Everyone should just get their stake back (no additional payout)
        final_balances = [ledger.get_balance(user.id, "cash") for user in users]
        
        for i in range(3):
            # They get their stake back (1000000), so balance should be back to initial
            assert final_balances[i] == initial_balances[i]
        
        # All bets should be marked as WON
        for bet in bets:
            sync_db.refresh(bet)
            assert bet.status == BetStatus.WON
    
    @given(
        up_stakes=st.lists(st.integers(min_value=100000, max_value=5000000), min_size=1, max_size=5),
        down_stakes=st.lists(st.integers(min_value=100000, max_value=5000000), min_size=1, max_size=5),
        result=st.sampled_from([RoundResult.UP, RoundResult.DOWN])
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_payout_property_zero_sum(self, sync_db, round_scheduler, settlement_service,
                                      up_stakes, down_stakes, result):
        """Property test: total system should maintain zero-sum after settlement"""
        # Create round
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=datetime.timezone.utc)
        round_obj = round_scheduler.create_round(code, start_ts)
        round_obj.status = RoundStatus.LOCKED
        
        # Create users
        num_users = len(up_stakes) + len(down_stakes)
        users = [User(email=f"user{i}@example.com") for i in range(num_users)]
        sync_db.add_all(users)
        sync_db.commit()
        
        ledger = LedgerService(sync_db)
        betting = BettingService(sync_db, ledger)
        
        # Give generous initial balances
        balance_entries = []
        for user in users:
            balance_entries.append(("cash", user.id, 50000000, "deposit", round_obj.id))
        balance_entries.append(("house", None, -len(users) * 50000000, "deposit", round_obj.id))
        ledger.create_entries(balance_entries)
        sync_db.commit()
        
        # Place bets
        user_idx = 0
        
        # UP bets
        for stake in up_stakes:
            betting.place_bet(users[user_idx].id, round_obj.id, BetSide.UP, stake)
            user_idx += 1
        
        # DOWN bets
        for stake in down_stakes:
            betting.place_bet(users[user_idx].id, round_obj.id, BetSide.DOWN, stake)
            user_idx += 1
        
        sync_db.commit()
        
        # Record total system cash before settlement
        initial_total_cash = sum(ledger.get_balance(user.id, "cash") for user in users)
        initial_total_locked = sum(ledger.get_balance(user.id, "locked") for user in users)
        initial_system_total = initial_total_cash + initial_total_locked
        
        # Settle
        settlement_service.settle_round(round_obj.id, result)
        sync_db.commit()
        
        # Record total system cash after settlement
        final_total_cash = sum(ledger.get_balance(user.id, "cash") for user in users)
        final_total_locked = sum(ledger.get_balance(user.id, "locked") for user in users)
        final_system_total = final_total_cash + final_total_locked
        
        # Locked should be zero after settlement
        assert final_total_locked == 0
        
        # Total user funds should be less than or equal to initial (due to fees going to house)
        assert final_system_total <= initial_system_total
        
        # The difference should be the fee amount
        total_loser_pool = sum(down_stakes) if result == RoundResult.UP else sum(up_stakes)
        expected_fee = (total_loser_pool * 100) // 10000  # 1% fee
        
        assert initial_system_total - final_system_total == expected_fee