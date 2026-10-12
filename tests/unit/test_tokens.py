"""Unit tests for priority token storage and the admin CLI."""
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import admin
from app.core.database import Base
from app.models.db import PriorityToken
from app.services import tokens


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db(session_factory):
    s = session_factory()
    yield s
    s.close()


def test_create_stores_hash_not_token(db):
    token, raw = tokens.create(db, "alice")
    assert raw.startswith("apb_")
    assert len(raw) > 40
    assert token.prefix == raw[:12]
    assert token.token_hash == tokens.hash_token(raw)
    assert raw not in {token.token_hash, token.prefix, token.label}


def test_tokens_are_unique(db):
    _, a = tokens.create(db, "a")
    _, b = tokens.create(db, "b")
    assert a != b


def test_verify(db):
    token, raw = tokens.create(db, "alice")
    assert tokens.verify(db, raw).id == token.id
    assert tokens.verify(db, raw + "x") is None
    assert tokens.verify(db, "") is None


def test_revoke_by_id_and_prefix(db):
    a, raw_a = tokens.create(db, "a")
    b, raw_b = tokens.create(db, "b")
    assert tokens.revoke(db, a.id).id == a.id
    assert tokens.revoke(db, b.prefix).id == b.id
    assert tokens.verify(db, raw_a) is None
    assert tokens.verify(db, raw_b) is None


def test_revoke_unknown_returns_none(db):
    assert tokens.revoke(db, "nope") is None


def test_revoke_ambiguous_prefix_raises(db):
    a, _ = tokens.create(db, "a")
    b, _ = tokens.create(db, "b")
    b.prefix = a.prefix
    db.commit()
    with pytest.raises(ValueError):
        tokens.revoke(db, a.prefix)


def test_admin_cli_create_list_revoke(session_factory, capsys):
    with patch("app.admin.SessionLocal", session_factory):
        assert admin.main(["tokens", "create", "--label", "alice (outbreak team)"]) == 0
        raw = capsys.readouterr().out.strip().splitlines()[-1]
        assert raw.startswith("apb_")

        assert admin.main(["tokens", "list"]) == 0
        listing = capsys.readouterr().out
        assert "alice (outbreak team)" in listing
        assert raw[:12] in listing
        assert raw not in listing

        assert admin.main(["tokens", "revoke", raw[:12]]) == 0
        capsys.readouterr()
        assert admin.main(["tokens", "revoke", "nope"]) == 1

    with session_factory() as s:
        assert s.query(PriorityToken).one().revoked_at is not None
