"""
Compact admin interface for betting MVP maintenance.

Provides a simple web UI with session-based authentication for:
- System health monitoring
- User management
- Transaction monitoring
- API key management
- Round management
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from domain.models import (
    User, Round, Bet, Transfer, LedgerEntry, 
    RoundStatus, BetStatus, TransferStatus, TransferType, BetSide
)
from domain.services import LedgerService, BettingService, TvlService
from infra.db import get_async_db
from infra.monitoring import HealthChecker, prometheus_metrics
from infra.settings import settings


router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")

# Add datetime to all templates globally
templates.env.globals['datetime'] = datetime

# Simple admin credentials from environment
ADMIN_PASSWORD = settings.admin_password

def check_admin_session(admin_session: str = Cookie(None)):
    """Check if user has valid admin session"""
    if admin_session != "admin_logged_in":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please login to access admin panel"
        )
    return True



@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Admin login page"""
    return templates.TemplateResponse("admin/login.html", {
        "request": request
    })

@router.post("/login", response_class=HTMLResponse)
async def admin_login(
    request: Request,
    password: str = Form(...),
):
    """Handle admin login"""
    if password == ADMIN_PASSWORD:
        response = RedirectResponse(url="/admin/", status_code=302)
        response.set_cookie(key="admin_session", value="admin_logged_in", httponly=True, max_age=86400)  # 24 hours
        return response
    else:
        return templates.TemplateResponse("admin/login.html", {
            "request": request,
            "error": "Invalid password"
        })

@router.get("/logout")
async def admin_logout():
    """Logout admin"""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(key="admin_session")
    return response

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """Main admin dashboard"""
    
    # Get system health
    health_checker = HealthChecker(db)
    health = await health_checker.perform_full_health_check()
    
    # Get basic stats
    user_count = await db.scalar(select(func.count()).select_from(User))
    
    # Recent rounds
    recent_rounds = await db.execute(
        select(Round).order_by(desc(Round.start_ts)).limit(5)
    )
    rounds = recent_rounds.scalars().all()
    
    # Recent bets (last 24h)
    yesterday = datetime.utcnow() - timedelta(days=1)
    recent_bets_count = await db.scalar(
        select(func.count()).where(
            and_(Bet.created_at >= yesterday, Bet.status != BetStatus.REFUNDED)
        )
    )
    
    # Pending transfers
    pending_deposits = await db.scalar(
        select(func.count()).where(
            and_(Transfer.type == TransferType.DEPOSIT, Transfer.status == TransferStatus.PENDING)
        )
    )
    
    pending_withdrawals = await db.scalar(
        select(func.count()).where(
            and_(Transfer.type == TransferType.WITHDRAWAL, Transfer.status == TransferStatus.PENDING)
        )
    )
    
    # TVL
    ledger_service = LedgerService(db)
    tvl_service = TvlService(db, ledger_service)
    tvl_data = await tvl_service.get_tvl()
    
    # Create stats object with all needed fields
    class Stats:
        def __init__(self):
            self.user_count = user_count or 0
            self.recent_bets_24h = recent_bets_count or 0
            self.pending_deposits = pending_deposits or 0
            self.pending_withdrawals = pending_withdrawals or 0
            self.tvl_locked_usdc = tvl_data["locked_u"] / 1_000_000 if tvl_data else 0
            self.total_cash_usdc = tvl_data["total_cash_u"] / 1_000_000 if tvl_data else 0
            self.active_transfers = (pending_deposits or 0) + (pending_withdrawals or 0)
            self.round_count = len(rounds)
            self.total_volume_usdc = 0
            self.active_rounds = len([r for r in rounds if r.status in [RoundStatus.OPEN, RoundStatus.LOCKED]])

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "health": health,
        "stats": Stats(),
        "recent_operations": [],
        "health_summary": {"healthy": 0, "degraded": 0, "unhealthy": 0}
    })


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    page: int = 1,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """User management page"""
    
    page_size = 20
    offset = (page - 1) * page_size
    
    # Build query
    query = select(User)
    if search:
        query = query.where(User.email.ilike(f"%{search}%"))
    
    # Get users
    result = await db.execute(
        query.order_by(desc(User.created_at)).offset(offset).limit(page_size)
    )
    users = result.scalars().all()
    
    # Get user balances
    ledger_service = LedgerService(db)
    user_data = []
    
    for user in users:
        balance = await ledger_service.get_balance_async(user.id, "cash")
        locked = await ledger_service.get_balance_async(user.id, "locked")
        
        # Count bets
        bet_count = await db.scalar(
            select(func.count()).where(Bet.user_id == user.id)
        )
        
        user_data.append({
            "user": user,
            "balance_usdc": balance / 1_000_000,
            "locked_usdc": locked / 1_000_000,
            "bet_count": bet_count
        })
    
    # Total count for pagination
    total = await db.scalar(select(func.count()).select_from(User))
    total_pages = (total + page_size - 1) // page_size
    
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "users": user_data,
        "page": page,
        "total_pages": total_pages,
        "search": search or "",
        "has_prev": page > 1,
        "has_next": page < total_pages
    })


@router.get("/transactions", response_class=HTMLResponse)
async def admin_transactions(
    request: Request,
    page: int = 1,
    status_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """Transaction monitoring page"""
    
    page_size = 50
    offset = (page - 1) * page_size
    
    # Build query
    query = select(Transfer, User.email).join(User, Transfer.user_id == User.id)
    
    if status_filter:
        query = query.where(Transfer.status == status_filter)
    if type_filter:
        query = query.where(Transfer.type == type_filter)
        
    # Get transactions
    result = await db.execute(
        query.order_by(desc(Transfer.created_at)).offset(offset).limit(page_size)
    )
    transactions = result.all()
    
    # Total count
    count_query = select(func.count()).select_from(Transfer)
    if status_filter:
        count_query = count_query.where(Transfer.status == status_filter)
    if type_filter:
        count_query = count_query.where(Transfer.type == type_filter)
        
    total = await db.scalar(count_query)
    total_pages = (total + page_size - 1) // page_size
    
    return templates.TemplateResponse("admin/transactions.html", {
        "request": request,
        "transactions": transactions,
        "page": page,
        "total_pages": total_pages,
        "status_filter": status_filter or "",
        "type_filter": type_filter or "",
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "transfer_statuses": [s.value for s in TransferStatus],
        "transfer_types": [t.value for t in TransferType]
    })


@router.get("/rounds", response_class=HTMLResponse)
async def admin_rounds(
    request: Request,
    page: int = 1,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """Round management page"""
    
    page_size = 20
    offset = (page - 1) * page_size
    
    # Get rounds with bet counts and pool sizes
    result = await db.execute(
        select(
            Round,
            func.count(Bet.id).label("bet_count"),
            func.sum(Bet.stake_u).label("total_volume")
        )
        .outerjoin(Bet, Round.id == Bet.round_id)
        .group_by(Round.id)
        .order_by(desc(Round.start_ts))
        .offset(offset)
        .limit(page_size)
    )
    
    rounds_data = []
    betting_service = BettingService(db, LedgerService(db))
    
    for round_obj, bet_count, total_volume in result.all():
        # Get pool sizes
        up_pool, down_pool = await betting_service.get_round_pools(round_obj.id)
        
        rounds_data.append({
            "round": round_obj,
            "bet_count": bet_count or 0,
            "total_volume_usdc": (total_volume or 0) / 1_000_000,
            "up_pool_usdc": up_pool / 1_000_000,
            "down_pool_usdc": down_pool / 1_000_000
        })
    
    # Total count
    total = await db.scalar(select(func.count()).select_from(Round))
    total_pages = (total + page_size - 1) // page_size
    
    return templates.TemplateResponse("admin/rounds.html", {
        "request": request,
        "rounds": rounds_data,
        "page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "round_statuses": [s.value for s in RoundStatus]
    })


@router.get("/api-keys", response_class=HTMLResponse)
async def admin_api_keys(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """API key management page"""
    
    # Get all API keys
    result = await db.execute(
        select(ApiKey).order_by(desc(ApiKey.created_at))
    )
    keys = result.scalars().all()
    
    return templates.TemplateResponse("admin/api_keys.html", {
        "request": request,
        "api_keys": keys
    })


@router.post("/api-keys/create")
async def create_api_key(
    name: str = Form(...),
    role: str = Form(...),
    user_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """Create new API key"""
    
    from api.auth import ApiKeyAuth
    
    # Generate new key
    new_api_key = ApiKeyAuth.generate_api_key()
    key_hash = ApiKeyAuth.hash_key(new_api_key)
    
    # Parse user_id if provided
    parsed_user_id = None
    if user_id and user_id.strip():
        try:
            parsed_user_id = uuid.UUID(user_id.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user ID format")
    
    # Create database record
    api_key_record = ApiKey(
        key_hash=key_hash,
        name=name,
        role=role,
        user_id=parsed_user_id
    )
    
    db.add(api_key_record)
    await db.commit()
    
    return RedirectResponse(
        url=f"/admin/api-keys?created_key={new_api_key}&key_id={api_key_record.id}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """Revoke an API key"""
    
    # Find the key
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id)
    )
    api_key_to_revoke = result.scalar_one_or_none()
    
    if not api_key_to_revoke:
        raise HTTPException(status_code=404, detail="API key not found")
    
    # Revoke the key
    api_key_to_revoke.is_active = "false"
    await db.commit()
    
    return RedirectResponse(url="/admin/api-keys", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/system", response_class=HTMLResponse)
async def admin_system(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """System monitoring and health page"""
    
    # Get detailed health check
    health_checker = HealthChecker(db)
    health = await health_checker.perform_full_health_check()
    
    # Get recent errors from Prometheus (if available)
    error_summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    
    # System metrics
    ledger_service = LedgerService(db)
    
    # Check ledger balance
    total_balance = await db.scalar(select(func.sum(LedgerEntry.amount_u)))
    
    # Get database size info (PostgreSQL specific)
    try:
        db_size_result = await db.execute(
            select(func.pg_database_size(func.current_database()))
        )
        db_size_bytes = db_size_result.scalar()
        db_size_mb = db_size_bytes / (1024 * 1024) if db_size_bytes else 0
    except:
        db_size_mb = 0
    
    return templates.TemplateResponse("admin/system.html", {
        "request": request,
        "health": health,
        "system_info": {
            "ledger_balance": total_balance or 0,
            "db_size_mb": db_size_mb,
            "ledger_balanced": (total_balance or 0) == 0
        },
        "error_summary": error_summary
    })


@router.post("/system/reconcile")
async def trigger_reconciliation(
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """Trigger manual reconciliation"""
    
    # This would trigger reconciliation in the background
    # For now, just redirect back with a message
    
    return RedirectResponse(
        url="/admin/system?message=Reconciliation+triggered",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/user/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(check_admin_session)
):
    """Individual user detail page"""
    
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID")
    
    # Get user
    user = await db.get(User, user_uuid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get user balances
    ledger_service = LedgerService(db)
    cash_balance = await ledger_service.get_balance_async(user.id, "cash")
    locked_balance = await ledger_service.get_balance_async(user.id, "locked")
    
    # Get recent bets
    recent_bets = await db.execute(
        select(Bet, Round.code)
        .join(Round, Bet.round_id == Round.id)
        .where(Bet.user_id == user.id)
        .order_by(desc(Bet.created_at))
        .limit(20)
    )
    bets = recent_bets.all()
    
    # Get recent transfers
    recent_transfers = await db.execute(
        select(Transfer)
        .where(Transfer.user_id == user.id)
        .order_by(desc(Transfer.created_at))
        .limit(20)
    )
    transfers = recent_transfers.scalars().all()
    
    return templates.TemplateResponse("admin/user_detail.html", {
        "request": request,
        "user": user,
        "cash_balance_usdc": cash_balance / 1_000_000,
        "locked_balance_usdc": locked_balance / 1_000_000,
        "recent_bets": bets,
        "recent_transfers": transfers
    })