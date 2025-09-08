import hashlib
import secrets
from enum import Enum
from typing import Optional

from fastapi import HTTPException, Security, status, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Column, DateTime, String, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from infra.db import Base, get_async_db


class ApiKeyRole(str, Enum):
    USER = "user"           # Can place bets, check balances
    ADMIN = "admin"         # Can manage rounds, access all endpoints  
    READONLY = "readonly"   # Can only read data (monitoring, analytics)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=lambda: secrets.token_hex(16))
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)  # For user-level keys
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(String(10), default="true")


class ApiKeyAuth:
    def __init__(self):
        self.security = HTTPBearer(auto_error=False)

    @staticmethod
    def generate_api_key() -> str:
        """Generate a new API key"""
        return f"bk_{secrets.token_urlsafe(32)}"

    @staticmethod
    def hash_key(api_key: str) -> str:
        """Hash an API key for storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()

    async def get_current_api_key(
        self, 
        credentials: Optional[HTTPAuthorizationCredentials] = Security(HTTPBearer(auto_error=False)),
        db: AsyncSession = Depends(get_async_db)
    ) -> Optional[ApiKey]:
        """Get current API key from request"""
        if not credentials:
            return None

        if not credentials.credentials.startswith("bk_"):
            return None

        key_hash = self.hash_key(credentials.credentials)
        
        result = await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == "true"
            )
        )
        api_key = result.scalar_one_or_none()
        
        if api_key:
            # Update last_used timestamp
            api_key.last_used = func.now()
            
        return api_key

    def require_role(self, required_role: ApiKeyRole):
        """Decorator to require specific role"""
        async def dependency(
            credentials: HTTPAuthorizationCredentials = Security(self.security),
            db: AsyncSession = Depends(get_async_db)
        ) -> ApiKey:
            if not credentials:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            api_key = await self.get_current_api_key(credentials, db)
            
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Check role hierarchy: admin > user > readonly
            role_hierarchy = {
                ApiKeyRole.READONLY: 1,
                ApiKeyRole.USER: 2,
                ApiKeyRole.ADMIN: 3,
            }
            
            user_level = role_hierarchy.get(ApiKeyRole(api_key.role), 0)
            required_level = role_hierarchy.get(required_role, 999)
            
            if user_level < required_level:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role '{required_role}' required, have '{api_key.role}'",
                )

            return api_key
            
        return dependency

    def optional_auth(self):
        """Optional authentication for public endpoints"""
        async def dependency(
            credentials: Optional[HTTPAuthorizationCredentials] = Security(HTTPBearer(auto_error=False)),
            db: AsyncSession = Depends(get_async_db)
        ) -> Optional[ApiKey]:
            if credentials:
                return await self.get_current_api_key(credentials, db)
            return None
            
        return dependency


# Global auth instance
auth = ApiKeyAuth()

# Common role requirements
require_admin = auth.require_role(ApiKeyRole.ADMIN)
require_user = auth.require_role(ApiKeyRole.USER)
require_readonly = auth.require_role(ApiKeyRole.READONLY)
optional_auth = auth.optional_auth()