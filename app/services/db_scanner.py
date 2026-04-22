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


def _disk_stats(db_path: Path) -> tuple[int, datetime | None]:
    """Return (total_size_bytes, newest_mtime) for the index files of db_path."""
    size = 0
    last_updated: datetime | None = None
    for f in db_path.parent.glob(f"{db_path.name}.*"):
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

        db_path = Path(entry["path"])
        try:
            size_bytes, last_updated = _disk_stats(db_path)
        except OSError:
            size_bytes, last_updated = 0, None

        results.append(
            DatabaseInfo(
                name=entry["name"],
                description=entry.get("description", ""),
                program_types=program_types,
                path=str(db_path),
                size_bytes=size_bytes,
                last_updated=last_updated,
            )
        )

    return results


def database_exists(name: str, config_path: Path | None = None) -> bool:
    """Return True if a database with the given name is defined in the config."""
    return any(db.name == name for db in load_databases(config_path))
