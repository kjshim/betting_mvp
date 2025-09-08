# Betting MVP - House Operating Manual

This manual provides comprehensive instructions for house operators to manage the daily operations of the 24h Up/Down betting service.

## 📋 Table of Contents

1. [Daily Operations](#daily-operations)
2. [Round Management](#round-management)
3. [User Management](#user-management)
4. [Financial Operations](#financial-operations)
5. [Monitoring & Health Checks](#monitoring--health-checks)
6. [Incident Response](#incident-response)
7. [Administrative Tasks](#administrative-tasks)
8. [Troubleshooting](#troubleshooting)

## 🌅 Daily Operations

### Pre-Market Checklist (Before 9:00 AM ET)

1. **System Health Check**
   ```bash
   # Check all services are running
   curl http://localhost:8000/health
   
   # Verify database connectivity
   python -m cli.main tvl
   
   # Check scheduler status
   docker-compose ps
   ```

2. **Open Today's Round**
   ```bash
   # Open round for current date
   TODAY=$(date +%Y%m%d)
   python -m cli.main open-round --code $TODAY
   
   # Verify round creation
   curl http://localhost:8000/rounds/current
   ```

3. **Review Overnight Activity**
   ```bash
   # Check for any pending transactions
   docker-compose logs api | grep -i error
   
   # Review withdrawal queue
   # (Check admin dashboard or database directly)
   ```

### Market Close Procedures (3:55-4:10 PM ET)

4. **Pre-Settlement Verification (3:55 PM ET)**
   ```bash
   # Verify round will lock soon
   python -m cli.main tvl
   
   # Check current betting pools
   curl http://localhost:8000/rounds/current
   ```

5. **Manual Lock if Needed (4:00 PM ET)**
   ```bash
   # Only if automatic lock fails
   TODAY=$(date +%Y%m%d)
   python -m cli.main lock-round --code $TODAY
   ```

6. **Monitor Settlement (4:05-4:10 PM ET)**
   ```bash
   # Check if settlement completed automatically
   curl http://localhost:8000/rounds/current
   
   # If settlement failed, check logs
   docker-compose logs api | tail -50
   ```

7. **Manual Settlement if Required**
   ```bash
   # If auto-settlement fails within 5 minutes
   TODAY=$(date +%Y%m%d)
   
   # Use AUTO for oracle price, or specify UP/DOWN
   python -m cli.main settle-round --code $TODAY --result AUTO
   ```

### Post-Settlement Review (4:15 PM ET)

8. **Verify Settlement Completion**
   ```bash
   # Check round status is SETTLED
   TODAY=$(date +%Y%m%d)
   python -m cli.main settle-round --code $TODAY --result AUTO
   
   # Verify TVL updated correctly
   python -m cli.main tvl
   ```

9. **Review Daily Metrics**
   ```bash
   # Check Prometheus metrics
   curl http://localhost:8000/metrics | grep betting_
   
   # Review profit/loss
   # (House fees earned from the day)
   ```

## 🎯 Round Management

### Opening New Rounds

```bash
# Standard daily round
python -m cli.main open-round --code $(date +%Y%m%d)

# Future round (weekend prep)
python -m cli.main open-round --code 20250915
```

**Round Parameters:**
- **Lock Time**: Automatically set to 15:59:59 ET
- **Settlement Time**: Automatically set to 16:05:00 ET
- **Commit Hash**: Generated automatically for integrity

### Emergency Round Operations

#### Emergency Lock
```bash
# Lock round immediately (emergency stop)
python -m cli.main lock-round --code 20250908
```

#### Manual Settlement
```bash
# Settle with specific result (use if oracle fails)
python -m cli.main settle-round --code 20250908 --result UP
python -m cli.main settle-round --code 20250908 --result DOWN

# Void round (refund all bets)
python -m cli.main settle-round --code 20250908 --result VOID
```

#### Oracle Failure Recovery
If oracle fails beyond grace period:

1. **Check Oracle Status**
   ```bash
   # Review oracle logs
   docker-compose logs api | grep -i oracle
   ```

2. **Manual Price Verification**
   - Verify NASDAQ official close from multiple sources
   - Document price sources used
   - Compare with previous day's close

3. **Execute Settlement**
   ```bash
   # Settle with verified result
   python -m cli.main settle-round --code 20250908 --result UP
   ```

4. **Post-Settlement Audit**
   ```bash
   # Verify all payouts correct
   python -m cli.main tvl
   
   # Generate settlement report
   # (Custom reporting script or manual verification)
   ```

## 👥 User Management

### Creating User Accounts

```bash
# Create single user via CLI
python -m cli.main seed --users 1

# Bulk user creation
python -m cli.main seed --users 100
```

### User Balance Management

```bash
# Check user balance
# (Requires user email or ID)
python -m cli.main deposit --user user@example.com --amount 0  # Shows current balance

# Add funds (emergency credit)
python -m cli.main deposit --user user@example.com --amount 1000000  # 1 USDC

# Process withdrawal
python -m cli.main withdraw --user user@example.com --amount 500000   # 0.5 USDC
```

### User Support Operations

#### Balance Inquiry
```bash
# Via API
curl -X POST "http://localhost:8000/simulate/deposit_webhook" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-uuid-here", "amount_u": 0}'
```

#### Deposit Processing
```bash
# Simulate confirmed deposit (development/testing)
curl -X POST "http://localhost:8000/simulate/deposit_webhook" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-uuid-here", "amount_u": 1000000}'
```

#### Withdrawal Processing
```bash
# Queue withdrawal
curl -X POST "http://localhost:8000/withdrawals" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-uuid-here", "amount_u": 500000}'
```

## 💰 Financial Operations

### Daily Financial Reconciliation

1. **TVL Verification**
   ```bash
   python -m cli.main tvl
   ```
   Expected output:
   ```
   📊 TVL Metrics:
     Locked:             0 micro USDC (0.00 USDC)      # Should be 0 after settlement
     Total Cash:         X micro USDC (X.XX USDC)      # User balances
     Pending Withdrawals: Y micro USDC (Y.YY USDC)     # Queued withdrawals
   ```

2. **House P&L Calculation**
   ```sql
   -- Query house account balance
   SELECT SUM(amount_u) as house_balance_u 
   FROM ledger_entries 
   WHERE account = 'house';
   ```

3. **Fee Collection Verification**
   ```sql
   -- Daily fees collected
   SELECT DATE(ts) as date, SUM(amount_u) as fees_collected_u
   FROM ledger_entries 
   WHERE account = 'house' 
      AND ref_type = 'settlement'
      AND DATE(ts) = CURRENT_DATE
   GROUP BY DATE(ts);
   ```

### Emergency Financial Operations

#### System Balance Recovery
If system shows inconsistent balances:

1. **Stop All Operations**
   ```bash
   # Stop scheduler to prevent new rounds
   docker-compose stop api
   ```

2. **Audit Ledger Integrity**
   ```sql
   -- Verify all batches sum to zero
   SELECT ref_id, SUM(amount_u) as batch_total
   FROM ledger_entries
   GROUP BY ref_id
   HAVING SUM(amount_u) != 0;
   ```

3. **Identify Discrepancies**
   ```sql
   -- Find problematic transactions
   SELECT * FROM ledger_entries 
   WHERE ref_id IN (
       SELECT ref_id FROM ledger_entries 
       GROUP BY ref_id 
       HAVING SUM(amount_u) != 0
   );
   ```

#### Manual Balance Adjustment
Only use in extreme circumstances with proper approval:

```bash
# Create corrective entry (must balance to zero)
# This requires custom script - contact development team
```

### Withdrawal Management

#### Batch Withdrawal Processing
```bash
# Get pending withdrawals (custom query needed)
# Process through blockchain adapter
# Mark as completed in system
```

#### Failed Withdrawal Handling
```bash
# Return funds to user's cash account
# Update withdrawal status to FAILED
# Notify user of failure
```

## 📊 Monitoring & Health Checks

### Real-Time Monitoring

1. **System Health Dashboard**
   ```bash
   # API health
   curl http://localhost:8000/health
   
   # Database connectivity
   docker-compose exec db pg_isready -U user -d app
   
   # Redis connectivity
   docker-compose exec redis redis-cli ping
   ```

2. **Prometheus Metrics**
   ```bash
   # Key metrics to monitor
   curl http://localhost:8000/metrics | grep -E "(betting_|tvl_|round_)"
   ```

3. **Application Logs**
   ```bash
   # Real-time log monitoring
   docker-compose logs -f api
   
   # Error log analysis
   docker-compose logs api | grep -i error | tail -20
   ```

### Performance Monitoring

#### Key Performance Indicators (KPIs)

| Metric | Normal Range | Alert Threshold | Action Required |
|--------|-------------|----------------|-----------------|
| API Response Time | < 100ms | > 500ms | Scale up instances |
| Database Connections | < 80% pool | > 90% pool | Increase pool size |
| TVL Growth | Positive daily | Negative 3 days | Marketing review |
| Settlement Latency | < 30s | > 60s | Oracle investigation |
| Error Rate | < 0.1% | > 1% | Immediate investigation |

#### Daily Reports

```bash
# Generate daily activity report
# (Custom script needed - template below)

echo "Daily Report for $(date)"
echo "========================"
echo "Total Users: $(echo 'SELECT COUNT(*) FROM users;' | docker-compose exec -T db psql -U user -d app -t)"
echo "Active Bettors: $(echo 'SELECT COUNT(DISTINCT user_id) FROM bets WHERE DATE(created_at) = CURRENT_DATE;' | docker-compose exec -T db psql -U user -d app -t)"
echo "Daily Volume: $(echo 'SELECT SUM(stake_u) FROM bets WHERE DATE(created_at) = CURRENT_DATE;' | docker-compose exec -T db psql -U user -d app -t) micro-USDC"
python -m cli.main tvl
```

### Alerting Setup

#### Critical Alerts (Immediate Response Required)
- API server down
- Database connection failures
- Settlement failures beyond grace period
- Ledger imbalance detected
- Security incidents

#### Warning Alerts (Response within 30 minutes)
- High error rates
- Slow API responses
- Oracle delays
- Unusual betting patterns
- Withdrawal queue backlog

## 🚨 Incident Response

### Severity Levels

#### P0 - Critical (Response: Immediate)
- **System down**: API/Database completely unavailable
- **Data corruption**: Ledger inconsistencies
- **Security breach**: Unauthorized access detected
- **Settlement failure**: Cannot settle daily round

#### P1 - High (Response: 15 minutes)
- **Oracle failure**: Cannot fetch prices
- **API degradation**: High error rates
- **Scheduler issues**: Jobs not executing
- **Withdrawal issues**: Blockchain problems

#### P2 - Medium (Response: 1 hour)
- **Performance degradation**: Slow responses
- **Minor data issues**: Non-critical inconsistencies
- **User complaints**: Individual account problems

### Incident Response Procedures

#### P0 Critical Incident Response

1. **Immediate Assessment (0-5 minutes)**
   ```bash
   # Quick system check
   curl -f http://localhost:8000/health || echo "API DOWN"
   docker-compose ps | grep -v "Up"
   python -m cli.main tvl || echo "DATABASE ISSUES"
   ```

2. **Emergency Actions (5-15 minutes)**
   ```bash
   # Stop new bet acceptance
   # Lock current round if needed
   TODAY=$(date +%Y%m%d)
   python -m cli.main lock-round --code $TODAY
   
   # Preserve system state
   docker-compose logs api > incident_$(date +%Y%m%d_%H%M).log
   ```

3. **Stakeholder Communication (15 minutes)**
   - Notify management
   - Update status page
   - Prepare user communication

4. **Recovery Actions**
   - Follow specific recovery procedures
   - Test system functionality
   - Resume operations gradually

#### Settlement Failure Recovery

1. **Immediate Response**
   ```bash
   # Check scheduler status
   docker-compose ps scheduler
   
   # Review settlement logs
   docker-compose logs api | grep -i settlement
   ```

2. **Oracle Verification**
   ```bash
   # Check oracle connectivity
   # Verify market close price from multiple sources
   # Document price sources
   ```

3. **Manual Settlement**
   ```bash
   TODAY=$(date +%Y%m%d)
   
   # If price verified
   python -m cli.main settle-round --code $TODAY --result UP
   
   # If oracle completely failed
   python -m cli.main settle-round --code $TODAY --result VOID
   ```

4. **Post-Incident Review**
   - Document root cause
   - Update procedures
   - Implement preventive measures

## 🔧 Administrative Tasks

### Database Maintenance

#### Daily Maintenance
```bash
# Check database size
echo "SELECT pg_size_pretty(pg_database_size('app'));" | docker-compose exec -T db psql -U user -d app

# Analyze query performance
echo "SELECT query, calls, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;" | docker-compose exec -T db psql -U user -d app
```

#### Weekly Maintenance
```bash
# Vacuum and analyze
docker-compose exec db psql -U user -d app -c "VACUUM ANALYZE;"

# Check for unused indexes
# (Custom query needed)

# Review slow queries
# (Enable pg_stat_statements and analyze)
```

### Backup Operations

#### Daily Backups
```bash
# Database backup
docker-compose exec db pg_dump -U user -d app > backup_$(date +%Y%m%d).sql

# Configuration backup
tar -czf config_backup_$(date +%Y%m%d).tar.gz .env docker-compose.yml
```

#### Restore Procedures
```bash
# Database restore (DANGEROUS - test first)
# docker-compose exec -T db psql -U user -d app < backup_20250908.sql
```

### Security Operations

#### Access Management
```bash
# Review database connections
echo "SELECT usename, client_addr, state FROM pg_stat_activity;" | docker-compose exec -T db psql -U user -d app

# Check API access logs
docker-compose logs api | grep -E "(POST|GET|PUT|DELETE)" | tail -20
```

#### Security Audits
- Review user access patterns
- Check for unusual API usage
- Monitor for potential fraud
- Verify withdrawal request legitimacy

### Configuration Management

#### Environment Updates
```bash
# Backup current configuration
cp .env .env.backup_$(date +%Y%m%d)

# Update settings (example: change fee rate)
# Edit .env file
# FEE_BPS=150  # Change from 100 to 150 (1.5%)

# Restart services
docker-compose restart api
```

#### Feature Flags
```bash
# Enable/disable features through environment variables
# (If implemented in future versions)
```

## 🔍 Troubleshooting

### Common Issues and Solutions

#### Issue: API Not Responding
**Symptoms**: Health check fails, user complaints
```bash
# Diagnosis
curl -v http://localhost:8000/health
docker-compose ps api
docker-compose logs api --tail 50

# Solutions
docker-compose restart api
# If persistent: docker-compose up -d --scale api=2
```

#### Issue: Database Connection Errors
**Symptoms**: API errors, CLI commands fail
```bash
# Diagnosis
docker-compose exec db pg_isready -U user -d app
docker-compose logs db --tail 50

# Solutions
docker-compose restart db
# Check disk space: df -h
# Check connection limits: max_connections setting
```

#### Issue: Settlement Not Executing
**Symptoms**: Round stays LOCKED past 16:10 PM ET
```bash
# Diagnosis
docker-compose logs api | grep -i scheduler
curl http://localhost:8000/rounds/current

# Solutions
TODAY=$(date +%Y%m%d)
python -m cli.main settle-round --code $TODAY --result AUTO
# If oracle fails: --result VOID
```

#### Issue: Ledger Imbalance
**Symptoms**: TVL shows unexpected values
```bash
# Diagnosis
python -m cli.main tvl
# Run ledger integrity check (custom SQL needed)

# Solutions
# STOP all operations immediately
docker-compose stop api
# Contact development team
# Do not create manual entries without approval
```

#### Issue: High Memory/CPU Usage
**Symptoms**: Slow responses, system alerts
```bash
# Diagnosis
docker stats
top -c

# Solutions
docker-compose restart api
# Scale horizontally if possible
# Review recent changes for memory leaks
```

### Escalation Procedures

#### When to Escalate to Development Team
- Ledger integrity issues
- Database schema problems
- Security vulnerabilities
- Code bugs causing data corruption
- Performance issues requiring code changes

#### When to Escalate to Management
- Financial discrepancies > $1000
- Security incidents
- Regulatory compliance issues
- Extended service outages (>1 hour)
- User data breaches

### Emergency Contacts

#### Development Team
- **Primary**: [Developer contact]
- **Secondary**: [Backup developer]
- **On-call**: [Emergency number]

#### Management
- **Operations Manager**: [Contact]
- **CTO**: [Contact]
- **Legal**: [Contact for security incidents]

### Recovery Procedures

#### System Restore from Backup
```bash
# ONLY use in extreme circumstances
# 1. Stop all services
docker-compose down

# 2. Restore database
# (Follow backup restore procedures)

# 3. Restore configuration
tar -xzf config_backup_YYYYMMDD.tar.gz

# 4. Start services
docker-compose up -d

# 5. Verify system state
python -m cli.main tvl
curl http://localhost:8000/health
```

## 📝 Operational Checklists

### Daily Opening Checklist
- [ ] System health check completed
- [ ] Today's round opened
- [ ] Previous day's settlement verified
- [ ] Overnight logs reviewed
- [ ] Withdrawal queue processed
- [ ] TVL metrics normal

### Daily Closing Checklist
- [ ] Round locked automatically at 16:00 ET
- [ ] Settlement completed by 16:10 ET
- [ ] Payouts distributed correctly
- [ ] TVL updated properly
- [ ] Daily metrics recorded
- [ ] House P&L calculated

### Weekly Maintenance Checklist
- [ ] Database maintenance completed
- [ ] Backup verification performed
- [ ] Performance metrics reviewed
- [ ] Security audit completed
- [ ] Configuration updates applied
- [ ] Documentation updated

### Monthly Review Checklist
- [ ] Financial reconciliation completed
- [ ] System performance analysis
- [ ] User growth metrics
- [ ] Security assessment
- [ ] Capacity planning review
- [ ] Incident post-mortems

---

## 📞 Emergency Procedures Summary

### In Case of System Failure
1. **STOP** - Immediately stop accepting new bets
2. **ASSESS** - Determine scope and severity
3. **COMMUNICATE** - Notify stakeholders
4. **RECOVER** - Execute appropriate recovery procedures
5. **VERIFY** - Confirm system integrity before resuming
6. **DOCUMENT** - Record incident details for future prevention

### Remember
- **Always prioritize data integrity over availability**
- **When in doubt, stop operations and escalate**
- **Document all manual interventions**
- **Test recovery procedures regularly**
- **Keep emergency contacts readily available**

---

*This manual should be reviewed and updated monthly to reflect system changes and operational learnings.*