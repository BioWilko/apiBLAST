"""apiBLAST command-line client."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from cli import client as _client_mod
from cli import config as _config
from cli import formatters as _fmt
from cli.client import CliClient, CliError

app = typer.Typer(
    name="apiblast",
    help="Submit and manage BLAST jobs on an apiBLAST server.",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Read and write client configuration.")
app.add_typer(config_app, name="config")

console = Console()
err = Console(stderr=True)

_TERMINAL_STATES = {"SUCCESS", "FAILURE", "TIMEOUT", "REVOKED"}


def _make_client() -> CliClient:
    return CliClient(_config.get_server_url())


def _handle_cli_error(e: CliError) -> None:
    err.print(f"[red]Error:[/] {e}")
    raise typer.Exit(code=e.exit_code)


# ── Polling helper ────────────────────────────────────────────────────────────

def _poll_until_done(client: CliClient, job_id: str) -> dict:
    """Block with a Rich spinner until the job reaches a terminal state."""
    interval = 2.0
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=err,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Waiting — {job_id}…", total=None)
        while True:
            job = client.get_status(job_id)
            status = job.get("status", "UNKNOWN")
            progress.update(task, description=f"[cyan]{status}[/] — {job_id}…")
            if status in _TERMINAL_STATES:
                return job
            time.sleep(interval)
            interval = min(interval * 1.5, 10.0)


# ── submit ────────────────────────────────────────────────────────────────────

@app.command()
def submit(
    fasta_file: Annotated[Path, typer.Argument(help="FASTA file containing query sequence(s)")],
    program: Annotated[str, typer.Option(
        "--program", "-p", help="blastn (nucleotide DB), blastp or blastx (protein DB)"
    )] = "blastn",
    db: Annotated[str, typer.Option("--db", "-d", help="Database name (see `apiblast databases`)")] = "",
    evalue: Annotated[float, typer.Option(help="E-value threshold")] = 1e-5,
    max_hits: Annotated[int, typer.Option(help="Maximum subjects to return per query")] = 50,
    extra_arg: Annotated[Optional[list[str]], typer.Option(
        "--extra-arg",
        help="Extra MMseqs2 option as key=value (repeatable), e.g. min-seq-id=0.9, "
             "s=7.5, or for blastx translation-table=11",
    )] = None,
    wait: Annotated[bool, typer.Option("--wait", help="Block until job completes and show results")] = False,
    format: Annotated[str, typer.Option("--format", help="Output format for --wait: table|tsv|json")] = "table",
    top: Annotated[Optional[int], typer.Option("--top", help="Show only top N hits (table/json)")] = None,
) -> None:
    """Submit a BLAST job. Prints the job ID to stdout (scriptable)."""
    if not db:
        err.print("[red]Error:[/] --db is required. Use `apiblast databases` to list available databases.")
        raise typer.Exit(1)

    if not fasta_file.is_file():
        err.print(f"[red]Error:[/] File not found: {fasta_file}")
        raise typer.Exit(1)

    query = fasta_file.read_text()

    extra: dict[str, str | int | float] = {}
    for kv in (extra_arg or []):
        if "=" not in kv:
            err.print(f"[red]Error:[/] --extra-arg must be key=value, got: {kv!r}")
            raise typer.Exit(1)
        k, v = kv.split("=", 1)
        extra[k] = v

    client = _make_client()
    try:
        job = client.submit(
            program=program,
            database=db,
            query=query,
            evalue=evalue,
            max_hits=max_hits,
            extra_args=extra,
        )
    except CliError as e:
        _handle_cli_error(e)
        return

    job_id = job["job_id"]

    _config.history_append({
        "job_id": job_id,
        "program": program,
        "database": db,
        "submitted_at": job.get("submitted_at", ""),
        "status": "PENDING",
        "server": _config.get_server_url(),
    })

    if wait:
        try:
            final = _poll_until_done(client, job_id)
        except CliError as e:
            _handle_cli_error(e)
            return
        _render_results(client, job_id, final, format, top)
    else:
        # Bare job ID to stdout — scriptable: JOB=$(apiblast submit ...)
        typer.echo(job_id)


# ── status ────────────────────────────────────────────────────────────────────

@app.command()
def status(
    job_id: Annotated[str, typer.Argument(help="Job ID to check")],
) -> None:
    """Show the current status of a job."""
    client = _make_client()
    try:
        job = client.get_status(job_id)
    except CliError as e:
        _handle_cli_error(e)
        return
    _fmt.print_job_status(job)


# ── results ───────────────────────────────────────────────────────────────────

def _render_results(
    client: CliClient,
    job_id: str,
    job: dict,
    format: str,
    top: int | None,
) -> None:
    status = job.get("status", "")
    if status != "SUCCESS":
        err.print(f"[red]Job {job_id} ended with status {status}.[/]")
        if job.get("error"):
            err.print(f"  {job['error']}", markup=False)
        raise typer.Exit(1)

    try:
        if format == "tsv":
            raw = client.get_results_tsv(job_id)
            header = "qseqid\tsseqid\tpident\tlength\tmismatch\tgapopen\tqstart\tqend\tsstart\tsend\tevalue\tbitscore\n"
            sys.stdout.write(header)
            sys.stdout.write(raw)
            return

        data = client.get_results_json(job_id)
    except CliError as e:
        _handle_cli_error(e)
        return

    if format == "json":
        typer.echo(json.dumps(data, indent=2))
        return

    hits = data.get("hits", [])
    num_hits = data.get("num_hits", len(hits))
    err.print(f"[dim]{num_hits} hit(s) for job {job_id}[/]")
    if not hits:
        console.print("[dim]No hits.[/]")
        return
    console.print(_fmt.hits_table(hits, top_n=top))


@app.command()
def results(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    format: Annotated[str, typer.Option("--format", help="Output format: table|tsv|json")] = "table",
    top: Annotated[Optional[int], typer.Option("--top", help="Show only top N hits")] = None,
) -> None:
    """Fetch results for a job, polling until it completes."""
    client = _make_client()
    try:
        job = client.get_status(job_id)
    except CliError as e:
        _handle_cli_error(e)
        return

    if job.get("status") not in _TERMINAL_STATES:
        try:
            job = _poll_until_done(client, job_id)
        except CliError as e:
            _handle_cli_error(e)
            return

    _render_results(client, job_id, job, format, top)


# ── databases ─────────────────────────────────────────────────────────────────

@app.command()
def databases() -> None:
    """List available databases on the server."""
    client = _make_client()
    try:
        dbs = client.list_databases()
    except CliError as e:
        _handle_cli_error(e)
        return
    _fmt.print_databases(dbs)


# ── jobs ──────────────────────────────────────────────────────────────────────

@app.command()
def jobs(
    status_filter: Annotated[Optional[str], typer.Option("--status", help="Filter by status")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum rows to show")] = 20,
) -> None:
    """List recently submitted jobs (from local history), with live status."""
    entries = _config.history_list(limit=limit * 2, status_filter=None)
    if not entries:
        console.print("[dim]No jobs in local history.[/]")
        return

    client = _make_client()
    refreshed: list[dict] = []
    for entry in entries:
        try:
            job = client.get_status(entry["job_id"])
            entry["status"] = job.get("status", entry.get("status", "UNKNOWN"))
        except CliError:
            pass
        refreshed.append(entry)

    if status_filter:
        refreshed = [e for e in refreshed if e.get("status", "").upper() == status_filter.upper()]

    _fmt.print_jobs_history(refreshed[:limit])


# ── cancel ────────────────────────────────────────────────────────────────────

@app.command()
def cancel(
    job_id: Annotated[str, typer.Argument(help="Job ID to cancel")],
) -> None:
    """Cancel a pending or running job."""
    client = _make_client()
    try:
        result = client.cancel(job_id)
    except CliError as e:
        _handle_cli_error(e)
        return
    if result.get("cancelled"):
        console.print(f"[green]Cancelled[/] job {job_id}")
    else:
        console.print(f"[dim]Job {job_id} was already in a terminal state — nothing to cancel.[/]")


# ── config subcommands ────────────────────────────────────────────────────────

@config_app.command("set")
def config_set(
    server: Annotated[Optional[str], typer.Option("--server", help="Server base URL")] = None,
) -> None:
    """Write configuration values."""
    if server is None:
        err.print("[red]Error:[/] Provide at least one option, e.g. --server http://blast-server:8000")
        raise typer.Exit(1)
    _config.set_server_url(server)
    console.print(f"[green]Server URL set to:[/] {server}")


@config_app.command("show")
def config_show() -> None:
    """Print current configuration."""
    data = _config.show_config()
    console.print(f"[bold]Server URL:[/] {data.get('server')}")
    console.print(f"[dim]Config file:[/] {escape(str(_config._config_file()))}")
    console.print(f"[dim]History file:[/] {escape(str(_config._history_file()))}")
    env = __import__("os").environ.get("APIBLAST_SERVER")
    if env:
        console.print(f"[yellow]APIBLAST_SERVER env override:[/] {env}")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
