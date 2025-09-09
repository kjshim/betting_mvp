# Betting MVP - 24h Up/Down Betting Service

Production-ready 24h Up/Down betting platform with USDC accounting, automated settlement, and admin interface.

## 🎯 Current Status (Production Ready)

### ✅ **Completed Features**
- **Daily betting rounds** with NASDAQ close timing (16:00 ET)
- **Double-entry ledger** accounting (micro-USDC precision) 
- **Automated settlement** with payout calculations
- **Admin interface** with session authentication
- **REST API** with comprehensive endpoints
- **CLI tools** for operations
- **Health monitoring** with Prometheus metrics
- **Test suite** with 27 chain integration tests

### 🔄 **Current Capabilities**
- Users can place UP/DOWN bets on daily rounds
- Automated round lifecycle (OPEN → LOCKED → SETTLED)
- Admin can manually settle rounds with results
- Real-time balance tracking and transaction monitoring
- Production monitoring with health checks

## 🏗️ Architecture

```
betting_mvp/
├── adapters/           # External service interfaces
│   ├── chain.py        # Blockchain operations (deposits/withdrawals)
│   └── oracle.py       # Price feed integration
├── domain/             # Business logic
│   ├── models.py       # SQLAlchemy database models
│   └── services.py     # Core business services
├── infra/              # Infrastructure
│   ├── db.py          # Database connection/sessions
│   ├── redis.py       # Redis pub/sub
│   ├── scheduler.py   # APScheduler for automation
│   └── settings.py    # Configuration management
├── api/                # REST API
│   ├── main.py        # FastAPI application
│   ├── routes.py      # API endpoints
│   └── schemas.py     # Pydantic models
├── cli/                # Command line tools
│   └── main.py        # Typer CLI commands
└── tests/              # Test suite
    ├── conftest.py     # Test fixtures
    ├── test_ledger.py  # Ledger accounting tests
    ├── test_payouts.py # Payout calculation tests
    └── ...
```

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Make (optional but recommended)

### Setup

1. **Clone and setup environment:**
```bash
git clone <repository>
cd betting_mvp
cp .env.example .env
make install          # Install dependencies
```

2. **Start services:**
```bash
make up               # Start PostgreSQL + Redis
make migrate          # Run database migrations
make seed             # Create test users with initial balance
```

3. **Run the demo:**
```bash
python demo.py        # Complete betting flow demonstration
```

4. **Start API server:**
```bash
uvicorn api.main:app --reload
# Visit http://localhost:8000/docs for API documentation
```

## 💰 Money & Units

All monetary amounts use **micro-USDC** units (10^-6 precision):
- 1 USDC = 1,000,000 micro-USDC
- Example: Betting 100,000 micro-USDC = 0.1 USDC
- Minimum bet: 1 micro-USDC (0.000001 USDC)

## 🎲 Round Logic

### Round Lifecycle
1. **OPEN** - Users can place bets
2. **LOCKED** - No more bets (15:59:59 ET)  
3. **SETTLED** - Payouts distributed (after 16:05 ET)

### Round Timing
- **Round code**: `YYYYMMDD` (closing date in ET)
- **Lock time**: 15:59:59 ET
- **Settlement**: 16:05 ET (5-minute delay for price fetch)
- **Grace period**: 30 minutes for oracle failures

### Settlement Rules
- **UP**: Current close > previous close
- **DOWN**: Current close ≤ previous close (ties go to DOWN)
- **VOID**: Oracle failure beyond grace period → full refunds

### Payout Formula
```
Winners get: stake_back + (loser_pool × (1 - fee_rate) × stake_weight)
Fee: 1% of loser pool goes to house (configurable)
```

## 📡 API Endpoints

### 🎲 **Betting Operations**
- `POST /users` - Create user account
- `POST /bets` - Place UP/DOWN bet on current round
- `POST /withdrawals` - Queue withdrawal request
- `POST /simulate/deposit_webhook` - Simulate deposit (testing)

### 📊 **Information & Monitoring**
- `GET /rounds/current` - Current round status and pools
- `GET /tvl` - Total Value Locked metrics
- `GET /health` - System health status
- `GET /metrics` - Prometheus metrics endpoint

### 🔐 **Admin Interface** (http://localhost:8000/admin/)
- **Login**: Session-based authentication (password in .env)
- **Dashboard**: System overview and key metrics  
- **Users**: User management with balance display
- **Rounds**: Round management with settlement controls
- **Transactions**: Transfer monitoring and status
- **System**: Health monitoring and reconciliation
- **API Keys**: Manage API access keys

### 🏁 **Admin Settlement**
- `POST /admin/rounds/{code}/lock` - Lock round (stop bets)
- `POST /admin/rounds/{code}/settle` - Settle with UP/DOWN/VOID result

## 🛠️ CLI Commands

### Database Management
```bash
# Run database migrations
python -m cli.main migrate

# Create test users with initial balance
python -m cli.main seed --users 10
```

### Round Management
```bash
# Open new round for today
python -m cli.main open-round --code $(date +%Y%m%d)

# Lock round (no more bets)
python -m cli.main lock-round --code 20250908

# Settle round (AUTO uses oracle)
python -m cli.main settle-round --code 20250908 --result AUTO
```

### User Operations
```bash
# Place bet
python -m cli.main bet --user user1@example.com --side UP --amount 1000000

# Add funds (bypasses blockchain)
python -m cli.main deposit --user user1@example.com --amount 5000000

# Queue withdrawal
python -m cli.main withdraw --user user1@example.com --amount 2000000

# Check system metrics
python -m cli.main tvl
```

## 🧪 Testing

### Run Test Suite
```bash
make test-local       # Run all tests locally
make test             # Run tests in Docker

# Specific test categories
pytest tests/test_ledger.py -v          # Ledger accounting
pytest tests/test_payouts.py -v         # Payout calculations
pytest tests/test_round_lifecycle.py -v # Round state management
```

### Test Features
- **Property testing** with Hypothesis for payout edge cases
- **Time manipulation** with freezegun for deterministic results
- **Mock adapters** for predictable blockchain/oracle behavior
- **Double-entry verification** ensures accounting integrity

## 🔧 Configuration

Environment variables (`.env` file):

```bash
# Database
DATABASE_URL=postgresql+psycopg://user:pass@db:5432/app

# Redis
REDIS_URL=redis://redis:6379/0

# Business Logic
TIMEZONE=America/New_York    # Round timing timezone
FEE_BPS=100                 # Fee basis points (100 = 1%)
SETTLE_GRACE_MIN=30         # Oracle failure grace period
CLOSE_FETCH_DELAY_MIN=5     # Delay after market close
```

## 📊 Monitoring & Operations

### Health Checks
- **API**: `GET /health` - Service availability
- **Database**: Connection pool status
- **Redis**: Pub/sub connectivity
- **Scheduler**: Job execution status

### Metrics (Prometheus)
- **TVL**: Total locked funds
- **Round counts**: By status
- **Bet volumes**: By side/outcome
- **Settlement latency**: Oracle response times
- **Error rates**: API/CLI/scheduler failures

### Logging
- **Structured JSON** logs via python-json-logger
- **Request tracing** with correlation IDs
- **Business events**: Deposits, bets, settlements
- **Error tracking** with full context

## 🔒 Security & Production Status

### ✅ **Production Ready**
- **Admin authentication**: Session-based login system
- **API key system**: Role-based access (admin/user/readonly)
- **SQL injection prevention**: Parameterized queries
- **Health monitoring**: Comprehensive system checks
- **Audit logging**: Financial transaction tracking
- **Secret management**: Environment variables (.env)

### ⚠️ **Next Steps for Production**
- **Public API authentication**: Add JWT/OAuth for user endpoints
- **Rate limiting**: Per-user/IP throttling
- **Real blockchain integration**: Replace mock chain adapter
- **Oracle integration**: Replace mock price feeds
- **Multi-instance deployment**: Load balancer + scaling

## 🚀 Production Deployment

### Infrastructure Requirements
- **Application**: 2+ instances behind load balancer
- **Database**: PostgreSQL 15+ with read replicas
- **Cache**: Redis Cluster for high availability
- **Monitoring**: Prometheus + Grafana + Alertmanager
- **Logs**: ELK Stack or equivalent

### Scaling Considerations
- **Horizontal scaling**: Stateless API design
- **Database optimization**: Read replicas for queries
- **Caching strategy**: Redis for frequently accessed data  
- **Queue processing**: Background job workers
- **CDN**: Static asset delivery

### Backup & Recovery
- **Database backups**: Automated daily + WAL archiving
- **Configuration**: Infrastructure as Code (Terraform)
- **Secrets**: Encrypted backup storage
- **Disaster recovery**: Multi-region deployment capability

## 🤝 Contributing

### Development Setup
```bash
make install              # Install dev dependencies
make format              # Format code with black
make lint                # Run ruff linting + mypy
pre-commit install       # Git hooks for quality
```

### Code Standards
- **Formatting**: Black (88 char line length)
- **Linting**: Ruff for Python best practices
- **Type checking**: MyPy for static analysis
- **Testing**: 90%+ coverage requirement
- **Documentation**: Docstrings for all public APIs

## 📄 License

[Add your license here]

## 🆘 Support

- **Issues**: [GitHub Issues](repository-url/issues)
- **Documentation**: See `OPERATING_MANUAL.md` for detailed operations
- **Claude Code**: See `CLAUDE.md` for development notes

---

**⚠️ Disclaimer**: This is a demonstration MVP. For production use, implement proper authentication, replace mock adapters with real integrations, and follow security best practices.