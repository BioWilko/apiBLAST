from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    APP_ENV: str = "development"
    APP_VERSION: str = "2.0.0"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "changeme"

    # Metadata database
    DATABASE_URL: str = "sqlite:///./apiblast.db"

    # Redis (broker + rate-limit store)
    REDIS_URL: str = "redis://localhost:6379/0"

    # MMseqs2 binary and data locations
    MMSEQS_BIN: Path = Path("/usr/local/bin/mmseqs")
    RESULT_DIR: Path = Path("/data/results")
    DB_CONFIG: Path = Path("databases.yml")

    # MMseqs2 execution
    MMSEQS_THREADS: int = 1
    MMSEQS_GPU_ENABLED: bool = False

    # Per-job execution limits
    JOB_SOFT_TIMEOUT_S: int = 3600
    JOB_HARD_TIMEOUT_S: int = 3900
    MAX_QUERY_LENGTH_NT: int = 500_000
    MAX_QUERY_LENGTH_AA: int = 100_000
    MAX_SEQUENCES_PER_JOB: int = 100

    # Queue / concurrency
    CELERY_CONCURRENCY: int = 4
    MAX_QUEUE_DEPTH: int = 16
    MAX_CONCURRENT_DBS: int = 3
    MEMORY_FLOOR_MB: int = 512

    # Result retention
    RESULT_TTL_S: int = 86_400

    # Rate limiting
    RATE_LIMIT_SUBMIT_PER_MINUTE: int = 10
    RATE_LIMIT_SUBMIT_PER_HOUR: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
