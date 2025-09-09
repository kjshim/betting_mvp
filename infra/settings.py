from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = Field(default="postgresql+psycopg://user:pass@localhost:5432/app")
    redis_url: str = Field(default="redis://localhost:6379/0")
    timezone: str = Field(default="America/New_York")
    fee_bps: int = Field(default=100, ge=0, le=10000)
    settle_grace_min: int = Field(default=30, ge=1)
    close_fetch_delay_min: int = Field(default=5, ge=1)
    admin_password: str = Field(default="admin2024!")

    # Authentication
    jwt_secret: str = Field(default="dev-jwt-secret-change-in-production")
    session_secret: str = Field(default="dev-session-secret-change-in-production")
    argon2_memory_cost: int = Field(default=65536)

    # Solana configuration
    solana_rpc_url: str = Field(default="http://localhost:8899")
    solana_usdc_mint: str = Field(default="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")  # Mainnet USDC
    solana_min_conf: int = Field(default=1)
    solana_derive_seed: str = Field(default="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

    class Config:
        env_file = ".env"


settings = Settings()