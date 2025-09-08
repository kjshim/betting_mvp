from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = Field(default="postgresql+psycopg://user:pass@localhost:5432/app")
    redis_url: str = Field(default="redis://localhost:6379/0")
    timezone: str = Field(default="America/New_York")
    fee_bps: int = Field(default=100, ge=0, le=10000)
    settle_grace_min: int = Field(default=30, ge=1)
    close_fetch_delay_min: int = Field(default=5, ge=1)

    class Config:
        env_file = ".env"


settings = Settings()