# Claude Code Development Notes

This document contains development notes, architectural decisions, and Claude Code specific instructions for the Betting MVP project.

## 🤖 Claude Code Integration

This project was developed using Claude Code with the following considerations:

### Recommended Commands
```bash
# Run linting and type checking
make lint

# Run tests
make test-local

# Format code
make format
```

Claude Code will automatically run these when making changes.

## 🏗️ Architecture Decisions

### Clean Architecture
The project follows clean architecture principles with clear separation of concerns:

- **Adapters Layer** (`adapters/`) - External integrations with mock implementations
- **Domain Layer** (`domain/`) - Pure business logic and models  
- **Infrastructure Layer** (`infra/`) - Database, Redis, configuration
- **API Layer** (`api/`) - HTTP endpoints and request/response handling
- **CLI Layer** (`cli/`) - Command-line interface for operations

### Key Design Patterns

#### 1. Adapter Pattern
```python
# Abstract interface
class PriceOracle(ABC):
    @abstractmethod
    async def get_official_close(self, date: datetime.date) -> Optional[Decimal]:
        pass

# Mock implementation for development/testing
class MockOracle(PriceOracle):
    def __init__(self, fixture_data: Optional[Dict[datetime.date, Decimal]] = None):
        self.fixture_data = fixture_data or {}
```

#### 2. Service Layer Pattern
```python
class LedgerService:
    def create_entries(self, entries: List[Tuple[str, Optional[uuid.UUID], int, str, uuid.UUID]]):
        """Create multiple ledger entries ensuring double-entry bookkeeping"""
        total = sum(amount for _, _, amount, _, _ in entries)
        if total != 0:
            raise ValueError(f"Ledger entries must sum to zero, got {total}")
```

#### 3. Repository Pattern (via SQLAlchemy)
Models are defined as SQLAlchemy entities with business logic in separate service classes.

### Database Design

#### Double-Entry Ledger
```sql
CREATE TABLE ledger_entries (
    id UUID PRIMARY KEY,
    ts TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    account TEXT NOT NULL,          -- 'cash', 'locked', 'fees', 'house'
    user_id UUID REFERENCES users(id),  -- NULL for system accounts
    amount_u BIGINT NOT NULL,       -- Can be positive or negative
    ref_type TEXT NOT NULL,         -- 'deposit', 'bet', 'settlement', etc.
    ref_id UUID NOT NULL            -- Reference to related entity
);
```

#### Money as Integers
All monetary amounts are stored as `BIGINT` representing micro-USDC (10^-6):
- Avoids floating-point precision issues
- Enables precise calculations
- Easy conversion: `amount_usdc = amount_u / 1_000_000`

#### Commit-Reveal Scheme
```python
def create_round(self, code: str, start_ts: datetime) -> Round:
    commit_data = {
        "code": code,
        "start_ts": start_ts.isoformat(),
        "fee_bps": settings.fee_bps,
        "seed": uuid.uuid4().hex,
    }
    commit_hash = hashlib.sha256(json.dumps(commit_data, sort_keys=True).encode()).hexdigest()
```

## 🧪 Testing Strategy

### Test Architecture
```
tests/
├── conftest.py              # Shared fixtures
├── test_ledger.py           # Double-entry accounting tests
├── test_payouts.py          # Payout calculation tests
├── test_round_lifecycle.py  # Round state transitions
└── test_api_integration.py  # API endpoint tests
```

### Key Testing Patterns

#### 1. Property Testing with Hypothesis
```python
@given(
    up_stakes=st.lists(st.integers(min_value=100000, max_value=5000000), min_size=1, max_size=5),
    down_stakes=st.lists(st.integers(min_value=100000, max_value=5000000), min_size=1, max_size=5),
    result=st.sampled_from([RoundResult.UP, RoundResult.DOWN])
)
def test_payout_property_zero_sum(self, sync_db, round_scheduler, settlement_service,
                                  up_stakes, down_stakes, result):
    """Property test: total system should maintain zero-sum after settlement"""
```

#### 2. Time Manipulation
```python
@freeze_time("2025-09-01T16:05:00-04:00")  # Eastern Time
async def test_auto_settlement_success(self, async_db, async_test_user, ...):
```

#### 3. Mock Adapters for Deterministic Tests
```python
# Oracle with fixed price data
oracle = MockOracle()
oracle.set_price(base_date, Decimal("101.50"))  # UP result

# Chain gateway with controlled deposits
chain_gateway = MockChainGateway()
chain_gateway.add_deposit(user_id, 1000000, confirmations=1)
```

### Test Coverage Requirements
- **Ledger operations**: 100% coverage (financial integrity critical)
- **Payout calculations**: Comprehensive property testing
- **API endpoints**: Full request/response validation
- **Round lifecycle**: All state transitions
- **Error conditions**: Exception handling and rollback

## 🔧 Development Guidelines

### Code Style
- **Line length**: 88 characters (Black default)
- **Import ordering**: isort compatible
- **Type hints**: Required for all public APIs
- **Docstrings**: Google style for all classes and functions

### Error Handling
```python
# Business logic errors - specific exceptions
class InsufficientBalanceError(ValueError):
    pass

# Infrastructure errors - let them bubble up
try:
    result = await db.execute(query)
except SQLAlchemyError:
    # Log and re-raise - let higher level handle
    logger.exception("Database query failed")
    raise
```

### Async/Sync Compatibility
Services support both sync and async database sessions:
```python
class LedgerService:
    def __init__(self, db: Union[Session, AsyncSession]):
        self.db = db
    
    def get_balance(self, user_id: uuid.UUID, account: str = "cash") -> int:
        """Sync version for CLI/tests"""
        
    async def get_balance_async(self, user_id: uuid.UUID, account: str = "cash") -> int:
        """Async version for API"""
```

## 📊 Monitoring & Observability

### Structured Logging
```python
import structlog

logger = structlog.get_logger()

logger.info(
    "bet_placed",
    user_id=str(user_id),
    round_id=str(round_id),
    side=side.value,
    stake_u=stake_u,
    round_code=round_code
)
```

### Metrics
Prometheus metrics are exposed at `/metrics`:
- **Counter**: bet_count, deposit_count, withdrawal_count
- **Histogram**: settlement_duration, oracle_response_time
- **Gauge**: tvl_locked, active_users, pending_withdrawals

### Health Checks
```python
@app.get("/health")
async def health():
    # Check database connectivity
    # Check Redis connectivity  
    # Check scheduler status
    return {"status": "healthy", "timestamp": datetime.utcnow()}
```

## 🚀 Deployment Considerations

### Environment Configuration
```python
class Settings(BaseSettings):
    database_url: str
    redis_url: str
    timezone: str = "America/New_York"
    fee_bps: int = Field(default=100, ge=0, le=10000)
    
    class Config:
        env_file = ".env"
```

### Database Migrations
```bash
# Create migration
alembic revision --autogenerate -m "add_new_table"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Scheduler Management
```python
# Graceful shutdown
async def shutdown_scheduler():
    await scheduler_service.stop()
    logger.info("Scheduler stopped gracefully")
```

## 🔒 Security Notes

### Input Validation
All API inputs are validated with Pydantic:
```python
class BetCreate(BaseModel):
    user_id: uuid.UUID
    side: BetSide
    stake_u: int = Field(gt=0, description="Stake in micro USDC")
```

### SQL Injection Prevention
SQLAlchemy ORM with parameterized queries prevents SQL injection:
```python
# Safe - parameterized
result = await db.execute(
    select(User).where(User.email == email)
)

# Avoid - string formatting
# query = f"SELECT * FROM users WHERE email = '{email}'"  # DON'T DO THIS
```

### Secret Management
```python
# Development - .env files
# Production - Environment variables or secret management service

settings = Settings()  # Automatically loads from environment
```

## 🐛 Common Issues & Solutions

### 1. SQLAlchemy Session Management
**Problem**: Session not closed properly
```python
# Wrong
def get_data():
    session = SessionLocal()
    return session.query(User).all()  # Session never closed

# Correct
def get_data():
    with SessionLocal() as session:
        return session.query(User).all()
```

### 2. Async/Await Issues
**Problem**: Mixing sync and async code
```python
# Wrong
def sync_function():
    result = await async_function()  # Can't await in sync function

# Correct
async def async_function():
    result = await other_async_function()

def sync_function():
    result = asyncio.run(async_function())
```

### 3. Time Zone Handling
**Problem**: Inconsistent timezone usage
```python
# Wrong
now = datetime.now()  # Uses local timezone

# Correct
tz = pytz.timezone(settings.timezone)
now = datetime.now(tz)
```

### 4. Test Database State
**Problem**: Tests interfering with each other
```python
# Solution: Use fixtures that clean up
@pytest.fixture
def clean_db():
    # Setup
    yield db
    # Cleanup
    db.rollback()
```

## 📈 Performance Considerations

### Database Optimization
```python
# Use indexes for frequent queries
class Bet(Base):
    __table_args__ = (
        Index("ix_bets_round_user", round_id, user_id),
        Index("ix_bets_status", status),
    )

# Batch operations for large datasets
ledger_entries = [LedgerEntry(...) for entry in entries]
db.add_all(ledger_entries)
```

### Redis Usage
```python
# Use Redis for:
# - Pub/Sub notifications
# - Caching frequently accessed data
# - Session storage (future)
# - Rate limiting counters (future)
```

### Connection Pooling
```python
# SQLAlchemy connection pool configuration
engine = create_engine(
    database_url,
    pool_size=20,          # Connection pool size
    max_overflow=30,       # Additional connections
    pool_pre_ping=True,    # Validate connections
    pool_recycle=3600      # Recycle connections hourly
)
```

## 🔄 Continuous Integration

### Pre-commit Hooks
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    hooks:
      - id: black
  - repo: https://github.com/charliermarsh/ruff-pre-commit
    hooks:
      - id: ruff
  - repo: https://github.com/pre-commit/mirrors-mypy
    hooks:
      - id: mypy
```

### GitHub Actions (Example)
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
      - name: Install dependencies
        run: pip install -r requirements-dev.txt
      - name: Run tests
        run: pytest tests/ --cov=.
      - name: Run linting
        run: make lint
```

## 🎯 Future Enhancements

### Authentication System
```python
# JWT token implementation
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import JWTAuthentication

# Role-based access control
class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    OPERATOR = "operator"
```

### Real Blockchain Integration
```python
class EthereumGateway(ChainGateway):
    def __init__(self, web3_provider: str, usdc_contract: str):
        self.w3 = Web3(Web3.HTTPProvider(web3_provider))
        self.usdc = self.w3.eth.contract(address=usdc_contract, abi=USDC_ABI)
```

### Advanced Analytics
```python
# User behavior tracking
# Risk management
# Fraud detection
# Market making algorithms
```

---

This document should be updated as the system evolves. Key architectural decisions and their rationale should be documented here for future developers.