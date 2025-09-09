import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import jwt
from jwt.exceptions import InvalidTokenError

from infra.settings import settings


class JWTService:
    def __init__(self):
        self.secret_key = settings.jwt_secret
        self.algorithm = "HS256"
        self.access_token_expire_minutes = 30
        self.refresh_token_expire_hours = 24 * 7  # 7 days

    def create_access_token(self, user_id: uuid.UUID, jti: str) -> str:
        """Create short-lived access token"""
        now = datetime.utcnow()
        payload = {
            "sub": str(user_id),
            "jti": jti,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=self.access_token_expire_minutes),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(self, user_id: uuid.UUID, jti: str) -> str:
        """Create long-lived refresh token"""
        now = datetime.utcnow()
        payload = {
            "sub": str(user_id),
            "jti": jti,
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(hours=self.refresh_token_expire_hours),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Decode and validate JWT token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except InvalidTokenError:
            return None

    def get_user_id_from_token(self, token: str) -> Optional[uuid.UUID]:
        """Extract user ID from valid token"""
        payload = self.decode_token(token)
        if payload and "sub" in payload:
            try:
                return uuid.UUID(payload["sub"])
            except ValueError:
                return None
        return None

    def get_jti_from_token(self, token: str) -> Optional[str]:
        """Extract JTI from valid token"""
        payload = self.decode_token(token)
        if payload and "jti" in payload:
            return payload["jti"]
        return None

    def is_access_token(self, token: str) -> bool:
        """Check if token is an access token"""
        payload = self.decode_token(token)
        return payload is not None and payload.get("type") == "access"

    def is_refresh_token(self, token: str) -> bool:
        """Check if token is a refresh token"""
        payload = self.decode_token(token)
        return payload is not None and payload.get("type") == "refresh"

    def is_token_expired(self, token: str) -> bool:
        """Check if token is expired"""
        payload = self.decode_token(token)
        if not payload:
            return True
        
        exp = payload.get("exp")
        if not exp:
            return True
            
        return datetime.utcnow().timestamp() > exp