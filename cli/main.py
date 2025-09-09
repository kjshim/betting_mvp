import asyncio
import datetime
import uuid
from typing import Optional

import pytz
import typer
from sqlalchemy import select

# from cli.auth import app as auth_app

from adapters.chain import MockChainGateway
from adapters.oracle import MockOracle
from domain.models import (
    BetSide,
    BetStatus,
    Round,
    RoundResult,
    RoundStatus,
    Transfer,
    TransferStatus,
    TransferType,
    User,
)
from domain.services import BettingService, LedgerService, RoundScheduler, SettlementService, TvlService
from infra.db import SessionLocal, get_db
from infra.settings import settings

app = typer.Typer(help="Betting MVP CLI")

# Add auth subcommand
# app.add_typer(auth_app, name="auth", help="API key management")

def get_services(db):
    """Get all services with dependencies"""
    ledger = LedgerService(db)
    betting = BettingService(db, ledger)
    settlement = SettlementService(db, ledger, betting)
    oracle = MockOracle()
    scheduler = RoundScheduler(db, oracle, settlement)
    tvl = TvlService(db, ledger)
    
    return ledger, betting, settlement, scheduler, tvl


@app.command()
def migrate():
    """Run database migrations"""
    import subprocess
    result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if result.returncode == 0:
        typer.echo("✓ Migrations completed successfully")
    else:
        typer.echo(f"✗ Migration failed: {result.stderr}", err=True)
        raise typer.Exit(1)


@app.command()
def seed(users: int = typer.Option(10, help="Number of users to create")):
    """Seed the database with test data"""
    with SessionLocal() as db:
        try:
            created_users = []
            existing_count = 0
            
            for i in range(users):
                email = f"user{i+1}@example.com"
                # Check if user already exists
                existing_user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
                
                if existing_user:
                    created_users.append(existing_user)
                    existing_count += 1
                else:
                    user = User(email=email)
                    db.add(user)
                    created_users.append(user)
            
            db.commit()
            new_users = users - existing_count
            if new_users > 0:
                typer.echo(f"✓ Created {new_users} new test users")
            if existing_count > 0:
                typer.echo(f"✓ Found {existing_count} existing users")
            
            # Give each user some initial balance (if they don't have any)
            ledger = LedgerService(db)
            funded_users = 0
            
            for user in created_users:
                # Check if user already has balance
                current_balance = ledger.get_balance(user.id, "cash")
                
                if current_balance == 0:
                    # Simulate a deposit of 1000 USDC (1,000,000,000 micro USDC)
                    transfer_id = uuid.uuid4()
                    ledger.create_entries([
                        ("cash", user.id, 1_000_000_000, "seed", transfer_id),
                        ("house", None, -1_000_000_000, "seed", transfer_id),  # House provides funds
                    ])
                    funded_users += 1
            
            db.commit()
            if funded_users > 0:
                typer.echo(f"✓ Added initial balances to {funded_users} users (1000 USDC each)")
            else:
                typer.echo(f"✓ All users already have balances")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Seeding failed: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def open_round(code: str = typer.Option(..., help="Round code (YYYYMMDD)")):
    """Open a new round"""
    with SessionLocal() as db:
        try:
            # Parse date from code
            date = datetime.datetime.strptime(code, "%Y%m%d").date()
            tz = pytz.timezone(settings.timezone)
            
            # Start at midnight ET
            start_ts = tz.localize(datetime.datetime.combine(date, datetime.time.min))
            
            _, _, _, scheduler, _ = get_services(db)
            round_obj = scheduler.create_round(code, start_ts)
            db.commit()
            
            typer.echo(f"✓ Created round {code} (ID: {round_obj.id})")
            typer.echo(f"  Start: {start_ts}")
            typer.echo(f"  Lock:  {round_obj.lock_ts}")
            typer.echo(f"  Settle: {round_obj.settle_ts}")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to create round: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def lock_round(code: str = typer.Option(..., help="Round code to lock")):
    """Lock a round (no more bets allowed)"""
    with SessionLocal() as db:
        try:
            result = db.execute(select(Round).where(Round.code == code))
            round_obj = result.scalar_one_or_none()
            
            if not round_obj:
                typer.echo(f"✗ Round {code} not found", err=True)
                raise typer.Exit(1)
            
            if round_obj.status != RoundStatus.OPEN:
                typer.echo(f"✗ Round {code} is not open (status: {round_obj.status})", err=True)
                raise typer.Exit(1)
            
            round_obj.status = RoundStatus.LOCKED
            db.commit()
            
            typer.echo(f"✓ Locked round {code}")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to lock round: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def settle_round(
    code: str = typer.Option(..., help="Round code to settle"),
    result: str = typer.Option("AUTO", help="Result: UP, DOWN, VOID, or AUTO")
):
    """Settle a round with specified or automatic result"""
    with SessionLocal() as db:
        try:
            round_result = db.execute(select(Round).where(Round.code == code))
            round_obj = round_result.scalar_one_or_none()
            
            if not round_obj:
                typer.echo(f"✗ Round {code} not found", err=True)
                raise typer.Exit(1)
            
            if round_obj.status != RoundStatus.LOCKED:
                typer.echo(f"✗ Round {code} is not locked (status: {round_obj.status})", err=True)
                raise typer.Exit(1)
            
            _, _, _, scheduler, _ = get_services(db)
            
            if result == "AUTO":
                # Parse date from code
                date = datetime.datetime.strptime(code, "%Y%m%d").date()
                
                # Run async settlement
                async def settle():
                    success = await scheduler.settle_round_auto(round_obj.id, date)
                    return success
                
                success = asyncio.run(settle())
                if success:
                    db.commit()
                    typer.echo(f"✓ Automatically settled round {code}")
                else:
                    typer.echo(f"✗ Auto settlement failed for round {code}", err=True)
                    raise typer.Exit(1)
            else:
                # Manual result
                if result not in ["UP", "DOWN", "VOID"]:
                    typer.echo(f"✗ Invalid result: {result}. Must be UP, DOWN, VOID, or AUTO", err=True)
                    raise typer.Exit(1)
                
                round_result_enum = RoundResult(result)
                
                async def settle():
                    await scheduler.settlement.settle_round(round_obj.id, round_result_enum)
                
                asyncio.run(settle())
                db.commit()
                typer.echo(f"✓ Manually settled round {code} with result: {result}")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to settle round: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def bet(
    user: str = typer.Option(..., help="User email or ID"),
    side: str = typer.Option(..., help="UP or DOWN"),
    amount: int = typer.Option(..., help="Amount in micro USDC")
):
    """Place a bet for a user"""
    with SessionLocal() as db:
        try:
            # Find user
            if "@" in user:
                user_result = db.execute(select(User).where(User.email == user))
            else:
                user_result = db.execute(select(User).where(User.id == uuid.UUID(user)))
            
            user_obj = user_result.scalar_one_or_none()
            if not user_obj:
                typer.echo(f"✗ User not found: {user}", err=True)
                raise typer.Exit(1)
            
            # Find current open round
            round_result = db.execute(
                select(Round)
                .where(Round.status == RoundStatus.OPEN)
                .order_by(Round.start_ts.desc())
                .limit(1)
            )
            round_obj = round_result.scalar_one_or_none()
            
            if not round_obj:
                typer.echo("✗ No open round available", err=True)
                raise typer.Exit(1)
            
            # Validate side
            if side not in ["UP", "DOWN"]:
                typer.echo(f"✗ Invalid side: {side}. Must be UP or DOWN", err=True)
                raise typer.Exit(1)
            
            bet_side = BetSide(side)
            
            # Place bet
            _, betting, _, _, _ = get_services(db)
            
            async def place():
                return await betting.place_bet(user_obj.id, round_obj.id, bet_side, amount)
            
            bet_obj = asyncio.run(place())
            db.commit()
            
            typer.echo(f"✓ Placed bet for {user_obj.email}")
            typer.echo(f"  Round: {round_obj.code}")
            typer.echo(f"  Side: {side}")
            typer.echo(f"  Amount: {amount:,} micro USDC ({amount/1_000_000:.2f} USDC)")
            typer.echo(f"  Bet ID: {bet_obj.id}")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to place bet: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def deposit(
    user: str = typer.Option(..., help="User email or ID"),
    amount: int = typer.Option(..., help="Amount in micro USDC")
):
    """Create a confirmed deposit for a user (bypasses chain adapter)"""
    with SessionLocal() as db:
        try:
            # Find user
            if "@" in user:
                user_result = db.execute(select(User).where(User.email == user))
            else:
                user_result = db.execute(select(User).where(User.id == uuid.UUID(user)))
            
            user_obj = user_result.scalar_one_or_none()
            if not user_obj:
                typer.echo(f"✗ User not found: {user}", err=True)
                raise typer.Exit(1)
            
            # Create deposit transfer
            transfer = Transfer(
                user_id=user_obj.id,
                type=TransferType.DEPOSIT,
                amount_u=amount,
                status=TransferStatus.CONFIRMED,
                tx_hash=f"0x{uuid.uuid4().hex[:64]}"
            )
            db.add(transfer)
            db.flush()
            
            # Add to ledger
            ledger, _, _, _, _ = get_services(db)
            ledger.create_entries([
                ("cash", user_obj.id, amount, "deposit", transfer.id),
            ])
            
            db.commit()
            
            typer.echo(f"✓ Created deposit for {user_obj.email}")
            typer.echo(f"  Amount: {amount:,} micro USDC ({amount/1_000_000:.2f} USDC)")
            typer.echo(f"  Transfer ID: {transfer.id}")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to create deposit: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def withdraw(
    user: str = typer.Option(..., help="User email or ID"),
    amount: int = typer.Option(..., help="Amount in micro USDC")
):
    """Queue a withdrawal for a user (uses mock chain adapter)"""
    with SessionLocal() as db:
        try:
            # Find user
            if "@" in user:
                user_result = db.execute(select(User).where(User.email == user))
            else:
                user_result = db.execute(select(User).where(User.id == uuid.UUID(user)))
            
            user_obj = user_result.scalar_one_or_none()
            if not user_obj:
                typer.echo(f"✗ User not found: {user}", err=True)
                raise typer.Exit(1)
            
            # Check balance
            ledger, _, _, _, _ = get_services(db)
            
            async def check_balance():
                return await ledger.get_balance(user_obj.id, "cash")
            
            balance = asyncio.run(check_balance())
            
            if balance < amount:
                typer.echo(f"✗ Insufficient balance: {balance:,} < {amount:,}", err=True)
                raise typer.Exit(1)
            
            # Create withdrawal using mock chain adapter
            chain_gateway = MockChainGateway()
            
            async def create():
                return await chain_gateway.create_withdrawal("0x" + "0" * 40, amount)
            
            tx_hash = asyncio.run(create())
            
            # Create transfer record
            transfer = Transfer(
                user_id=user_obj.id,
                type=TransferType.WITHDRAWAL,
                amount_u=amount,
                status=TransferStatus.PENDING,
                tx_hash=tx_hash
            )
            db.add(transfer)
            db.flush()
            
            # Deduct from cash
            ledger.create_entries([
                ("cash", user_obj.id, -amount, "withdrawal", transfer.id),
            ])
            
            db.commit()
            
            typer.echo(f"✓ Queued withdrawal for {user_obj.email}")
            typer.echo(f"  Amount: {amount:,} micro USDC ({amount/1_000_000:.2f} USDC)")
            typer.echo(f"  TX Hash: {tx_hash}")
            typer.echo(f"  Transfer ID: {transfer.id}")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to create withdrawal: {e}", err=True)
            raise typer.Exit(1)


@app.command()
def tvl():
    """Display Total Value Locked and other metrics"""
    with SessionLocal() as db:
        try:
            _, _, _, _, tvl_service = get_services(db)
            
            async def get():
                return await tvl_service.get_tvl()
            
            data = asyncio.run(get())
            
            typer.echo("📊 TVL Metrics:")
            typer.echo(f"  Locked:             {data['locked_u']:,} micro USDC ({data['locked_u']/1_000_000:.2f} USDC)")
            typer.echo(f"  Total Cash:         {data['total_cash_u']:,} micro USDC ({data['total_cash_u']/1_000_000:.2f} USDC)")
            typer.echo(f"  Pending Withdrawals: {data['pending_withdrawals_u']:,} micro USDC ({data['pending_withdrawals_u']/1_000_000:.2f} USDC)")
            
        except Exception as e:
            typer.echo(f"✗ Failed to get TVL: {e}", err=True)
            raise typer.Exit(1)


# On-chain commands
@app.command("user")
def create_user(
    email: str = typer.Option(..., help="User email"),
    password: str = typer.Option(..., help="User password")
):
    """Create a new user with authentication"""
    from auth.service import AuthService
    
    with SessionLocal() as db:
        try:
            auth_service = AuthService(db)
            
            async def create():
                return await auth_service.create_user(email, password)
            
            user = asyncio.run(create())
            db.commit()
            
            typer.echo(f"✓ Created user {email} (ID: {user.id})")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to create user: {e}", err=True)
            raise typer.Exit(1)


@app.command("deposit-intent")
def create_deposit_intent(
    user: str = typer.Option(..., help="User email"),
    min_amount: int = typer.Option(1000000, help="Minimum amount in micro USDC")
):
    """Create deposit intent with address and QR (Solana only)"""
    from onramp.models import ChainType
    from onramp.deposit_intents import DepositIntentService
    from onramp.qr import QRService
    from adapters.onchain.solana_simple import SolanaUSDCAdapterSimple
    
    with SessionLocal() as db:
        try:
            # Find user
            user_result = db.execute(select(User).where(User.email == user))
            user_obj = user_result.scalar_one_or_none()
            
            if not user_obj:
                typer.echo(f"✗ User not found: {user}", err=True)
                raise typer.Exit(1)
            
            # Create Solana gateway
            chain_type = ChainType.SOL
            gateway = SolanaUSDCAdapterSimple(
                rpc_url=settings.solana_rpc_url,
                usdc_mint=settings.solana_usdc_mint,
                min_confirmations=settings.solana_min_conf
            )
            
            # Create intent
            ledger = LedgerService(db)
            intent_service = DepositIntentService(db, ledger)
            
            # Create intent (sync version for CLI)
            intent = intent_service.create_intent_sync(
                user_obj.id, chain_type, gateway, min_amount
            )
            db.commit()
            
            # Generate payment URI and QR
            async def build_uri():
                return await gateway.build_payment_uri(
                    intent.address, min_amount, intent.id
                )
            
            payment_uri = asyncio.run(build_uri())
            qr_code = QRService.generate_qr_code(payment_uri)
            
            typer.echo(f"✓ Created deposit intent for {user}")
            typer.echo(f"  Intent ID: {intent.id}")
            typer.echo(f"  Chain: SOL")
            typer.echo(f"  Address: {intent.address}")
            typer.echo(f"  Min Amount: {min_amount:,} micro USDC")
            typer.echo(f"  Payment URI: {payment_uri}")
            typer.echo(f"  QR Code: [base64 data generated]")
            
        except Exception as e:
            db.rollback()
            typer.echo(f"✗ Failed to create deposit intent: {e}", err=True)
            raise typer.Exit(1)


@app.command("onchain")
def onchain_commands():
    """On-chain operation commands"""
    typer.echo("Available on-chain commands:")
    typer.echo("  faucet - Send test USDC to address")
    typer.echo("  tx-status - Check transaction status")
    typer.echo("  balance - Check address balance")


@app.command("faucet")
def faucet(
    to: str = typer.Option(..., help="Destination address"),
    amount: int = typer.Option(1000000000, help="Amount in micro USDC")
):
    """Send test USDC to Solana address (simulator/testnet only)"""
    typer.echo(f"🚰 Faucet: {amount:,} micro USDC to {to} on Solana")
    typer.echo("  This would send test USDC in a real testnet environment")
    typer.echo(f"  Mock transaction: {uuid.uuid4().hex[:16]}")


@app.command("tx-status")
def tx_status(
    tx: str = typer.Option(..., help="Transaction signature")
):
    """Check Solana transaction status"""
    typer.echo(f"🔍 Checking Solana transaction {tx}")
    typer.echo("  Status: Confirmed")
    typer.echo("  Confirmations: 10")
    typer.echo("  This would query actual Solana RPC in production")


@app.command()
def run_scheduler():
    """Start APScheduler and API (placeholder - would integrate with actual scheduler)"""
    typer.echo("🚀 Starting scheduler and API...")
    typer.echo("This would start the APScheduler and FastAPI server")
    typer.echo("Use 'uvicorn api.main:app' to start the API server manually")


if __name__ == "__main__":
    app()