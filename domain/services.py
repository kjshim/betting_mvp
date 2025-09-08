import hashlib
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple, Union

import pytz
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from adapters.oracle import PriceOracle
from domain.models import (
    Bet,
    BetSide,
    BetStatus,
    LedgerEntry,
    Round,
    RoundResult,
    RoundStatus,
    Transfer,
    TransferStatus,
    TransferType,
    User,
)
from infra.settings import settings


class LedgerService:
    def __init__(self, db: Union[Session, AsyncSession]):
        self.db = db

    def create_entries(
        self, entries: List[Tuple[str, Optional[uuid.UUID], int, str, uuid.UUID]]
    ) -> List[LedgerEntry]:
        """Create multiple ledger entries ensuring double-entry bookkeeping"""
        total = sum(amount for _, _, amount, _, _ in entries)
        if total != 0:
            raise ValueError(f"Ledger entries must sum to zero, got {total}")

        ledger_entries = []
        for account, user_id, amount_u, ref_type, ref_id in entries:
            entry = LedgerEntry(
                account=account,
                user_id=user_id,
                amount_u=amount_u,
                ref_type=ref_type,
                ref_id=ref_id,
            )
            self.db.add(entry)
            ledger_entries.append(entry)

        return ledger_entries

    def get_balance(self, user_id: uuid.UUID, account: str = "cash") -> int:
        """Get user balance for a specific account"""
        result = self.db.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount_u), 0)).where(
                and_(LedgerEntry.user_id == user_id, LedgerEntry.account == account)
            )
        )
        return result.scalar() or 0
        
    async def get_balance_async(self, user_id: uuid.UUID, account: str = "cash") -> int:
        """Get user balance for a specific account (async version)"""
        result = await self.db.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount_u), 0)).where(
                and_(LedgerEntry.user_id == user_id, LedgerEntry.account == account)
            )
        )
        return result.scalar() or 0

    async def get_total_locked(self) -> int:
        """Get total locked funds across all users"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(func.coalesce(func.sum(LedgerEntry.amount_u), 0)).where(
                    LedgerEntry.account == "locked"
                )
            )
            return result.scalar() or 0
        else:
            result = self.db.execute(
                select(func.coalesce(func.sum(LedgerEntry.amount_u), 0)).where(
                    LedgerEntry.account == "locked"
                )
            )
            return result.scalar() or 0


class BettingService:
    def __init__(self, db: Union[Session, AsyncSession], ledger: LedgerService):
        self.db = db
        self.ledger = ledger

    async def place_bet(
        self, user_id: uuid.UUID, round_id: uuid.UUID, side: BetSide, stake_u: int
    ) -> Bet:
        """Place a bet, moving stake from cash to locked"""
        # Check user has sufficient balance
        if isinstance(self.db, AsyncSession):
            balance = await self.ledger.get_balance_async(user_id, "cash")
        else:
            balance = self.ledger.get_balance(user_id, "cash")
        if balance < stake_u:
            raise ValueError(f"Insufficient balance: {balance} < {stake_u}")

        # Get round and verify it's open
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(select(Round).where(Round.id == round_id))
            round_obj = result.scalar_one_or_none()
        else:
            round_obj = self.db.get(Round, round_id)

        if not round_obj:
            raise ValueError("Round not found")
        if round_obj.status != RoundStatus.OPEN:
            raise ValueError(f"Round is not open: {round_obj.status}")

        # Create bet
        bet = Bet(
            round_id=round_id,
            user_id=user_id,
            side=side,
            stake_u=stake_u,
            status=BetStatus.PLACED,
        )
        self.db.add(bet)
        await self.db.flush() if isinstance(self.db, AsyncSession) else self.db.flush()

        # Move funds from cash to locked
        self.ledger.create_entries([
            ("cash", user_id, -stake_u, "bet", bet.id),
            ("locked", user_id, stake_u, "bet", bet.id),
        ])

        return bet

    async def get_round_pools(self, round_id: uuid.UUID) -> Tuple[int, int]:
        """Get UP and DOWN pool totals for a round"""
        if isinstance(self.db, AsyncSession):
            up_result = await self.db.execute(
                select(func.coalesce(func.sum(Bet.stake_u), 0)).where(
                    and_(Bet.round_id == round_id, Bet.side == BetSide.UP)
                )
            )
            down_result = await self.db.execute(
                select(func.coalesce(func.sum(Bet.stake_u), 0)).where(
                    and_(Bet.round_id == round_id, Bet.side == BetSide.DOWN)
                )
            )
            up_pool = up_result.scalar() or 0
            down_pool = down_result.scalar() or 0
        else:
            up_result = self.db.execute(
                select(func.coalesce(func.sum(Bet.stake_u), 0)).where(
                    and_(Bet.round_id == round_id, Bet.side == BetSide.UP)
                )
            )
            down_result = self.db.execute(
                select(func.coalesce(func.sum(Bet.stake_u), 0)).where(
                    and_(Bet.round_id == round_id, Bet.side == BetSide.DOWN)
                )
            )
            up_pool = up_result.scalar() or 0
            down_pool = down_result.scalar() or 0

        return up_pool, down_pool


class SettlementService:
    def __init__(
        self, db: Union[Session, AsyncSession], ledger: LedgerService, betting: BettingService
    ):
        self.db = db
        self.ledger = ledger
        self.betting = betting

    async def settle_round(self, round_id: uuid.UUID, result: RoundResult):
        """Settle a round and distribute payouts"""
        if isinstance(self.db, AsyncSession):
            result_obj = await self.db.execute(select(Round).where(Round.id == round_id))
            round_obj = result_obj.scalar_one_or_none()
        else:
            round_obj = self.db.get(Round, round_id)

        if not round_obj:
            raise ValueError("Round not found")
        if round_obj.status != RoundStatus.LOCKED:
            raise ValueError(f"Round is not locked: {round_obj.status}")

        # Update round
        round_obj.result = result
        round_obj.status = RoundStatus.SETTLED

        # Handle void rounds - refund all bets
        if result == RoundResult.VOID:
            await self._refund_all_bets(round_id)
            return

        # Get all bets for this round
        if isinstance(self.db, AsyncSession):
            bets_result = await self.db.execute(
                select(Bet).where(Bet.round_id == round_id)
            )
            bets = bets_result.scalars().all()
        else:
            bets = self.db.execute(
                select(Bet).where(Bet.round_id == round_id)
            ).scalars().all()

        # Calculate pools
        up_pool, down_pool = await self.betting.get_round_pools(round_id)
        
        # Determine winner and loser pools
        if result == RoundResult.UP:
            winner_side = BetSide.UP
            winner_pool = up_pool
            loser_pool = down_pool
        else:  # DOWN
            winner_side = BetSide.DOWN
            winner_pool = down_pool
            loser_pool = up_pool

        # Calculate fee
        fee_bps = settings.fee_bps
        fee_amount = (loser_pool * fee_bps) // 10000
        distributable_amount = loser_pool - fee_amount

        # Distribute payouts
        ledger_entries = []
        
        # House takes fee
        if fee_amount > 0:
            ledger_entries.append(("house", None, fee_amount, "settlement", round_id))

        for bet in bets:
            if bet.side == winner_side and winner_pool > 0:
                # Winner gets their stake back plus pro-rata share of loser pool
                payout_share = (bet.stake_u * distributable_amount) // winner_pool
                total_payout = bet.stake_u + payout_share
                bet.status = BetStatus.WON
                
                ledger_entries.extend([
                    ("locked", bet.user_id, -bet.stake_u, "settlement", round_id),
                    ("cash", bet.user_id, total_payout, "settlement", round_id),
                ])
            else:
                # Loser loses their stake
                bet.status = BetStatus.LOST
                ledger_entries.append(
                    ("locked", bet.user_id, -bet.stake_u, "settlement", round_id)
                )

        # Balance the ledger (remaining goes to house if any rounding)
        total_out = sum(amount for _, _, amount, _, _ in ledger_entries if amount > 0)
        total_in = sum(-amount for _, _, amount, _, _ in ledger_entries if amount < 0)
        remaining = total_in - total_out
        if remaining > 0:
            ledger_entries.append(("house", None, remaining, "settlement", round_id))

        # Create all ledger entries
        self.ledger.create_entries(ledger_entries)

    async def _refund_all_bets(self, round_id: uuid.UUID):
        """Refund all bets for a void round"""
        if isinstance(self.db, AsyncSession):
            bets_result = await self.db.execute(
                select(Bet).where(Bet.round_id == round_id)
            )
            bets = bets_result.scalars().all()
        else:
            bets = self.db.execute(
                select(Bet).where(Bet.round_id == round_id)
            ).scalars().all()

        ledger_entries = []
        for bet in bets:
            bet.status = BetStatus.REFUNDED
            ledger_entries.extend([
                ("locked", bet.user_id, -bet.stake_u, "refund", round_id),
                ("cash", bet.user_id, bet.stake_u, "refund", round_id),
            ])

        self.ledger.create_entries(ledger_entries)


class RoundScheduler:
    def __init__(self, db: Union[Session, AsyncSession], oracle: PriceOracle, settlement: SettlementService):
        self.db = db
        self.oracle = oracle
        self.settlement = settlement
        self.timezone = pytz.timezone(settings.timezone)

    def create_round(self, code: str, start_ts: datetime) -> Round:
        """Create a new round with commit-reveal scheme"""
        # Calculate lock and settle timestamps
        lock_ts = start_ts.replace(hour=15, minute=59, second=59, microsecond=0)
        settle_ts = start_ts.replace(hour=16, minute=settings.close_fetch_delay_min, second=0, microsecond=0)

        # Create commit hash
        commit_data = {
            "code": code,
            "start_ts": start_ts.isoformat(),
            "fee_bps": settings.fee_bps,
            "seed": uuid.uuid4().hex,
        }
        commit_hash = hashlib.sha256(json.dumps(commit_data, sort_keys=True).encode()).hexdigest()

        round_obj = Round(
            code=code,
            start_ts=start_ts,
            lock_ts=lock_ts,
            settle_ts=settle_ts,
            status=RoundStatus.OPEN,
            commit_hash=commit_hash,
        )
        self.db.add(round_obj)
        return round_obj

    async def settle_round_auto(self, round_id: uuid.UUID, date: datetime.date) -> bool:
        """Automatically settle a round using oracle data"""
        try:
            current_price = await self.oracle.get_official_close(date)
            if current_price is None:
                return False  # Oracle failure

            # Get previous day's price
            prev_date = date - timedelta(days=1)
            prev_price = await self.oracle.get_official_close(prev_date)
            if prev_price is None:
                return False  # Need previous price for comparison

            # Determine result (ties go to DOWN)
            if current_price > prev_price:
                result = RoundResult.UP
            else:
                result = RoundResult.DOWN

            await self.settlement.settle_round(round_id, result)
            
            # Store reveal data
            if isinstance(self.db, AsyncSession):
                round_result = await self.db.execute(select(Round).where(Round.id == round_id))
                round_obj = round_result.scalar_one_or_none()
            else:
                round_obj = self.db.get(Round, round_id)
                
            if round_obj:
                reveal_data = {
                    "date": date.isoformat(),
                    "current_price": str(current_price),
                    "prev_price": str(prev_price),
                    "result": result.value,
                }
                round_obj.reveal = json.dumps(reveal_data)

            return True
            
        except Exception as e:
            # Log error in production
            print(f"Settlement failed: {e}")
            return False


class TvlService:
    def __init__(self, db: Union[Session, AsyncSession], ledger: LedgerService):
        self.db = db
        self.ledger = ledger

    async def get_tvl(self) -> dict:
        """Get Total Value Locked and other metrics"""
        locked_u = await self.ledger.get_total_locked()
        
        # Get total cash across all users
        if isinstance(self.db, AsyncSession):
            cash_result = await self.db.execute(
                select(func.coalesce(func.sum(LedgerEntry.amount_u), 0)).where(
                    LedgerEntry.account == "cash"
                )
            )
            total_cash_u = cash_result.scalar() or 0
            
            # Get pending withdrawals
            withdrawal_result = await self.db.execute(
                select(func.coalesce(func.sum(Transfer.amount_u), 0)).where(
                    and_(Transfer.type == TransferType.WITHDRAWAL, Transfer.status == TransferStatus.PENDING)
                )
            )
            pending_withdrawals_u = withdrawal_result.scalar() or 0
        else:
            cash_result = self.db.execute(
                select(func.coalesce(func.sum(LedgerEntry.amount_u), 0)).where(
                    LedgerEntry.account == "cash"
                )
            )
            total_cash_u = cash_result.scalar() or 0
            
            withdrawal_result = self.db.execute(
                select(func.coalesce(func.sum(Transfer.amount_u), 0)).where(
                    and_(Transfer.type == TransferType.WITHDRAWAL, Transfer.status == TransferStatus.PENDING)
                )
            )
            pending_withdrawals_u = withdrawal_result.scalar() or 0

        return {
            "locked_u": locked_u,
            "total_cash_u": total_cash_u,
            "pending_withdrawals_u": pending_withdrawals_u,
        }