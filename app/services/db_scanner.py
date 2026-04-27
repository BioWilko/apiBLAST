"""Load BLAST database definitions from databases.yml."""
from datetime import datetime
from pathlib import Path

import yaml

from app.config import get_settings
from app.models.schemas import DatabaseInfo

_NT_PROGRAMS = ["blastn", "tblastn", "tblastx"]
_AA_PROGRAMS = ["blastp", "blastx"]

# Index file extensions used to estimate database size on disk
_SIZE_EXTS = {".nhr", ".nin", ".nsq", ".phr", ".pin", ".psq"}


def _disk_stats(db_dir: Path, db_name: str) -> tuple[int, datetime | None]:
    """Return (total_size_bytes, newest_mtime) for the index files of a database."""
    size = 0
    last_updated: datetime | None = None
    for f in db_dir.glob(f"{db_name}.*"):
        if f.suffix in _SIZE_EXTS:
            size += f.stat().st_size
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if last_updated is None or mtime > last_updated:
            last_updated = mtime
    return size, last_updated


def load_databases(config_path: Path | None = None) -> list[DatabaseInfo]:
    """Return database definitions from the YAML config file."""
    if config_path is None:
        config_path = get_settings().BLAST_DB_CONFIG

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


def database_exists(name: str, config_path: Path | None = None) -> bool:
    """Return True if a database with the given name is defined in the config."""
    return any(db.name == name for db in load_databases(config_path))


def get_database_path(name: str, config_path: Path | None = None) -> Path:
    """Return the BLAST -db path for a named database: <path>/<name>.

    Raises KeyError if the database is not present — callers should validate
    via database_exists() before submitting jobs.
    """
    for db in load_databases(config_path):
        if db.name == name:
            return Path(db.path) / name
    raise KeyError(f"Database not found in config: {name!r}")
