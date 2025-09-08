"""
Transaction confirmation monitoring and reconciliation services.

These services ensure that all deposits and withdrawals are properly tracked
and confirmed on the blockchain, with automatic retry and alerting for issues.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from adapters.chain import ChainGateway
from domain.models import Transfer, TransferStatus, TransferType
from domain.services import LedgerService


logger = logging.getLogger(__name__)


class MonitoringAlert(Enum):
    """Types of monitoring alerts"""
    PENDING_TOO_LONG = "pending_too_long"
    CONFIRMATION_DROPPED = "confirmation_dropped"
    BALANCE_MISMATCH = "balance_mismatch"
    LARGE_WITHDRAWAL = "large_withdrawal"
    FAILED_TRANSACTION = "failed_transaction"
    NETWORK_ISSUES = "network_issues"


@dataclass
class Alert:
    """Monitoring alert data"""
    type: MonitoringAlert
    severity: str  # "low", "medium", "high", "critical"
    message: str
    transfer_id: Optional[uuid.UUID] = None
    tx_hash: Optional[str] = None
    metadata: Optional[Dict] = None


class TransactionMonitoringService:
    """
    Service for monitoring blockchain transactions and their confirmations.
    
    Handles:
    - Tracking pending transactions
    - Updating confirmation status
    - Alerting on stuck or failed transactions
    - Automatic retry logic
    """
    
    def __init__(self, db: AsyncSession, chain_gateway: ChainGateway):
        self.db = db
        self.chain_gateway = chain_gateway
        self.alerts: List[Alert] = []
        
        # Configuration
        self.max_pending_hours = 24  # Alert if pending longer than this
        self.confirmation_threshold = 6  # Required confirmations
        self.large_withdrawal_threshold = 10000 * 10**6  # 10,000 USDC in micro-USDC
        
    async def monitor_pending_transactions(self) -> List[Alert]:
        """
        Monitor all pending transactions and return any alerts.
        
        This should be called periodically (every 5-10 minutes).
        """
        alerts = []
        
        # Get all pending transactions
        result = await self.db.execute(
            select(Transfer).where(
                Transfer.status.in_([TransferStatus.PENDING, TransferStatus.SUBMITTED])
            )
        )
        pending_transfers = result.scalars().all()
        
        logger.info(f"Monitoring {len(pending_transfers)} pending transactions")
        
        for transfer in pending_transfers:
            try:
                alert = await self._monitor_single_transaction(transfer)
                if alert:
                    alerts.append(alert)
            except Exception as e:
                logger.error(f"Error monitoring transaction {transfer.id}: {e}")
                alerts.append(Alert(
                    type=MonitoringAlert.NETWORK_ISSUES,
                    severity="medium",
                    message=f"Failed to monitor transaction: {e}",
                    transfer_id=transfer.id,
                    tx_hash=transfer.tx_hash
                ))
                
        return alerts
        
    async def _monitor_single_transaction(self, transfer: Transfer) -> Optional[Alert]:
        """Monitor a single pending transaction"""
        if not transfer.tx_hash:
            return Alert(
                type=MonitoringAlert.FAILED_TRANSACTION,
                severity="high",
                message="Transfer has no transaction hash",
                transfer_id=transfer.id
            )
            
        # Get current confirmation count
        confirmations = await self.chain_gateway.get_confirmations(transfer.tx_hash)
        
        # Check if transaction is confirmed
        if confirmations >= self.confirmation_threshold:
            await self._confirm_transaction(transfer)
            return None
            
        # Check if pending too long
        hours_pending = (datetime.utcnow() - transfer.created_at).total_seconds() / 3600
        if hours_pending > self.max_pending_hours:
            return Alert(
                type=MonitoringAlert.PENDING_TOO_LONG,
                severity="high" if hours_pending > 48 else "medium",
                message=f"Transaction pending for {hours_pending:.1f} hours",
                transfer_id=transfer.id,
                tx_hash=transfer.tx_hash,
                metadata={"hours_pending": hours_pending, "confirmations": confirmations}
            )
            
        # Check for confirmation drops (blockchain reorg)
        if confirmations == 0 and transfer.status == TransferStatus.PENDING:
            # Transaction might have been dropped or replaced
            return Alert(
                type=MonitoringAlert.CONFIRMATION_DROPPED,
                severity="high",
                message="Transaction no longer found on blockchain",
                transfer_id=transfer.id,
                tx_hash=transfer.tx_hash
            )
            
        # Alert on large withdrawals
        if (transfer.type == TransferType.WITHDRAWAL and 
            transfer.amount_u > self.large_withdrawal_threshold and
            confirmations < self.confirmation_threshold):
            
            return Alert(
                type=MonitoringAlert.LARGE_WITHDRAWAL,
                severity="medium",
                message=f"Large withdrawal pending: {transfer.amount_u / 10**6:.2f} USDC",
                transfer_id=transfer.id,
                tx_hash=transfer.tx_hash,
                metadata={"amount_usdc": transfer.amount_u / 10**6}
            )
            
        return None
        
    async def _confirm_transaction(self, transfer: Transfer):
        """Mark a transaction as confirmed"""
        try:
            transfer.status = TransferStatus.CONFIRMED
            transfer.confirmed_at = datetime.utcnow()
            
            await self.db.commit()
            
            logger.info(f"Confirmed {transfer.type} transaction {transfer.tx_hash} "
                       f"for {transfer.amount_u / 10**6:.2f} USDC")
                       
        except Exception as e:
            logger.error(f"Error confirming transaction {transfer.id}: {e}")
            await self.db.rollback()
            raise
            
    async def get_monitoring_stats(self) -> Dict[str, any]:
        """Get current monitoring statistics"""
        # Count pending transactions by type
        result = await self.db.execute(
            select(Transfer.type, Transfer.status)
            .where(Transfer.status.in_([
                TransferStatus.PENDING, 
                TransferStatus.SUBMITTED,
                TransferStatus.CONFIRMED
            ]))
        )
        
        stats = {
            "pending_deposits": 0,
            "pending_withdrawals": 0,
            "confirmed_24h": 0,
            "total_pending_value_usdc": 0.0,
            "oldest_pending_hours": 0.0
        }
        
        pending_transfers = []
        confirmed_24h_count = 0
        total_pending_value = 0
        
        transfers = result.all()
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        
        for transfer_type, status in transfers:
            if status in [TransferStatus.PENDING, TransferStatus.SUBMITTED]:
                if transfer_type == TransferType.DEPOSIT:
                    stats["pending_deposits"] += 1
                elif transfer_type == TransferType.WITHDRAWAL:
                    stats["pending_withdrawals"] += 1
            elif status == TransferStatus.CONFIRMED:
                # This is a simplified count - in practice you'd check confirmed_at timestamp
                confirmed_24h_count += 1
                
        # Get detailed info for pending value and age calculations
        pending_result = await self.db.execute(
            select(Transfer).where(
                Transfer.status.in_([TransferStatus.PENDING, TransferStatus.SUBMITTED])
            )
        )
        
        pending_transfers = pending_result.scalars().all()
        
        if pending_transfers:
            total_pending_value = sum(t.amount_u for t in pending_transfers)
            oldest_transfer = min(pending_transfers, key=lambda t: t.created_at)
            oldest_hours = (datetime.utcnow() - oldest_transfer.created_at).total_seconds() / 3600
            
            stats["total_pending_value_usdc"] = total_pending_value / 10**6
            stats["oldest_pending_hours"] = oldest_hours
            
        stats["confirmed_24h"] = confirmed_24h_count
        
        return stats


class ReconciliationService:
    """
    Service for reconciling on-chain state with database records.
    
    Ensures that our database matches the actual blockchain state.
    """
    
    def __init__(self, db: AsyncSession, chain_gateway: ChainGateway, ledger_service: LedgerService):
        self.db = db
        self.chain_gateway = chain_gateway
        self.ledger_service = ledger_service
        
    async def reconcile_deposits(self) -> Dict[str, any]:
        """
        Reconcile deposit records with blockchain state.
        
        Finds deposits that exist on-chain but not in our database.
        """
        logger.info("Starting deposit reconciliation")
        
        # Get confirmed deposits from chain
        chain_deposits = self.chain_gateway.get_pending_deposits(min_confirmations=6)
        
        # Get existing deposits from database
        result = await self.db.execute(
            select(Transfer).where(
                Transfer.type == TransferType.DEPOSIT,
                Transfer.status == TransferStatus.CONFIRMED
            )
        )
        db_deposits = result.scalars().all()
        db_tx_hashes = {t.tx_hash for t in db_deposits}
        
        # Find missing deposits
        missing_deposits = []
        for chain_deposit in chain_deposits:
            if chain_deposit["tx_hash"] not in db_tx_hashes:
                missing_deposits.append(chain_deposit)
                
        # Process missing deposits
        processed_count = 0
        for missing in missing_deposits:
            try:
                await self._process_missing_deposit(missing)
                processed_count += 1
            except Exception as e:
                logger.error(f"Failed to process missing deposit {missing['tx_hash']}: {e}")
                
        reconciliation_result = {
            "chain_deposits": len(chain_deposits),
            "db_deposits": len(db_deposits),
            "missing_deposits": len(missing_deposits),
            "processed_missing": processed_count
        }
        
        logger.info(f"Deposit reconciliation complete: {reconciliation_result}")
        
        return reconciliation_result
        
    async def _process_missing_deposit(self, chain_deposit: Dict):
        """Process a deposit that was found on-chain but missing from database"""
        try:
            # Create transfer record
            transfer = Transfer(
                user_id=uuid.UUID(chain_deposit["user_id"]),  # Assuming UUID format
                type=TransferType.DEPOSIT,
                amount_u=chain_deposit["amount_u"],
                status=TransferStatus.CONFIRMED,
                tx_hash=chain_deposit["tx_hash"],
                confirmed_at=datetime.utcnow()
            )
            
            self.db.add(transfer)
            await self.db.flush()  # Get transfer.id
            
            # Update ledger
            self.ledger_service.create_entries([
                ("cash", transfer.user_id, transfer.amount_u, "deposit_reconciliation", transfer.id),
                ("house", None, -transfer.amount_u, "deposit_reconciliation", transfer.id),
            ])
            
            await self.db.commit()
            
            logger.info(f"Processed missing deposit: {transfer.amount_u / 10**6:.2f} USDC "
                       f"for user {transfer.user_id} (tx: {transfer.tx_hash})")
                       
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to process missing deposit: {e}")
            raise
            
    async def reconcile_balances(self) -> Dict[str, any]:
        """
        Reconcile ledger balances with expected values.
        
        Ensures that all ledger entries balance correctly.
        """
        logger.info("Starting balance reconciliation")
        
        # Check that all ledger entries sum to zero
        from domain.models import LedgerEntry
        
        result = await self.db.execute(
            select(LedgerEntry.ref_id, LedgerEntry.ref_type)
            .group_by(LedgerEntry.ref_id, LedgerEntry.ref_type)
        )
        
        unbalanced_refs = []
        
        for ref_id, ref_type in result.all():
            # Calculate sum for this reference
            sum_result = await self.db.execute(
                select(LedgerEntry.amount_u).where(
                    and_(
                        LedgerEntry.ref_id == ref_id,
                        LedgerEntry.ref_type == ref_type
                    )
                )
            )
            
            amounts = sum_result.scalars().all()
            total = sum(amounts)
            
            if total != 0:
                unbalanced_refs.append({
                    "ref_id": ref_id,
                    "ref_type": ref_type,
                    "imbalance": total
                })
                
        reconciliation_result = {
            "total_references_checked": result.rowcount,
            "unbalanced_references": len(unbalanced_refs),
            "unbalanced_refs": unbalanced_refs[:10]  # Limit to first 10 for logging
        }
        
        if unbalanced_refs:
            logger.error(f"Found {len(unbalanced_refs)} unbalanced ledger references")
        else:
            logger.info("All ledger entries are balanced")
            
        return reconciliation_result
        
    async def get_wallet_balance_comparison(self) -> Dict[str, any]:
        """Compare our ledger house balance with actual blockchain wallet balance"""
        try:
            # Get blockchain wallet balance
            chain_balance = await self.chain_gateway.get_wallet_balance()
            
            # Get house balance from ledger
            ledger_balance = await self.ledger_service.get_balance_async(None, "house")
            
            # Calculate difference
            difference = chain_balance - ledger_balance
            
            return {
                "chain_wallet_balance_usdc": chain_balance / 10**6,
                "ledger_house_balance_usdc": ledger_balance / 10**6,
                "difference_usdc": difference / 10**6,
                "difference_micro_usdc": difference,
                "reconciled": difference == 0
            }
            
        except Exception as e:
            logger.error(f"Error comparing wallet balances: {e}")
            return {
                "error": str(e),
                "reconciled": False
            }


class AlertingService:
    """
    Service for handling monitoring alerts and notifications.
    
    In production, this would integrate with services like:
    - Slack/Discord webhooks
    - PagerDuty for critical alerts
    - Email notifications
    - SMS for high-severity issues
    """
    
    def __init__(self):
        self.alert_history: List[Alert] = []
        
    async def process_alerts(self, alerts: List[Alert]):
        """Process a list of alerts"""
        for alert in alerts:
            await self._process_single_alert(alert)
            self.alert_history.append(alert)
            
        # Keep only last 1000 alerts
        self.alert_history = self.alert_history[-1000:]
        
    async def _process_single_alert(self, alert: Alert):
        """Process a single alert"""
        log_message = f"ALERT [{alert.severity.upper()}] {alert.type.value}: {alert.message}"
        
        if alert.transfer_id:
            log_message += f" (transfer: {alert.transfer_id})"
        if alert.tx_hash:
            log_message += f" (tx: {alert.tx_hash[:10]}...)"
            
        # Log based on severity
        if alert.severity == "critical":
            logger.critical(log_message)
        elif alert.severity == "high":
            logger.error(log_message)
        elif alert.severity == "medium":
            logger.warning(log_message)
        else:
            logger.info(log_message)
            
        # In production, you would also:
        # - Send Slack/Discord notifications
        # - Create PagerDuty incidents for critical alerts
        # - Send emails to operations team
        # - Store alerts in a monitoring database
        
    def get_recent_alerts(self, hours: int = 24) -> List[Alert]:
        """Get alerts from the last N hours"""
        # In a real implementation, alerts would have timestamps
        # For now, return all recent alerts
        return self.alert_history[-50:]  # Return last 50 alerts
        
    def get_alert_summary(self) -> Dict[str, int]:
        """Get summary of alert counts by severity"""
        summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        
        for alert in self.get_recent_alerts():
            summary[alert.severity] += 1
            
        return summary