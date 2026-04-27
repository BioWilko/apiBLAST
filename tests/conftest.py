"""Shared pytest fixtures."""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

# Use SQLite in-memory for all tests
TEST_DB_URL = "sqlite://"

# Patch settings before any app module is imported
os.environ.setdefault("DATABASE_URL", TEST_DB_URL)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("BLAST_BIN_DIR", "/tmp/fake_blast_bin")
os.environ.setdefault("BLAST_RESULT_DIR", "/tmp/fake_blast_results")


@pytest.fixture(scope="session")
def test_engine():
    from app.core.database import Base
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(test_engine):
    TestingSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db_session, tmp_path):
    from app.main import create_app
    from app.deps import get_db
    from app.config import get_settings

    app = create_app()

    def override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db

    with patch("app.core.limiter.limiter") as mock_limiter, \
         patch("app.config.get_settings") as mock_settings_fn:
        settings = get_settings()
        settings.BLAST_RESULT_DIR = tmp_path
        mock_settings_fn.return_value = settings

        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
