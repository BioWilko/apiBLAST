"""CLI configuration: server URL resolution and local job history."""
import json
import os
from pathlib import Path

_DEFAULT_SERVER = "http://localhost:8000"
_CONFIG_DIR_NAME = "apiblast"


def config_dir() -> Path:
    d = Path.home() / ".config" / _CONFIG_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _config_file() -> Path:
    return config_dir() / "config.json"


def _history_file() -> Path:
    return config_dir() / "history.json"


def _read_config() -> dict:
    cfg = _config_file()
    if not cfg.is_file():
        return {}
    try:
        return json.loads(cfg.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(data: dict) -> None:
    _config_file().write_text(json.dumps(data, indent=2))


# ── Server URL ────────────────────────────────────────────────────────────────

def get_server_url() -> str:
    """Return server URL: APIBLAST_SERVER env var > config.json > default."""
    env = os.environ.get("APIBLAST_SERVER")
    if env:
        return env.rstrip("/")
    server = _read_config().get("server")
    if server:
        return server.rstrip("/")
    return _DEFAULT_SERVER


def set_server_url(url: str) -> None:
    data = _read_config()
    data["server"] = url.rstrip("/")
    _write_config(data)


def show_config() -> dict:
    data = _read_config()
    data.setdefault("server", get_server_url())
    return data


# ── Job history ───────────────────────────────────────────────────────────────

def history_append(entry: dict) -> None:
    """Append a submitted job entry to history.json (atomic write)."""
    hf = _history_file()
    history: list = []
    if hf.is_file():
        try:
            history = json.loads(hf.read_text())
        except (json.JSONDecodeError, OSError):
            history = []

    history.append(entry)

    tmp = hf.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2))
    tmp.replace(hf)


def history_list(limit: int = 20, status_filter: str | None = None) -> list[dict]:
    """Return recent history entries, newest first."""
    hf = _history_file()
    if not hf.is_file():
        return []
    try:
        entries: list[dict] = json.loads(hf.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    if status_filter:
        entries = [e for e in entries if e.get("status", "").upper() == status_filter.upper()]

    return list(reversed(entries))[:limit]
