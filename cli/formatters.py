"""Rich-based output formatters for the apiBLAST CLI."""
from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()
err_console = Console(stderr=True)


# ── E-value colouring ─────────────────────────────────────────────────────────

def _evalue_style(evalue_str: str) -> str:
    try:
        v = float(evalue_str)
    except ValueError:
        return "white"
    if v < 1e-10:
        return "green"
    if v < 1e-5:
        return "yellow"
    return "red"


# ── Hits table ────────────────────────────────────────────────────────────────

def hits_table(hits: list[dict], top_n: int | None = None) -> Table:
    if top_n is not None:
        hits = hits[:top_n]

    t = Table(box=box.SIMPLE_HEAD, show_edge=False, highlight=True)
    t.add_column("Query", style="cyan", no_wrap=True)
    t.add_column("Subject", style="bright_white", no_wrap=True)
    t.add_column("%ID", justify="right")
    t.add_column("Aln len", justify="right")
    t.add_column("Mis", justify="right")
    t.add_column("Gaps", justify="right")
    t.add_column("E-value", justify="right")
    t.add_column("Bitscore", justify="right")

    for h in hits:
        ev = h.get("evalue", "")
        t.add_row(
            h.get("query_id", ""),
            h.get("subject_id", ""),
            f"{h.get('pct_identity', 0):.1f}",
            str(h.get("alignment_length", "")),
            str(h.get("mismatches", "")),
            str(h.get("gap_opens", "")),
            f"[{_evalue_style(ev)}]{ev}[/]",
            f"{h.get('bitscore', 0):.1f}",
        )
    return t


# ── Status badge ──────────────────────────────────────────────────────────────

_STATUS_STYLE = {
    "PENDING":  "yellow",
    "RUNNING":  "cyan",
    "SUCCESS":  "green",
    "FAILURE":  "red",
    "TIMEOUT":  "red",
    "REVOKED":  "dim",
}


def status_style(status: str) -> str:
    return _STATUS_STYLE.get(status.upper(), "white")


def _elapsed(job: dict) -> str:
    elapsed = job.get("elapsed_s")
    if elapsed is None:
        return "—"
    h, rem = divmod(int(elapsed), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


# ── Single job status ─────────────────────────────────────────────────────────

def print_job_status(job: dict) -> None:
    status = job.get("status", "")
    style = status_style(status)
    t = Table(box=box.SIMPLE, show_header=False, show_edge=False)
    t.add_column("Key", style="dim", width=16)
    t.add_column("Value")
    t.add_row("Job ID", job.get("job_id", ""))
    t.add_row("Status", f"[{style}]{status}[/]")
    t.add_row("Program", job.get("program", ""))
    t.add_row("Database", job.get("database", ""))
    t.add_row("Elapsed", _elapsed(job))
    if job.get("error"):
        t.add_row("Error", f"[red]{job['error']}[/]")
    console.print(t)


# ── Databases table ───────────────────────────────────────────────────────────

def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PB"


def print_databases(dbs: list[dict]) -> None:
    if not dbs:
        console.print("[dim]No databases configured.[/]")
        return
    t = Table(box=box.SIMPLE_HEAD, show_edge=False)
    t.add_column("Name", style="cyan", no_wrap=True)
    t.add_column("Type")
    t.add_column("Programs")
    t.add_column("Size", justify="right")
    t.add_column("Description")
    for db in dbs:
        db_type = "nucleotide" if "blastn" in db.get("program_types", []) else "protein"
        t.add_row(
            db.get("name", ""),
            db_type,
            ", ".join(db.get("program_types", [])),
            _human_size(db.get("size_bytes", 0)),
            db.get("description", ""),
        )
    console.print(t)


# ── Jobs history table ────────────────────────────────────────────────────────

def _relative_time(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        s = int(diff.total_seconds())
        if s < 60:
            return f"{s}s ago"
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return ts


def print_jobs_history(entries: list[dict]) -> None:
    if not entries:
        console.print("[dim]No jobs in local history.[/]")
        return
    t = Table(box=box.SIMPLE_HEAD, show_edge=False)
    t.add_column("Job ID", style="cyan", no_wrap=True)
    t.add_column("Program")
    t.add_column("Database")
    t.add_column("Submitted", justify="right")
    t.add_column("Status")
    for e in entries:
        status = e.get("status", "UNKNOWN")
        style = status_style(status)
        t.add_row(
            e.get("job_id", "")[:36],
            e.get("program", ""),
            e.get("database", ""),
            _relative_time(e.get("submitted_at", "")),
            f"[{style}]{status}[/]",
        )
    console.print(t)
