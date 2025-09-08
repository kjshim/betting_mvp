"""
Production monitoring and alerting infrastructure.

This module provides comprehensive monitoring capabilities including:
- Prometheus metrics collection
- Health check endpoints
- Performance monitoring
- Business metrics tracking
- Alert management
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from enum import Enum

import aiohttp
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from domain.models import Transfer, TransferStatus, TransferType, Bet, BetStatus, Round, RoundStatus, User
from domain.errors import ChainError, ErrorSeverity
from infra.settings import settings


logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheck:
    """Individual health check result"""
    name: str
    status: HealthStatus
    message: str
    latency_ms: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SystemHealth:
    """Overall system health status"""
    status: HealthStatus
    timestamp: datetime
    checks: List[HealthCheck]
    uptime_seconds: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "uptime_seconds": self.uptime_seconds,
            "checks": [asdict(check) for check in self.checks]
        }


class PrometheusMetrics:
    """Prometheus metrics collection for the betting service"""
    
    def __init__(self):
        self.registry = CollectorRegistry()
        
        # HTTP Request metrics
        self.http_requests_total = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status_code'],
            registry=self.registry
        )
        
        self.http_request_duration = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration',
            ['method', 'endpoint'],
            registry=self.registry
        )
        
        # Business metrics
        self.bets_total = Counter(
            'bets_total',
            'Total bets placed',
            ['side', 'status'],
            registry=self.registry
        )
        
        self.bet_amount_total = Counter(
            'bet_amount_micro_usdc_total',
            'Total bet amounts in micro USDC',
            ['side'],
            registry=self.registry
        )
        
        self.transfers_total = Counter(
            'transfers_total',
            'Total transfers',
            ['type', 'status'],
            registry=self.registry
        )
        
        self.transfer_amount_total = Counter(
            'transfer_amount_micro_usdc_total',
            'Total transfer amounts in micro USDC',
            ['type'],
            registry=self.registry
        )
        
        # System metrics
        self.active_users = Gauge(
            'active_users_total',
            'Number of active users',
            registry=self.registry
        )
        
        self.tvl_locked = Gauge(
            'tvl_locked_micro_usdc',
            'Total Value Locked in micro USDC',
            registry=self.registry
        )
        
        self.pending_transfers = Gauge(
            'pending_transfers_total',
            'Number of pending transfers',
            ['type'],
            registry=self.registry
        )
        
        # Blockchain metrics
        self.chain_confirmations = Histogram(
            'chain_confirmation_duration_seconds',
            'Time to get blockchain confirmations',
            ['type'],
            registry=self.registry
        )
        
        self.chain_errors_total = Counter(
            'chain_errors_total',
            'Total blockchain errors',
            ['category', 'severity'],
            registry=self.registry
        )
        
        # Performance metrics
        self.database_query_duration = Histogram(
            'database_query_duration_seconds',
            'Database query duration',
            ['operation'],
            registry=self.registry
        )
        
        self.settlement_duration = Histogram(
            'settlement_duration_seconds',
            'Round settlement duration',
            registry=self.registry
        )
        
        # Health metrics
        self.health_check_duration = Histogram(
            'health_check_duration_seconds',
            'Health check duration',
            ['check_name'],
            registry=self.registry
        )
        
        self.system_uptime = Gauge(
            'system_uptime_seconds',
            'System uptime in seconds',
            registry=self.registry
        )
        
        # Startup time
        self.startup_time = time.time()
        
    def record_http_request(self, method: str, endpoint: str, status_code: int, duration: float):
        """Record HTTP request metrics"""
        self.http_requests_total.labels(method, endpoint, status_code).inc()
        self.http_request_duration.labels(method, endpoint).observe(duration)
        
    def record_bet(self, side: str, status: str, amount: int):
        """Record bet metrics"""
        self.bets_total.labels(side, status).inc()
        self.bet_amount_total.labels(side).inc(amount)
        
    def record_transfer(self, transfer_type: str, status: str, amount: int):
        """Record transfer metrics"""
        self.transfers_total.labels(transfer_type, status).inc()
        self.transfer_amount_total.labels(transfer_type).inc(amount)
        
    def record_chain_error(self, error: ChainError):
        """Record blockchain error metrics"""
        self.chain_errors_total.labels(
            error.category.value,
            error.severity.value
        ).inc()
        
    def update_system_gauges(self, active_users: int, tvl_locked: int, pending_deposits: int, pending_withdrawals: int):
        """Update system gauge metrics"""
        self.active_users.set(active_users)
        self.tvl_locked.set(tvl_locked)
        self.pending_transfers.labels('deposit').set(pending_deposits)
        self.pending_transfers.labels('withdrawal').set(pending_withdrawals)
        self.system_uptime.set(time.time() - self.startup_time)
        
    def get_metrics_text(self) -> str:
        """Get Prometheus metrics in text format"""
        return generate_latest(self.registry).decode('utf-8')


class HealthChecker:
    """Comprehensive health checking service"""
    
    def __init__(self, db: AsyncSession, chain_gateway=None):
        self.db = db
        self.chain_gateway = chain_gateway
        
    async def check_database(self) -> HealthCheck:
        """Check database connectivity and performance"""
        start_time = time.time()
        
        try:
            # Simple query to test connectivity
            result = await self.db.execute(select(func.count()).select_from(User))
            user_count = result.scalar()
            
            latency_ms = (time.time() - start_time) * 1000
            
            if latency_ms > 5000:  # 5 seconds is too slow
                return HealthCheck(
                    name="database",
                    status=HealthStatus.DEGRADED,
                    message=f"Database responding slowly: {latency_ms:.0f}ms",
                    latency_ms=latency_ms,
                    metadata={"user_count": user_count}
                )
            
            return HealthCheck(
                name="database",
                status=HealthStatus.HEALTHY,
                message=f"Database operational ({user_count} users)",
                latency_ms=latency_ms,
                metadata={"user_count": user_count}
            )
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheck(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Database connectivity failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)}
            )
            
    async def check_blockchain(self) -> HealthCheck:
        """Check blockchain connectivity and sync status"""
        if not self.chain_gateway:
            return HealthCheck(
                name="blockchain",
                status=HealthStatus.DEGRADED,
                message="No blockchain gateway configured"
            )
            
        start_time = time.time()
        
        try:
            # Check blockchain health
            health_data = await self.chain_gateway.health_check()
            latency_ms = (time.time() - start_time) * 1000
            
            if not health_data.get("healthy", False):
                return HealthCheck(
                    name="blockchain",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Blockchain unhealthy: {health_data.get('error', 'Unknown error')}",
                    latency_ms=latency_ms,
                    metadata=health_data
                )
                
            # Check if we're behind on blocks
            latest_block = health_data.get("latest_block", 0)
            last_processed = health_data.get("last_processed_block", 0)
            block_lag = latest_block - last_processed
            
            if block_lag > 100:  # More than 100 blocks behind
                return HealthCheck(
                    name="blockchain",
                    status=HealthStatus.DEGRADED,
                    message=f"Blockchain sync lagging: {block_lag} blocks behind",
                    latency_ms=latency_ms,
                    metadata=health_data
                )
                
            return HealthCheck(
                name="blockchain",
                status=HealthStatus.HEALTHY,
                message=f"Blockchain operational (block {latest_block})",
                latency_ms=latency_ms,
                metadata=health_data
            )
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheck(
                name="blockchain",
                status=HealthStatus.UNHEALTHY,
                message=f"Blockchain check failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)}
            )
            
    async def check_pending_transactions(self) -> HealthCheck:
        """Check for stuck or overdue transactions"""
        start_time = time.time()
        
        try:
            # Count pending transactions older than 2 hours
            cutoff_time = datetime.utcnow() - timedelta(hours=2)
            
            result = await self.db.execute(
                select(func.count()).where(
                    and_(
                        Transfer.status == TransferStatus.PENDING,
                        Transfer.created_at < cutoff_time
                    )
                )
            )
            old_pending = result.scalar()
            
            # Count total pending
            result = await self.db.execute(
                select(func.count()).where(Transfer.status == TransferStatus.PENDING)
            )
            total_pending = result.scalar()
            
            latency_ms = (time.time() - start_time) * 1000
            
            if old_pending > 10:
                return HealthCheck(
                    name="pending_transactions",
                    status=HealthStatus.UNHEALTHY,
                    message=f"{old_pending} transactions pending over 2 hours",
                    latency_ms=latency_ms,
                    metadata={"old_pending": old_pending, "total_pending": total_pending}
                )
            elif old_pending > 0:
                return HealthCheck(
                    name="pending_transactions",
                    status=HealthStatus.DEGRADED,
                    message=f"{old_pending} transactions pending over 2 hours",
                    latency_ms=latency_ms,
                    metadata={"old_pending": old_pending, "total_pending": total_pending}
                )
            else:
                return HealthCheck(
                    name="pending_transactions",
                    status=HealthStatus.HEALTHY,
                    message=f"{total_pending} pending transactions (none overdue)",
                    latency_ms=latency_ms,
                    metadata={"total_pending": total_pending}
                )
                
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheck(
                name="pending_transactions",
                status=HealthStatus.UNHEALTHY,
                message=f"Transaction check failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)}
            )
            
    async def check_ledger_balance(self) -> HealthCheck:
        """Check ledger balance integrity"""
        start_time = time.time()
        
        try:
            from domain.models import LedgerEntry
            
            # Check that all ledger entries sum to zero
            result = await self.db.execute(
                select(func.sum(LedgerEntry.amount_u))
            )
            total_balance = result.scalar() or 0
            
            latency_ms = (time.time() - start_time) * 1000
            
            if abs(total_balance) > 1000:  # More than 0.001 USDC imbalance
                return HealthCheck(
                    name="ledger_balance",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Ledger imbalance detected: {total_balance} micro-USDC",
                    latency_ms=latency_ms,
                    metadata={"imbalance_micro_usdc": total_balance}
                )
            elif total_balance != 0:
                return HealthCheck(
                    name="ledger_balance",
                    status=HealthStatus.DEGRADED,
                    message=f"Minor ledger imbalance: {total_balance} micro-USDC",
                    latency_ms=latency_ms,
                    metadata={"imbalance_micro_usdc": total_balance}
                )
            else:
                return HealthCheck(
                    name="ledger_balance",
                    status=HealthStatus.HEALTHY,
                    message="Ledger is perfectly balanced",
                    latency_ms=latency_ms
                )
                
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheck(
                name="ledger_balance",
                status=HealthStatus.UNHEALTHY,
                message=f"Ledger balance check failed: {e}",
                latency_ms=latency_ms,
                metadata={"error": str(e)}
            )
            
    async def perform_full_health_check(self) -> SystemHealth:
        """Perform comprehensive health check"""
        start_time = time.time()
        
        # Run all health checks concurrently
        checks = await asyncio.gather(
            self.check_database(),
            self.check_blockchain(),
            self.check_pending_transactions(),
            self.check_ledger_balance(),
            return_exceptions=True
        )
        
        # Handle any exceptions in health checks
        valid_checks = []
        for check in checks:
            if isinstance(check, HealthCheck):
                valid_checks.append(check)
            else:
                # Health check itself failed
                valid_checks.append(HealthCheck(
                    name="unknown",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check failed: {check}"
                ))
                
        # Determine overall status
        if any(check.status == HealthStatus.UNHEALTHY for check in valid_checks):
            overall_status = HealthStatus.UNHEALTHY
        elif any(check.status == HealthStatus.DEGRADED for check in valid_checks):
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY
            
        uptime = time.time() - start_time
        
        return SystemHealth(
            status=overall_status,
            timestamp=datetime.utcnow(),
            checks=valid_checks,
            uptime_seconds=uptime
        )


class AlertManager:
    """
    Alert management and notification system.
    
    In production, this would integrate with:
    - Slack/Discord webhooks
    - PagerDuty for incident management
    - Email notifications
    - SMS alerts for critical issues
    """
    
    def __init__(self):
        self.webhook_urls = {
            "slack": settings.slack_webhook_url if hasattr(settings, 'slack_webhook_url') else None,
            "discord": settings.discord_webhook_url if hasattr(settings, 'discord_webhook_url') else None
        }
        self.alert_history = []
        self.rate_limit_cache = {}  # Prevent alert spam
        
    async def send_alert(
        self,
        title: str,
        message: str,
        severity: str = "medium",
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Send an alert through configured channels"""
        
        # Rate limiting - don't send same alert more than once per 5 minutes
        alert_key = f"{title}:{severity}"
        now = time.time()
        
        if alert_key in self.rate_limit_cache:
            if now - self.rate_limit_cache[alert_key] < 300:  # 5 minutes
                logger.debug(f"Alert rate limited: {alert_key}")
                return
                
        self.rate_limit_cache[alert_key] = now
        
        # Log the alert
        log_level = {
            "low": logging.INFO,
            "medium": logging.WARNING,
            "high": logging.ERROR,
            "critical": logging.CRITICAL
        }.get(severity, logging.WARNING)
        
        logger.log(log_level, f"ALERT [{severity.upper()}] {title}: {message}")
        
        # Store in history
        alert_data = {
            "title": title,
            "message": message,
            "severity": severity,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        
        self.alert_history.append(alert_data)
        self.alert_history = self.alert_history[-100:]  # Keep last 100
        
        # Send to external services
        await self._send_to_webhooks(alert_data)
        
    async def _send_to_webhooks(self, alert_data: Dict[str, Any]):
        """Send alert to webhook endpoints"""
        
        # Format for Slack
        if self.webhook_urls.get("slack"):
            slack_payload = {
                "text": f"🚨 {alert_data['title']}",
                "attachments": [
                    {
                        "color": self._get_color_for_severity(alert_data["severity"]),
                        "fields": [
                            {"title": "Message", "value": alert_data["message"], "short": False},
                            {"title": "Severity", "value": alert_data["severity"].upper(), "short": True},
                            {"title": "Time", "value": alert_data["timestamp"], "short": True}
                        ]
                    }
                ]
            }
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.webhook_urls["slack"], json=slack_payload, timeout=10) as resp:
                        if resp.status != 200:
                            logger.error(f"Failed to send Slack alert: {resp.status}")
            except Exception as e:
                logger.error(f"Error sending Slack alert: {e}")
                
        # Format for Discord
        if self.webhook_urls.get("discord"):
            discord_payload = {
                "embeds": [
                    {
                        "title": f"🚨 {alert_data['title']}",
                        "description": alert_data["message"],
                        "color": self._get_discord_color(alert_data["severity"]),
                        "timestamp": alert_data["timestamp"],
                        "fields": [
                            {"name": "Severity", "value": alert_data["severity"].upper(), "inline": True}
                        ]
                    }
                ]
            }
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.webhook_urls["discord"], json=discord_payload, timeout=10) as resp:
                        if resp.status not in [200, 204]:
                            logger.error(f"Failed to send Discord alert: {resp.status}")
            except Exception as e:
                logger.error(f"Error sending Discord alert: {e}")
                
    def _get_color_for_severity(self, severity: str) -> str:
        """Get Slack attachment color for severity level"""
        colors = {
            "low": "good",      # Green
            "medium": "warning", # Yellow
            "high": "danger",   # Red
            "critical": "#8B0000"  # Dark red
        }
        return colors.get(severity, "warning")
        
    def _get_discord_color(self, severity: str) -> int:
        """Get Discord embed color for severity level"""
        colors = {
            "low": 0x00FF00,     # Green
            "medium": 0xFFFF00,  # Yellow
            "high": 0xFF0000,    # Red
            "critical": 0x8B0000 # Dark red
        }
        return colors.get(severity, 0xFFFF00)
        
    def get_recent_alerts(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get recent alerts from the last N hours"""
        # In a real implementation, you'd filter by timestamp
        return self.alert_history[-20:]  # Return last 20 for now
        
    async def send_health_alert(self, health: SystemHealth):
        """Send alert based on health check results"""
        if health.status == HealthStatus.UNHEALTHY:
            unhealthy_checks = [c for c in health.checks if c.status == HealthStatus.UNHEALTHY]
            await self.send_alert(
                title="System Health Critical",
                message=f"System is unhealthy. Failed checks: {', '.join(c.name for c in unhealthy_checks)}",
                severity="critical",
                metadata={"health_status": health.to_dict()}
            )
        elif health.status == HealthStatus.DEGRADED:
            degraded_checks = [c for c in health.checks if c.status == HealthStatus.DEGRADED]
            await self.send_alert(
                title="System Performance Degraded",
                message=f"System performance is degraded. Issues: {', '.join(c.name for c in degraded_checks)}",
                severity="medium",
                metadata={"health_status": health.to_dict()}
            )


class BusinessMetricsCollector:
    """Collect business-specific metrics for monitoring"""
    
    def __init__(self, db: AsyncSession, prometheus_metrics: PrometheusMetrics):
        self.db = db
        self.metrics = prometheus_metrics
        
    async def collect_daily_metrics(self) -> Dict[str, Any]:
        """Collect daily business metrics"""
        today = datetime.utcnow().date()
        start_of_day = datetime.combine(today, datetime.min.time())
        
        # Count bets placed today
        result = await self.db.execute(
            select(func.count()).where(
                and_(
                    Bet.created_at >= start_of_day,
                    Bet.status != BetStatus.VOID
                )
            )
        )
        daily_bets = result.scalar() or 0
        
        # Sum bet amounts today
        result = await self.db.execute(
            select(func.sum(Bet.stake_u)).where(
                and_(
                    Bet.created_at >= start_of_day,
                    Bet.status != BetStatus.VOID
                )
            )
        )
        daily_volume = result.scalar() or 0
        
        # Count unique users who bet today
        result = await self.db.execute(
            select(func.count(func.distinct(Bet.user_id))).where(
                and_(
                    Bet.created_at >= start_of_day,
                    Bet.status != BetStatus.VOID
                )
            )
        )
        daily_active_users = result.scalar() or 0
        
        # Count deposits and withdrawals today
        result = await self.db.execute(
            select(Transfer.type, func.count(), func.sum(Transfer.amount_u))
            .where(Transfer.created_at >= start_of_day)
            .group_by(Transfer.type)
        )
        
        transfers_today = {"deposits": {"count": 0, "volume": 0}, "withdrawals": {"count": 0, "volume": 0}}
        for transfer_type, count, volume in result.all():
            type_key = "deposits" if transfer_type == TransferType.DEPOSIT else "withdrawals"
            transfers_today[type_key] = {"count": count, "volume": volume or 0}
            
        # Update Prometheus gauges
        self.metrics.update_system_gauges(
            active_users=daily_active_users,
            tvl_locked=0,  # Would calculate from ledger
            pending_deposits=transfers_today["deposits"]["count"],
            pending_withdrawals=transfers_today["withdrawals"]["count"]
        )
        
        return {
            "date": today.isoformat(),
            "daily_bets": daily_bets,
            "daily_volume_usdc": daily_volume / 10**6,
            "daily_active_users": daily_active_users,
            "transfers_today": transfers_today,
            "timestamp": datetime.utcnow().isoformat()
        }


# Global instances
prometheus_metrics = PrometheusMetrics()
alert_manager = AlertManager()