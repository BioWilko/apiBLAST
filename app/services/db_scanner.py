"""Load MMseqs2 database definitions from databases.yml."""
import logging
from datetime import datetime
from pathlib import Path

import yaml

from app.config import get_settings
from app.models.schemas import DatabaseInfo

logger = logging.getLogger(__name__)

_NT_PROGRAMS = ["blastn"]
_AA_PROGRAMS = ["blastp", "blastx"]

# BLAST+ (makeblastdb) volume, index and alias file extensions
_BLAST_EXTS = {".nal", ".ndb", ".nhr", ".nin", ".nsq", ".pal", ".pdb", ".phr", ".pin", ".psq"}

# (database, problem) pairs already logged
_reported: set[tuple[str, str]] = set()


def _is_db_file(path: Path, db_name: str) -> bool:
    """True for <name>, <name>.* and <name>_h[.*] (the MMseqs2 DB, index and header files)."""
    n = path.name
    return any(n == base or n.startswith(f"{base}.") for base in (db_name, f"{db_name}_h"))


def _disk_stats(db_dir: Path, db_name: str) -> tuple[int, datetime | None]:
    """Return (total_size_bytes, newest_mtime) for the files of a database."""
    size = 0
    last_updated: datetime | None = None
    for f in db_dir.glob(f"{db_name}*"):
        if not f.is_file() or not _is_db_file(f, db_name):
            continue
        size += f.stat().st_size
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if last_updated is None or mtime > last_updated:
            last_updated = mtime
    return size, last_updated


def load_databases(config_path: Path | None = None) -> list[DatabaseInfo]:
    """Return database definitions from the YAML config file."""
    if config_path is None:
        config_path = get_settings().DB_CONFIG

    if not config_path.is_file():
        return []

    with config_path.open() as fh:
        data = yaml.safe_load(fh)

    if not data or "databases" not in data:
        return []

    results: list[DatabaseInfo] = []
    for entry in data["databases"]:
        db_type = str(entry.get("type", "nucleotide")).lower()
        program_types = _NT_PROGRAMS if db_type == "nucleotide" else _AA_PROGRAMS

        db_name = entry["name"]
        db_dir = Path(entry["path"])
        try:
            size_bytes, last_updated = _disk_stats(db_dir, db_name)
        except OSError:
            size_bytes, last_updated = 0, None

        _check_format(db_dir, db_name, db_type)

        results.append(
            DatabaseInfo(
                name=db_name,
                description=entry.get("description", ""),
                program_types=program_types,
                path=str(db_dir),
                size_bytes=size_bytes,
                last_updated=last_updated,
            )
        )

    return results


def _report_once(db_name: str, problem: str, level: int, msg: str, *args) -> None:
    if (db_name, problem) not in _reported:
        _reported.add((db_name, problem))
        logger.log(level, msg, *args)


def _check_format(db_dir: Path, db_name: str, db_type: str) -> None:
    """Log configured databases that are not usable MMseqs2 databases."""
    if not db_dir.is_dir():
        return
    target = db_dir / db_name
    if not (db_dir / f"{db_name}.dbtype").exists():
        if any(f.suffix in _BLAST_EXTS for f in db_dir.glob(f"{db_name}.*")):
            _report_once(
                db_name, "blast", logging.ERROR,
                "Database %r at %s is a BLAST database; only MMseqs2 databases are "
                "supported and searches against it will fail",
                db_name, target,
            )
        else:
            _report_once(
                db_name, "missing", logging.ERROR,
                "Database %r: no MMseqs2 database found at %s (missing %s.dbtype)",
                db_name, target, db_name,
            )
        return
    if db_type == "nucleotide" and not (db_dir / f"{db_name}.idx").exists():
        _report_once(
            db_name, "unindexed", logging.WARNING,
            "Nucleotide database %r has no precomputed index (%s.idx); "
            "blastn searches against it will be slow",
            db_name, target,
        )


def get_database(name: str, config_path: Path | None = None) -> DatabaseInfo | None:
    """Return the database definition with the given name, or None."""
    return next((db for db in load_databases(config_path) if db.name == name), None)


def database_exists(name: str, config_path: Path | None = None) -> bool:
    """Return True if a database with the given name is defined in the config."""
    return get_database(name, config_path) is not None


def get_database_path(name: str, config_path: Path | None = None) -> Path:
    """Return the MMseqs2 target DB path for a named database: <path>/<name>.

    Raises KeyError if the database is not present — callers should validate
    via database_exists() before submitting jobs.
    """
    for db in load_databases(config_path):
        if db.name == name:
            return Path(db.path) / name
    raise KeyError(f"Database not found in config: {name!r}")
