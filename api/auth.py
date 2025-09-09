import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status, Response, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from auth.service import AuthService
from auth.jwt import JWTService
from auth.models import Session as AuthSession
from domain.models import User
from infra.db import get_async_db

router = APIRouter(prefix="/auth", tags=["Authentication"])
templates = Jinja2Templates(directory="templates")
security = HTTPBearer()
jwt_service = JWTService()


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


# GET endpoints for forms
@router.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    """Serve signup form"""
    return templates.TemplateResponse("signup.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    """Serve login form"""
    return templates.TemplateResponse("login.html", {"request": request})


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_db)
) -> User:
    """Get current authenticated user from JWT token"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    # Decode token
    payload = jwt_service.decode_token(credentials.credentials)
    if not payload or not jwt_service.is_access_token(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    # Check if session exists
    auth_service = AuthService(db)
    session = await auth_service.get_session(payload["jti"])
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired"
        )

    # Get user
    user_id = uuid.UUID(payload["sub"])
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


@router.post("/signup", response_model=TokenResponse)
async def signup(
    request: SignupRequest,
    response: Response,
    db: AsyncSession = Depends(get_async_db)
):
    """Register new user"""
    auth_service = AuthService(db)
    
    try:
        user = await auth_service.create_user(request.email, request.password)
        await db.commit()
        
        # Create session and tokens
        jti = str(uuid.uuid4())
        session = await auth_service.create_session(user.id, jti)
        await db.commit()
        
        access_token = jwt_service.create_access_token(user.id, jti)
        refresh_token = jwt_service.create_refresh_token(user.id, jti)
        
        # Set session cookie
        response.set_cookie(
            key="session_id",
            value=jti,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=60 * 60 * 24 * 7  # 7 days
        )
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserResponse(
                id=str(user.id),
                email=user.email,
                created_at=user.created_at
            )
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_async_db)
):
    """Login user"""
    auth_service = AuthService(db)
    
    user = await auth_service.authenticate(request.email, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    await db.commit()  # Commit login timestamp update
    
    # Create session and tokens
    jti = str(uuid.uuid4())
    session = await auth_service.create_session(user.id, jti)
    await db.commit()
    
    access_token = jwt_service.create_access_token(user.id, jti)
    refresh_token = jwt_service.create_refresh_token(user.id, jti)
    
    # Set session cookie
    response.set_cookie(
        key="session_id",
        value=jti,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 7  # 7 days
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            created_at=user.created_at
        )
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_db)
):
    """Refresh access token"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    # Decode refresh token
    payload = jwt_service.decode_token(credentials.credentials)
    if not payload or not jwt_service.is_refresh_token(credentials.credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    # Check session
    auth_service = AuthService(db)
    session = await auth_service.get_session(payload["jti"])
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired"
        )

    # Get user
    user_id = uuid.UUID(payload["sub"])
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    # Create new access token (same session)
    access_token = jwt_service.create_access_token(user.id, payload["jti"])
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=credentials.credentials,  # Return same refresh token
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            created_at=user.created_at
        )
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Logout user"""
    # Get session ID from cookie or token
    session_id = request.cookies.get("session_id")
    
    if session_id:
        auth_service = AuthService(db)
        await auth_service.revoke_session(session_id)
        await db.commit()
    
    # Clear session cookie
    response.delete_cookie("session_id")
    
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current user information"""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        created_at=current_user.created_at
    )


# Mock API Key classes for compatibility (not implemented yet)
class ApiKey:
    pass

class ApiKeyAuth:
    pass

class ApiKeyRole:
    pass

# Mock auth functions for compatibility
async def require_admin():
    """Placeholder admin auth function"""
    raise HTTPException(status_code=501, detail="Admin API keys not implemented")

async def require_user():
    """Placeholder user auth function"""  
    raise HTTPException(status_code=501, detail="User API keys not implemented")

async def optional_auth():
    """Placeholder optional auth function"""
    return None