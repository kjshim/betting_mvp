import uuid
from datetime import datetime, timedelta
from typing import Optional, Union

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from auth.models import UserAuth, Session as AuthSession
from domain.models import User


class AuthService:
    def __init__(self, db: Union[Session, AsyncSession]):
        self.db = db
        self.pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

    def hash_password(self, password: str) -> str:
        """Hash password using Argon2"""
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash"""
        return self.pwd_context.verify(plain_password, hashed_password)

    async def create_user(self, email: str, password: str) -> User:
        """Create new user with authentication"""
        # Check if user already exists
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(UserAuth).where(UserAuth.email == email)
            )
            existing_auth = result.scalar_one_or_none()
        else:
            existing_auth = self.db.execute(
                select(UserAuth).where(UserAuth.email == email)
            ).scalar_one_or_none()

        if existing_auth:
            raise ValueError(f"User with email {email} already exists")

        # Create user
        user = User(email=email)
        self.db.add(user)
        
        if isinstance(self.db, AsyncSession):
            await self.db.flush()
        else:
            self.db.flush()

        # Create auth
        password_hash = self.hash_password(password)
        user_auth = UserAuth(
            user_id=user.id,
            email=email,
            password_hash=password_hash
        )
        self.db.add(user_auth)

        return user

    async def authenticate(self, email: str, password: str) -> Optional[User]:
        """Authenticate user with email/password"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(UserAuth).where(UserAuth.email == email, UserAuth.is_active == True)
            )
            user_auth = result.scalar_one_or_none()
        else:
            user_auth = self.db.execute(
                select(UserAuth).where(UserAuth.email == email, UserAuth.is_active == True)
            ).scalar_one_or_none()

        if not user_auth:
            return None

        if not self.verify_password(password, user_auth.password_hash):
            return None

        # Update last login
        user_auth.last_login_at = datetime.utcnow()

        # Return user
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(User).where(User.id == user_auth.user_id)
            )
            return result.scalar_one_or_none()
        else:
            return self.db.get(User, user_auth.user_id)

    async def create_session(self, user_id: uuid.UUID, jwt_id: str, expires_in_hours: int = 24) -> AuthSession:
        """Create a new session"""
        expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
        session = AuthSession(
            user_id=user_id,
            jwt_id=jwt_id,
            expires_at=expires_at
        )
        self.db.add(session)
        return session

    async def get_session(self, jwt_id: str) -> Optional[AuthSession]:
        """Get session by JWT ID"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(AuthSession).where(
                    AuthSession.jwt_id == jwt_id,
                    AuthSession.expires_at > datetime.utcnow()
                )
            )
            return result.scalar_one_or_none()
        else:
            return self.db.execute(
                select(AuthSession).where(
                    AuthSession.jwt_id == jwt_id,
                    AuthSession.expires_at > datetime.utcnow()
                )
            ).scalar_one_or_none()

    async def revoke_session(self, jwt_id: str) -> bool:
        """Revoke a session"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(AuthSession).where(AuthSession.jwt_id == jwt_id)
            )
            session = result.scalar_one_or_none()
        else:
            session = self.db.execute(
                select(AuthSession).where(AuthSession.jwt_id == jwt_id)
            ).scalar_one_or_none()

        if session:
            if isinstance(self.db, AsyncSession):
                await self.db.delete(session)
            else:
                self.db.delete(session)
            return True
        return False

    async def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        if isinstance(self.db, AsyncSession):
            result = await self.db.execute(
                select(AuthSession).where(AuthSession.expires_at <= datetime.utcnow())
            )
            expired_sessions = result.scalars().all()
            for session in expired_sessions:
                await self.db.delete(session)
        else:
            expired_sessions = self.db.execute(
                select(AuthSession).where(AuthSession.expires_at <= datetime.utcnow())
            ).scalars().all()
            for session in expired_sessions:
                self.db.delete(session)