# 🚀 Production Deployment Guide

This guide covers deploying the Betting MVP to production with comprehensive monitoring, security, and reliability features.

## 🏗️ Production Architecture

The production deployment includes:

- **API Server**: FastAPI application with 4 workers
- **Database**: PostgreSQL 15 with automated backups
- **Cache**: Redis with persistence
- **Monitoring**: Prometheus + Grafana dashboards
- **Alerting**: Slack/Discord webhooks + Prometheus alerts
- **Logging**: Structured logging with optional ELK integration
- **Health Checks**: Comprehensive system health monitoring
- **Security**: Non-root containers, secret management

## 📋 Prerequisites

### Server Requirements

- **CPU**: Minimum 4 cores (8 cores recommended)
- **RAM**: Minimum 8GB (16GB recommended)
- **Storage**: Minimum 100GB SSD
- **Network**: Stable internet with low latency to blockchain RPC
- **OS**: Ubuntu 20.04 LTS or newer

### Required Services

- **Docker**: Version 20.10+
- **Docker Compose**: Version 2.0+
- **Domain**: For HTTPS and monitoring access
- **SSL Certificate**: Let's Encrypt or commercial
- **Blockchain RPC**: Reliable RPC endpoint (Alchemy, Infura, etc.)

## 🔐 Security Setup

### 1. Create Environment File

```bash
cp .env.prod.example .env
```

Edit `.env` with your production values:

```bash
# Critical: Generate secure passwords
POSTGRES_PASSWORD=$(openssl rand -base64 32)
REDIS_PASSWORD=$(openssl rand -base64 32)
GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 32)

# Blockchain: Use your actual wallet addresses and RPC
CHAIN_RPC_URL=https://base-mainnet.g.alchemy.com/v2/YOUR_API_KEY
DEPOSIT_WALLET_ADDRESS=0xYourHotWalletAddress
WITHDRAWAL_PRIVATE_KEY=0xYourSecurePrivateKey

# Monitoring: Set up webhook URLs
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### 2. Secure File Permissions

```bash
chmod 600 .env
chown root:root .env
```

### 3. Firewall Configuration

```bash
# Only allow necessary ports
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw allow 8000/tcp  # API (if not using reverse proxy)
ufw enable
```

## 🚀 Deployment Steps

### 1. Clone and Setup

```bash
git clone https://github.com/your-org/betting_mvp.git
cd betting_mvp
git checkout main  # Use stable branch in production
```

### 2. Build and Start Services

```bash
# Build production images
docker-compose -f docker-compose.prod.yml build

# Start all services
docker-compose -f docker-compose.prod.yml up -d
```

### 3. Initialize Database

The application automatically runs migrations on startup, but you can also run them manually:

```bash
docker-compose -f docker-compose.prod.yml exec api python -m alembic upgrade head
```

### 4. Create Initial API Key

```bash
docker-compose -f docker-compose.prod.yml exec api python -m cli.main auth create-key \
    --name "Production Admin" \
    --role admin
```

Save the generated API key securely!

### 5. Verify Deployment

```bash
# Check all services are running
docker-compose -f docker-compose.prod.yml ps

# Test API health
curl http://localhost:8000/health

# Check logs
docker-compose -f docker-compose.prod.yml logs -f api
```

## 📊 Monitoring Setup

### Accessing Monitoring Services

- **API**: `http://your-domain:8000`
- **Grafana**: `http://your-domain:3000` (admin/password from .env)
- **Prometheus**: `http://your-domain:9090`

### Key Dashboards to Monitor

1. **System Health**: Database, Redis, API response times
2. **Business Metrics**: Bets placed, volume, active users
3. **Blockchain**: Transaction confirmations, error rates
4. **Security**: Failed authentication attempts, unusual patterns

### Alert Configuration

Alerts are automatically configured for:

- **Critical**: Database down, application crash, ledger imbalance
- **High**: Blockchain errors, low wallet balance, stuck transactions
- **Medium**: High response times, unusual trading volume
- **Low**: Minor performance degradations

## 🔄 Operational Procedures

### Daily Checks

1. **Health Dashboard**: Check overall system status
2. **Balance Reconciliation**: Verify ledger vs blockchain balance
3. **Pending Transactions**: Review stuck transactions
4. **Error Logs**: Check for any unusual errors

### Weekly Tasks

1. **Database Backup Verification**: Ensure backups are working
2. **Security Updates**: Update system packages
3. **Performance Review**: Check response times and resource usage
4. **User Activity**: Review betting patterns and user growth

### Monthly Tasks

1. **Security Audit**: Review access logs and permissions
2. **Capacity Planning**: Assess resource needs
3. **Disaster Recovery Test**: Verify backup restore procedures
4. **Business Review**: Analyze metrics and performance

## 🔧 Maintenance Commands

### View Logs

```bash
# API logs
docker-compose -f docker-compose.prod.yml logs -f api

# Database logs
docker-compose -f docker-compose.prod.yml logs -f postgres

# All services
docker-compose -f docker-compose.prod.yml logs -f
```

### Manual Database Operations

```bash
# Create database backup
docker-compose -f docker-compose.prod.yml exec postgres pg_dump \
    -U betting betting_prod > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from backup
docker-compose -f docker-compose.prod.yml exec -T postgres psql \
    -U betting betting_prod < backup_file.sql
```

### API Key Management

```bash
# List API keys
docker-compose -f docker-compose.prod.yml exec api \
    python -m cli.main auth list-keys

# Rotate API key
docker-compose -f docker-compose.prod.yml exec api \
    python -m cli.main auth rotate-key --key-id KEY_ID

# Revoke API key
docker-compose -f docker-compose.prod.yml exec api \
    python -m cli.main auth revoke-key --key-id KEY_ID
```

### Blockchain Operations

```bash
# Check wallet balance
docker-compose -f docker-compose.prod.yml exec api \
    python -c "
from adapters.ethereum import create_ethereum_gateway
import asyncio
gateway = create_ethereum_gateway('base-mainnet')
asyncio.run(gateway.initialize())
balance = asyncio.run(gateway.get_wallet_balance())
print(f'Wallet balance: {balance / 10**6:.2f} USDC')
"

# Monitor pending transactions
docker-compose -f docker-compose.prod.yml exec api \
    python -m cli.main tvl
```

## 🚨 Emergency Procedures

### Service Recovery

```bash
# Restart all services
docker-compose -f docker-compose.prod.yml restart

# Restart specific service
docker-compose -f docker-compose.prod.yml restart api

# Force rebuild and restart
docker-compose -f docker-compose.prod.yml up -d --build
```

### Database Recovery

```bash
# Stop application to prevent writes
docker-compose -f docker-compose.prod.yml stop api

# Restore from backup
docker-compose -f docker-compose.prod.yml exec -T postgres psql \
    -U betting betting_prod < latest_backup.sql

# Start application
docker-compose -f docker-compose.prod.yml start api
```

### Blockchain Issues

If blockchain connectivity is lost:

1. **Check RPC Status**: Verify your RPC provider is operational
2. **Switch RPC**: Update `CHAIN_RPC_URL` to backup provider
3. **Monitor Pending**: Check for stuck transactions
4. **Manual Reconciliation**: Run reconciliation after recovery

## 📈 Scaling Considerations

### Horizontal Scaling

To scale beyond single-server:

1. **Load Balancer**: Add nginx/HAProxy for API requests
2. **Database**: Use read replicas for reporting queries
3. **Redis Cluster**: Scale cache layer
4. **Worker Processes**: Separate background task processing

### Resource Optimization

```bash
# Monitor resource usage
docker stats

# Optimize database
docker-compose -f docker-compose.prod.yml exec postgres \
    psql -U betting betting_prod -c "ANALYZE;"

# Clean old data
docker-compose -f docker-compose.prod.yml exec api \
    python -m cli.main cleanup --days 90
```

## 🛡️ Security Best Practices

### Regular Security Tasks

1. **Update Dependencies**: Keep all packages updated
2. **Rotate Secrets**: Change passwords and keys quarterly
3. **Access Review**: Audit who has access to production
4. **Backup Encryption**: Ensure backups are encrypted
5. **Network Security**: Use VPN for administrative access

### Monitoring Security

- **Failed Login Attempts**: Monitor authentication logs
- **Unusual API Usage**: Watch for suspicious patterns
- **Large Transactions**: Alert on significant amounts
- **System Changes**: Log all configuration modifications

## 📞 Support and Troubleshooting

### Common Issues

1. **High Memory Usage**: Check for memory leaks, restart if needed
2. **Slow Database**: Run `ANALYZE` and check indexes
3. **Blockchain Lag**: Verify RPC provider status
4. **Alert Spam**: Adjust alert thresholds if too noisy

### Getting Help

- **Logs**: Always check logs first: `docker-compose logs -f`
- **Health Endpoint**: `/health` provides system status
- **Metrics**: Prometheus metrics at `/metrics`
- **Documentation**: Refer to CLAUDE.md for architectural details

## 🎯 Performance Targets

### SLA Targets

- **Uptime**: 99.9% (8.76 hours downtime per year)
- **API Response**: <500ms for 95th percentile
- **Database Queries**: <100ms average
- **Transaction Processing**: <2 minutes to confirmation

### Monitoring Thresholds

- **Error Rate**: <0.1% for 5xx errors
- **Memory Usage**: <80% of available RAM
- **CPU Usage**: <70% sustained load
- **Disk Usage**: <85% of available space

Remember: This is a production system handling real money. Always test changes in staging first and have a rollback plan ready!