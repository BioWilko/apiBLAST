"""Server administration commands.

Usage:
    python -m app.admin tokens create --label "alice (outbreak team)"
    python -m app.admin tokens list
    python -m app.admin tokens revoke <id-or-prefix>
"""
import argparse
import sys

from app.core.database import SessionLocal
from app.services import tokens


def _create(args) -> int:
    with SessionLocal() as db:
        token, raw = tokens.create(db, args.label)
        print(f"Created priority token {token.id} ({args.label})")
    print("Token (shown once, store it securely):")
    print(raw)
    return 0


def _list(args) -> int:
    with SessionLocal() as db:
        rows = tokens.list_tokens(db)
        if not rows:
            print("No priority tokens")
            return 0
        print(f"{'ID':36}  {'PREFIX':12}  {'CREATED':19}  {'REVOKED':19}  LABEL")
        for t in rows:
            revoked = t.revoked_at.strftime("%Y-%m-%d %H:%M:%S") if t.revoked_at else "-"
            print(
                f"{t.id:36}  {t.prefix:12}  {t.created_at:%Y-%m-%d %H:%M:%S}  "
                f"{revoked:19}  {t.label}"
            )
    return 0


def _revoke(args) -> int:
    with SessionLocal() as db:
        try:
            token = tokens.revoke(db, args.token)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        if token is None:
            print(f"No token matches {args.token!r}", file=sys.stderr)
            return 1
        print(f"Revoked priority token {token.id} ({token.label})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.admin", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="group", required=True)

    tok = sub.add_parser("tokens", help="Manage priority tokens")
    tok_sub = tok.add_subparsers(dest="command", required=True)
    create = tok_sub.add_parser("create", help="Create a token and print it once")
    create.add_argument("--label", required=True, help="Who the token is for")
    create.set_defaults(func=_create)
    lst = tok_sub.add_parser("list", help="List tokens (never shows the token itself)")
    lst.set_defaults(func=_list)
    revoke = tok_sub.add_parser("revoke", help="Revoke a token")
    revoke.add_argument("token", help="Token id or prefix, as shown by 'tokens list'")
    revoke.set_defaults(func=_revoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
