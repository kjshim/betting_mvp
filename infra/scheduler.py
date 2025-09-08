import datetime
import logging
from typing import Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.oracle import MockOracle, PriceOracle
from domain.models import Round, RoundStatus, RoundResult
from domain.services import BettingService, LedgerService, RoundScheduler, SettlementService
from infra.db import AsyncSessionLocal
from infra.settings import settings

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, oracle: Optional[PriceOracle] = None):
        self.oracle = oracle or MockOracle()
        self.scheduler = self._create_scheduler()

    def _create_scheduler(self) -> AsyncIOScheduler:
        """Create and configure APScheduler"""
        jobstores = {
            'default': RedisJobStore(
                host='localhost' if 'localhost' in settings.redis_url else 'redis',
                port=6379,
                db=1
            )
        }
        
        executors = {
            'default': AsyncIOExecutor(),
        }
        
        job_defaults = {
            'coalesce': False,
            'max_instances': 3
        }

        scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=pytz.timezone(settings.timezone)
        )
        
        return scheduler

    async def start(self):
        """Start the scheduler and schedule daily settlement job"""
        self.scheduler.start()
        
        # Schedule daily settlement at 16:05 ET
        self.scheduler.add_job(
            self.settle_current_round,
            'cron',
            hour=16,
            minute=settings.close_fetch_delay_min,
            timezone=pytz.timezone(settings.timezone),
            id='daily_settlement',
            replace_existing=True
        )
        
        logger.info("Scheduler started with daily settlement at 16:05 ET")

    async def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

    async def settle_current_round(self):
        """Settle the current locked round"""
        async with AsyncSessionLocal() as db:
            try:
                # Find the current locked round
                result = await db.execute(
                    select(Round)
                    .where(Round.status == RoundStatus.LOCKED)
                    .order_by(Round.start_ts.desc())
                    .limit(1)
                )
                round_obj = result.scalar_one_or_none()
                
                if not round_obj:
                    logger.info("No locked round found for settlement")
                    return

                # Parse date from round code
                date = datetime.datetime.strptime(round_obj.code, "%Y%m%d").date()
                
                # Create services
                ledger = LedgerService(db)
                betting = BettingService(db, ledger)
                settlement = SettlementService(db, ledger, betting)
                scheduler = RoundScheduler(db, self.oracle, settlement)
                
                # Attempt automatic settlement
                success = await scheduler.settle_round_auto(round_obj.id, date)
                
                if success:
                    await db.commit()
                    logger.info(f"Successfully settled round {round_obj.code}")
                else:
                    # Check if grace period has expired
                    now = datetime.datetime.now(pytz.timezone(settings.timezone))
                    grace_deadline = round_obj.settle_ts + datetime.timedelta(minutes=settings.settle_grace_min)
                    
                    if now > grace_deadline:
                        # Mark round as VOID and refund
                        logger.warning(f"Oracle failed for round {round_obj.code}, marking as VOID")
                        await settlement.settle_round(round_obj.id, RoundResult.VOID)
                        await db.commit()
                        logger.info(f"Round {round_obj.code} marked as VOID - all bets refunded")
                    else:
                        # Retry later
                        logger.warning(f"Oracle temporarily unavailable for round {round_obj.code}, will retry")
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Settlement failed: {e}")
                raise

    async def lock_round(self, round_code: str):
        """Lock a specific round"""
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(Round).where(Round.code == round_code)
                )
                round_obj = result.scalar_one_or_none()
                
                if not round_obj:
                    logger.error(f"Round {round_code} not found")
                    return False
                
                if round_obj.status != RoundStatus.OPEN:
                    logger.error(f"Round {round_code} is not open (status: {round_obj.status})")
                    return False
                
                round_obj.status = RoundStatus.LOCKED
                await db.commit()
                
                logger.info(f"Locked round {round_code}")
                return True
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to lock round {round_code}: {e}")
                return False

    def schedule_round_lock(self, round_code: str, lock_time: datetime.datetime):
        """Schedule a round to be locked at a specific time"""
        self.scheduler.add_job(
            self.lock_round,
            'date',
            run_date=lock_time,
            args=[round_code],
            id=f'lock_round_{round_code}',
            replace_existing=True
        )
        
        logger.info(f"Scheduled round {round_code} to lock at {lock_time}")

    def get_scheduler_status(self) -> dict:
        """Get scheduler status and job information"""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                'id': job.id,
                'next_run': job.next_run_time,
                'trigger': str(job.trigger),
            })
        
        return {
            'running': self.scheduler.running,
            'jobs': jobs
        }