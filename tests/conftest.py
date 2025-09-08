import asyncio
import uuid
from decimal import Decimal
from datetime import datetime, date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from adapters.chain import MockChainGateway
from adapters.oracle import MockOracle
from domain.models import User, Transfer, TransferType, TransferStatus
from domain.services import BettingService, LedgerService, SettlementService, RoundScheduler, TvlService
from infra.db import Base


# Test database URLs
TEST_DATABASE_URL = "sqlite:///./test.db"
TEST_ASYNC_DATABASE_URL = "sqlite+aiosqlite:///./test.db"


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sync_db():
    """Create a sync test database session"""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest_asyncio.fixture
async def async_db():
    """Create an async test database session"""
    engine = create_async_engine(TEST_ASYNC_DATABASE_URL)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()


@pytest.fixture
def test_user(sync_db):
    """Create a test user"""
    user = User(email="test@example.com")
    sync_db.add(user)
    sync_db.commit()
    sync_db.refresh(user)
    return user


@pytest_asyncio.fixture
async def async_test_user(async_db):
    """Create a test user for async tests"""
    user = User(email="test@example.com")
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)
    return user


@pytest.fixture
def ledger_service(sync_db):
    """Create a ledger service"""
    return LedgerService(sync_db)


@pytest_asyncio.fixture
async def async_ledger_service(async_db):
    """Create an async ledger service"""
    return LedgerService(async_db)


@pytest.fixture
def betting_service(sync_db, ledger_service):
    """Create a betting service"""
    return BettingService(sync_db, ledger_service)


@pytest_asyncio.fixture
async def async_betting_service(async_db, async_ledger_service):
    """Create an async betting service"""
    return BettingService(async_db, async_ledger_service)


@pytest.fixture
def mock_oracle():
    """Create a mock oracle with test data"""
    oracle = MockOracle()
    base_date = date(2025, 9, 1)
    
    # Set up some test prices
    oracle.set_price(base_date, Decimal("100.00"))
    oracle.set_price(base_date + timedelta(days=1), Decimal("101.50"))  # UP
    oracle.set_price(base_date + timedelta(days=2), Decimal("99.75"))   # DOWN
    oracle.set_price(base_date + timedelta(days=3), Decimal("99.75"))   # DOWN (tie)
    
    return oracle


@pytest.fixture
def mock_chain_gateway():
    """Create a mock chain gateway"""
    return MockChainGateway()


@pytest.fixture
def settlement_service(sync_db, ledger_service, betting_service):
    """Create a settlement service"""
    return SettlementService(sync_db, ledger_service, betting_service)


@pytest_asyncio.fixture
async def async_settlement_service(async_db, async_ledger_service, async_betting_service):
    """Create an async settlement service"""
    return SettlementService(async_db, async_ledger_service, async_betting_service)


@pytest.fixture
def round_scheduler(sync_db, mock_oracle, settlement_service):
    """Create a round scheduler"""
    return RoundScheduler(sync_db, mock_oracle, settlement_service)


@pytest_asyncio.fixture
async def async_round_scheduler(async_db, mock_oracle, async_settlement_service):
    """Create an async round scheduler"""
    return RoundScheduler(async_db, mock_oracle, async_settlement_service)


@pytest.fixture
def tvl_service(sync_db, ledger_service):
    """Create a TVL service"""
    return TvlService(sync_db, ledger_service)


@pytest_asyncio.fixture
async def async_tvl_service(async_db, async_ledger_service):
    """Create an async TVL service"""
    return TvlService(async_db, async_ledger_service)