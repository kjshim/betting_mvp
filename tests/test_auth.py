import pytest
import uuid
from datetime import datetime, timedelta

from auth.service import AuthService
from auth.jwt import JWTService
from domain.models import User
from infra.db import SessionLocal


class TestAuthService:
    def test_password_hashing(self):
        """Test password hashing and verification"""
        with SessionLocal() as db:
            auth_service = AuthService(db)
            
            password = "test_password_123"
            hashed = auth_service.hash_password(password)
            
            assert hashed != password
            assert auth_service.verify_password(password, hashed)
            assert not auth_service.verify_password("wrong_password", hashed)

    @pytest.mark.asyncio
    async def test_create_user(self):
        """Test user creation with authentication"""
        with SessionLocal() as db:
            auth_service = AuthService(db)
            
            email = f"test_{uuid.uuid4().hex[:8]}@example.com"
            password = "test_password_123"
            
            user = await auth_service.create_user(email, password)
            db.commit()
            
            assert user.email == email
            assert user.id is not None
            assert user.auth is not None
            assert user.auth.email == email
            assert user.auth.password_hash != password

    @pytest.mark.asyncio
    async def test_authenticate_success(self):
        """Test successful authentication"""
        with SessionLocal() as db:
            auth_service = AuthService(db)
            
            email = f"test_{uuid.uuid4().hex[:8]}@example.com"
            password = "test_password_123"
            
            # Create user
            created_user = await auth_service.create_user(email, password)
            db.commit()
            
            # Authenticate
            authenticated_user = await auth_service.authenticate(email, password)
            
            assert authenticated_user is not None
            assert authenticated_user.id == created_user.id
            assert authenticated_user.email == email

    @pytest.mark.asyncio
    async def test_authenticate_failure(self):
        """Test failed authentication"""
        with SessionLocal() as db:
            auth_service = AuthService(db)
            
            # Try to authenticate non-existent user
            user = await auth_service.authenticate("nonexistent@example.com", "password")
            assert user is None
            
            # Create user and try wrong password
            email = f"test_{uuid.uuid4().hex[:8]}@example.com"
            await auth_service.create_user(email, "correct_password")
            db.commit()
            
            user = await auth_service.authenticate(email, "wrong_password")
            assert user is None

    @pytest.mark.asyncio
    async def test_session_management(self):
        """Test session creation and management"""
        with SessionLocal() as db:
            auth_service = AuthService(db)
            
            user_id = uuid.uuid4()
            jti = str(uuid.uuid4())
            
            # Create session
            session = await auth_service.create_session(user_id, jti)
            db.commit()
            
            assert session.user_id == user_id
            assert session.jwt_id == jti
            assert session.expires_at > datetime.utcnow()
            
            # Get session
            retrieved_session = await auth_service.get_session(jti)
            assert retrieved_session is not None
            assert retrieved_session.id == session.id
            
            # Revoke session
            revoked = await auth_service.revoke_session(jti)
            assert revoked is True
            
            # Should not be able to get revoked session
            retrieved_session = await auth_service.get_session(jti)
            assert retrieved_session is None


class TestJWTService:
    def test_token_creation_and_validation(self):
        """Test JWT token creation and validation"""
        jwt_service = JWTService()
        user_id = uuid.uuid4()
        jti = str(uuid.uuid4())
        
        # Create tokens
        access_token = jwt_service.create_access_token(user_id, jti)
        refresh_token = jwt_service.create_refresh_token(user_id, jti)
        
        assert access_token != refresh_token
        
        # Validate access token
        assert jwt_service.is_access_token(access_token)
        assert not jwt_service.is_refresh_token(access_token)
        
        # Validate refresh token
        assert jwt_service.is_refresh_token(refresh_token)
        assert not jwt_service.is_access_token(refresh_token)
        
        # Extract information
        assert jwt_service.get_user_id_from_token(access_token) == user_id
        assert jwt_service.get_jti_from_token(access_token) == jti

    def test_invalid_token_handling(self):
        """Test handling of invalid tokens"""
        jwt_service = JWTService()
        
        # Invalid token should return None
        assert jwt_service.decode_token("invalid_token") is None
        assert jwt_service.get_user_id_from_token("invalid_token") is None
        assert jwt_service.get_jti_from_token("invalid_token") is None
        
        # Empty token
        assert jwt_service.decode_token("") is None

    def test_token_expiration(self):
        """Test token expiration checking"""
        jwt_service = JWTService()
        user_id = uuid.uuid4()
        jti = str(uuid.uuid4())
        
        # Create fresh token
        access_token = jwt_service.create_access_token(user_id, jti)
        
        # Should not be expired
        assert not jwt_service.is_token_expired(access_token)
        
        # Invalid token should be considered expired
        assert jwt_service.is_token_expired("invalid_token")