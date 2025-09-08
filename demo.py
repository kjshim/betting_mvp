#!/usr/bin/env python3
"""
Demonstration script for the Betting MVP
Shows the complete flow from setup to settlement
"""

import asyncio
import datetime
import uuid
from decimal import Decimal

import pytz
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from adapters.chain import MockChainGateway
from adapters.oracle import MockOracle
from domain.models import Base, BetSide, RoundStatus, User
from domain.services import BettingService, LedgerService, RoundScheduler, SettlementService, TvlService
from infra.settings import settings

# Use in-memory SQLite for demo
DEMO_DATABASE_URL = "sqlite:///demo.db"
DEMO_ASYNC_DATABASE_URL = "sqlite+aiosqlite:///demo.db"

def setup_demo_db():
    """Set up demo database"""
    engine = create_engine(DEMO_DATABASE_URL)
    Base.metadata.create_all(engine)
    return engine

async def demo_betting_flow():
    """Demonstrate the complete betting flow"""
    print("🎲 Betting MVP Demo")
    print("=" * 50)
    
    # Setup
    engine = create_async_engine(DEMO_ASYNC_DATABASE_URL)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    
    # Create oracle with demo data
    oracle = MockOracle()
    base_date = datetime.date(2025, 9, 8)
    oracle.set_price(base_date - datetime.timedelta(days=1), Decimal("100.00"))
    oracle.set_price(base_date, Decimal("102.50"))  # UP result
    
    async with SessionLocal() as db:
        # Create services
        ledger = LedgerService(db)
        betting = BettingService(db, ledger)
        settlement = SettlementService(db, ledger, betting)
        scheduler = RoundScheduler(db, oracle, settlement)
        tvl_service = TvlService(db, ledger)
        
        # 1. Create test users
        print("\n1. Creating test users...")
        users = []
        for i in range(3):
            user = User(email=f"demo_user_{i+1}@example.com")
            db.add(user)
            users.append(user)
        
        await db.commit()
        print(f"   ✓ Created {len(users)} users")
        
        # 2. Give users initial deposits
        print("\n2. Processing initial deposits...")
        for i, user in enumerate(users):
            amount = 1000000 * (i + 1)  # 1M, 2M, 3M micro-USDC
            transfer_id = uuid.uuid4()
            ledger.create_entries([
                ("cash", user.id, amount, "deposit", transfer_id),
                ("house", None, -amount, "deposit", transfer_id),  # House provides the funds
            ])
            print(f"   ✓ User {user.email}: {amount/1_000_000:.1f} USDC")
        
        await db.commit()
        
        # 3. Create and open a round
        print("\n3. Creating betting round...")
        code = base_date.strftime("%Y%m%d")
        start_ts = datetime.datetime.combine(base_date, datetime.time.min)
        start_ts = pytz.timezone(settings.timezone).localize(start_ts)
        
        round_obj = scheduler.create_round(code, start_ts)
        await db.commit()
        print(f"   ✓ Round {code} created (ID: {str(round_obj.id)[:8]}...)")
        print(f"   ✓ Lock time: {round_obj.lock_ts}")
        print(f"   ✓ Settle time: {round_obj.settle_ts}")
        
        # 4. Place bets
        print("\n4. Placing bets...")
        bets = []
        
        # User 1: 0.5 USDC on UP
        bet1 = await betting.place_bet(users[0].id, round_obj.id, BetSide.UP, 500000)
        bets.append(bet1)
        print(f"   ✓ {users[0].email}: 0.5 USDC on UP")
        
        # User 2: 1.0 USDC on DOWN  
        bet2 = await betting.place_bet(users[1].id, round_obj.id, BetSide.DOWN, 1000000)
        bets.append(bet2)
        print(f"   ✓ {users[1].email}: 1.0 USDC on DOWN")
        
        # User 3: 1.5 USDC on UP
        bet3 = await betting.place_bet(users[2].id, round_obj.id, BetSide.UP, 1500000)
        bets.append(bet3)
        print(f"   ✓ {users[2].email}: 1.5 USDC on UP")
        
        await db.commit()
        
        # 5. Check pools and TVL
        print("\n5. Current state...")
        up_pool, down_pool = await betting.get_round_pools(round_obj.id)
        tvl_data = await tvl_service.get_tvl()
        
        print(f"   UP Pool:   {up_pool/1_000_000:.1f} USDC")
        print(f"   DOWN Pool: {down_pool/1_000_000:.1f} USDC")
        print(f"   TVL:       {tvl_data['locked_u']/1_000_000:.1f} USDC locked")
        print(f"   Cash:      {tvl_data['total_cash_u']/1_000_000:.1f} USDC total")
        
        # 6. Lock the round
        print("\n6. Locking round...")
        round_obj.status = RoundStatus.LOCKED
        await db.commit()
        print("   ✓ Round locked - no more bets accepted")
        
        # 7. Settle the round automatically
        print("\n7. Settling round...")
        success = await scheduler.settle_round_auto(round_obj.id, base_date)
        
        if success:
            await db.commit()
            await db.refresh(round_obj)
            print(f"   ✓ Round settled with result: {round_obj.result.value}")
            
            # Show results
            print("\n8. Final results...")
            for i, user in enumerate(users):
                final_balance = await ledger.get_balance_async(user.id, "cash")
                await db.refresh(bets[i])
                print(f"   {user.email}:")
                print(f"     Final balance: {final_balance/1_000_000:.2f} USDC")
                print(f"     Bet status: {bets[i].status.value}")
                
                # Calculate P&L
                if i == 0:  # User 1: 0.5 UP
                    initial = 1000000
                    pnl = final_balance - initial
                elif i == 1:  # User 2: 1.0 DOWN  
                    initial = 2000000
                    pnl = final_balance - initial
                else:  # User 3: 1.5 UP
                    initial = 3000000
                    pnl = final_balance - initial
                
                print(f"     P&L: {pnl/1_000_000:+.2f} USDC")
            
            # Final TVL
            final_tvl = await tvl_service.get_tvl()
            print(f"\n   Final TVL: {final_tvl['locked_u']/1_000_000:.1f} USDC locked")
            print(f"   Total Cash: {final_tvl['total_cash_u']/1_000_000:.2f} USDC")
            
        else:
            print("   ✗ Settlement failed")
    
    await engine.dispose()
    print("\n🎉 Demo completed!")

if __name__ == "__main__":
    # Clean setup for demo
    setup_demo_db()
    asyncio.run(demo_betting_flow())