import os
import logging
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_secret(secret_id: str, project_id: str) -> str:
    """Get secret from Google Secret Manager"""
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        logger.info(f"Successfully retrieved secret: {secret_id}")
        return secret_value
    except ImportError:
        logger.warning("Google Cloud Secret Manager client not available, using environment variables")
        return os.environ.get(secret_id.upper().replace("-", "_"), "")
    except Exception as e:
        logger.error(f"Error getting secret {secret_id}: {e}")
        # Fallback to environment variable
        return os.environ.get(secret_id.upper().replace("-", "_"), "")


class ProductionSettings(BaseSettings):
    """Production settings with Google Cloud integration"""
    
    # Google Cloud Project
    project_id: str = Field(default_factory=lambda: os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    
    # Environment
    environment: str = Field(default="production")
    
    # Database - will be loaded from Secret Manager
    database_url: str = Field(default="")
    
    # Redis - will be loaded from Secret Manager  
    redis_url: str = Field(default="")
    
    # Application settings
    timezone: str = Field(default="America/New_York")
    fee_bps: int = Field(default=100, ge=0, le=10000)
    settle_grace_min: int = Field(default=30, ge=1)
    close_fetch_delay_min: int = Field(default=5, ge=1)
    
    # Authentication - will be loaded from Secret Manager
    jwt_secret: str = Field(default="")
    session_secret: str = Field(default="")
    admin_password: str = Field(default="")
    argon2_memory_cost: int = Field(default=65536)

    # Solana configuration - mainnet settings
    solana_rpc_url: str = Field(default="https://api.mainnet-beta.solana.com")
    solana_usdc_mint: str = Field(default="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")  # Mainnet USDC
    solana_min_conf: int = Field(default=15)  # Higher confirmations for mainnet
    solana_derive_seed: str = Field(default="")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Load secrets from Google Secret Manager if in GCP
        if self.project_id:
            logger.info(f"Loading secrets for project: {self.project_id}")
            self._load_secrets()
        else:
            logger.warning("No project ID found, using environment variables")

    def _load_secrets(self):
        """Load secrets from Google Secret Manager"""
        secrets_to_load = {
            'database_url': 'database-url',
            'redis_url': 'redis-url', 
            'jwt_secret': 'jwt-secret',
            'session_secret': 'session-secret',
            'admin_password': 'admin-password',
            'solana_derive_seed': 'solana-derive-seed'
        }
        
        for attr_name, secret_name in secrets_to_load.items():
            try:
                secret_value = get_secret(secret_name, self.project_id)
                if secret_value:
                    setattr(self, attr_name, secret_value)
                    logger.info(f"Loaded secret: {secret_name}")
                else:
                    logger.warning(f"Empty secret value for: {secret_name}")
            except Exception as e:
                logger.error(f"Failed to load secret {secret_name}: {e}")

    class Config:
        env_file = ".env"
        env_prefix = ""


# Create settings instance
def get_settings() -> ProductionSettings:
    """Get production settings instance"""
    return ProductionSettings()


# For backwards compatibility
settings = get_settings()