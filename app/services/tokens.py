"""Create, verify and revoke priority tokens.

Tokens are random and high-entropy, so an unsalted SHA-256 hash is enough to
keep the stored form useless if the database leaks.
"""
import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.db import PriorityToken

TOKEN_PREFIX = "apb_"
_DISPLAY_LEN = 12


def hash_token(raw: str) -> str:
    """Return the hex SHA-256 digest of a raw token."""
    return hashlib.sha256(raw.encode()).hexdigest()


def create(db: Session, label: str) -> tuple[PriorityToken, str]:
    """Create and store a new token.

    Args:
        db: Database session; committed on success.
        label: Who the token is for, shown in listings.

    Returns:
        The stored token row and the raw token. The raw token is not stored
        and cannot be recovered later.
    """
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = PriorityToken(label=label, prefix=raw[:_DISPLAY_LEN], token_hash=hash_token(raw))
    db.add(token)
    db.commit()
    return token, raw


def verify(db: Session, raw: str) -> PriorityToken | None:
    """Return the active token matching ``raw``, or None if unknown or revoked."""
    return (
        db.query(PriorityToken)
        .filter(PriorityToken.token_hash == hash_token(raw), PriorityToken.revoked_at.is_(None))
        .one_or_none()
    )


def list_tokens(db: Session) -> list[PriorityToken]:
    """Return all tokens, oldest first."""
    return db.query(PriorityToken).order_by(PriorityToken.created_at).all()


def revoke(db: Session, id_or_prefix: str) -> PriorityToken | None:
    """Revoke the token with this id or display prefix.

    Args:
        db: Database session; committed on success.
        id_or_prefix: The token's id, or the prefix shown by ``list_tokens``.

    Returns:
        The revoked token, or None if nothing matched.

    Raises:
        ValueError: If the prefix matches more than one token.
    """
    matches = (
        db.query(PriorityToken)
        .filter(or_(PriorityToken.id == id_or_prefix, PriorityToken.prefix == id_or_prefix))
        .all()
    )
    if len(matches) > 1:
        raise ValueError(f"{id_or_prefix!r} matches {len(matches)} tokens; use the id")
    if not matches:
        return None
    token = matches[0]
    if token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return token
