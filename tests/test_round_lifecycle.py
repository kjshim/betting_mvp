import datetime
import json
from decimal import Decimal

import pytz
from freezegun import freeze_time

from domain.models import RoundStatus, RoundResult, BetSide


class TestRoundLifecycle:
    def test_create_round_commit_reveal(self, sync_db, round_scheduler):
        """Test round creation with commit-reveal scheme"""
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=pytz.UTC)
        
        round_obj = round_scheduler.create_round(code, start_ts)
        sync_db.commit()
        
        # Verify round properties
        assert round_obj.code == code
        assert round_obj.start_ts == start_ts
        assert round_obj.status == RoundStatus.OPEN
        assert round_obj.commit_hash is not None
        assert len(round_obj.commit_hash) == 64  # SHA256 hex
        
        # Verify lock and settle timestamps
        assert round_obj.lock_ts.hour == 15
        assert round_obj.lock_ts.minute == 59
        assert round_obj.lock_ts.second == 59
        
        assert round_obj.settle_ts.hour == 16
        assert round_obj.settle_ts.minute == 5  # CLOSE_FETCH_DELAY_MIN
    
    def test_round_lifecycle_full(self, sync_db, test_user, betting_service, round_scheduler, settlement_service):
        """Test complete round lifecycle: OPEN -> LOCKED -> SETTLED"""
        # Create round
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=pytz.UTC)
        round_obj = round_scheduler.create_round(code, start_ts)
        sync_db.commit()
        
        # Give user initial balance
        ref_id = round_obj.id
        betting_service.ledger.create_entries([
            ("cash", test_user.id, 1000000, "deposit", ref_id),
        ])
        sync_db.commit()
        
        # Place a bet while round is OPEN
        bet = betting_service.place_bet(test_user.id, round_obj.id, BetSide.UP, 100000)
        sync_db.commit()
        
        # Lock the round
        round_obj.status = RoundStatus.LOCKED
        sync_db.commit()
        
        # Settle the round
        settlement_service.settle_round(round_obj.id, RoundResult.UP)
        sync_db.commit()
        
        # Verify final state
        sync_db.refresh(round_obj)
        assert round_obj.status == RoundStatus.SETTLED
        assert round_obj.result == RoundResult.UP
    
    @freeze_time("2025-09-01T16:05:00-04:00")  # Eastern Time
    async def test_auto_settlement_success(self, async_db, async_test_user, async_betting_service, 
                                           async_round_scheduler, mock_oracle):
        """Test successful automatic settlement"""
        # Set up oracle prices
        base_date = datetime.date(2025, 9, 1)
        mock_oracle.set_price(base_date - datetime.timedelta(days=1), Decimal("100.00"))
        mock_oracle.set_price(base_date, Decimal("101.50"))  # UP result
        
        # Create and lock round
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=pytz.UTC)
        round_obj = async_round_scheduler.create_round(code, start_ts)
        round_obj.status = RoundStatus.LOCKED
        await async_db.commit()
        
        # Give user balance and place bet
        betting_service = async_betting_service
        betting_service.ledger.create_entries([
            ("cash", async_test_user.id, 1000000, "deposit", round_obj.id),
        ])
        await async_db.commit()
        
        bet = await betting_service.place_bet(async_test_user.id, round_obj.id, BetSide.UP, 100000)
        await async_db.commit()
        
        # Auto settle
        success = await async_round_scheduler.settle_round_auto(round_obj.id, base_date)
        await async_db.commit()
        
        assert success
        await async_db.refresh(round_obj)
        assert round_obj.status == RoundStatus.SETTLED
        assert round_obj.result == RoundResult.UP
        assert round_obj.reveal is not None
        
        # Verify reveal data
        reveal_data = json.loads(round_obj.reveal)
        assert reveal_data["result"] == "UP"
        assert Decimal(reveal_data["current_price"]) == Decimal("101.50")
        assert Decimal(reveal_data["prev_price"]) == Decimal("100.00")
    
    async def test_auto_settlement_oracle_failure(self, async_db, async_round_scheduler, mock_oracle):
        """Test auto settlement when oracle fails"""
        # Create round
        code = "20250901"
        start_ts = datetime.datetime(2025, 9, 1, tzinfo=pytz.UTC)
        round_obj = async_round_scheduler.create_round(code, start_ts)
        round_obj.status = RoundStatus.LOCKED
        await async_db.commit()
        
        # Simulate oracle failure by not setting any price data
        base_date = datetime.date(2025, 9, 1)
        
        # Auto settle should fail
        success = await async_round_scheduler.settle_round_auto(round_obj.id, base_date)
        
        assert not success
        await async_db.refresh(round_obj)
        assert round_obj.status == RoundStatus.LOCKED  # Should remain locked
        assert round_obj.result is None
    
    def test_tie_goes_to_down(self, sync_db, test_user, betting_service, round_scheduler, 
                               settlement_service, mock_oracle):
        """Test that price ties result in DOWN"""
        # Set up tie condition
        base_date = datetime.date(2025, 9, 3)
        
        # Create round
        code = "20250903"
        start_ts = datetime.datetime(2025, 9, 3, tzinfo=pytz.UTC)
        round_obj = round_scheduler.create_round(code, start_ts)
        round_obj.status = RoundStatus.LOCKED
        sync_db.commit()
        
        # Give users balance and place opposing bets
        user1 = test_user
        from domain.models import User
        user2 = User(email="user2@example.com")
        sync_db.add(user2)
        sync_db.commit()
        
        # Initial balances
        betting_service.ledger.create_entries([
            ("cash", user1.id, 1000000, "deposit", round_obj.id),
            ("cash", user2.id, 1000000, "deposit", round_obj.id),
        ])
        sync_db.commit()
        
        # Place opposing bets
        bet_up = betting_service.place_bet(user1.id, round_obj.id, BetSide.UP, 100000)
        bet_down = betting_service.place_bet(user2.id, round_obj.id, BetSide.DOWN, 100000)
        sync_db.commit()
        
        # Settle - should result in DOWN due to tie
        settlement_service.settle_round(round_obj.id, RoundResult.DOWN)
        sync_db.commit()
        
        # Verify DOWN won
        sync_db.refresh(round_obj)
        assert round_obj.result == RoundResult.DOWN
        
        # Verify bet outcomes
        sync_db.refresh(bet_up)
        sync_db.refresh(bet_down)
        
        from domain.models import BetStatus
        assert bet_up.status == BetStatus.LOST
        assert bet_down.status == BetStatus.WON