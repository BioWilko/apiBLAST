"""BLASTClient — Python interface to an apiBLAST server."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

import httpx

from apiblast.exceptions import (
    ApiBlastError,
    JobFailedError,
    ResultExpiredError,
    ServerError,
    WaitTimeoutError,
)
from apiblast.models import BlastHit, BlastResult, Database, Job

_DEFAULT_SERVER = "http://localhost:8000"
_TERMINAL_STATES = {"SUCCESS", "FAILURE", "TIMEOUT", "REVOKED"}


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    if resp.status_code == 410:
        raise ResultExpiredError.__new__(ResultExpiredError)
    raise ServerError(resp.status_code, detail)


class BLASTClient:
    """Client for the apiBLAST REST API.

    Usage::

        with BLASTClient("http://blast-server:8000") as client:
            result = client.blast("blastn", "nt_small", ">seq1\\nATGCATGC")
            for hit in result.hits:
                print(hit.subject_id, hit.evalue)
    """

    def __init__(self, server: str = _DEFAULT_SERVER, timeout: float = 30.0):
        self._base = server.rstrip("/")
        self._timeout = timeout
        self._http: httpx.Client | None = None

    @classmethod
    def from_env(cls, timeout: float = 30.0) -> "BLASTClient":
        """Create a client using the APIBLAST_SERVER environment variable."""
        server = os.environ.get("APIBLAST_SERVER", _DEFAULT_SERVER)
        return cls(server=server, timeout=timeout)

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "BLASTClient":
        self._http = httpx.Client(base_url=self._base, timeout=self._timeout)
        return self

    def __exit__(self, *_) -> None:
        if self._http:
            self._http.close()
            self._http = None

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if self._http:
            resp = getattr(self._http, method)(path, **kwargs)
        else:
            with httpx.Client(base_url=self._base, timeout=self._timeout) as c:
                resp = getattr(c, method)(path, **kwargs)
        _raise_for_status(resp)
        return resp

    # ── Core API methods ──────────────────────────────────────────────────────

    def health(self) -> dict:
        """Check server liveness. Returns {"status": "ok", "version": "..."}."""
        return self._request("get", "/health").json()

    def databases(self) -> list[Database]:
        """List BLAST databases available on the server."""
        data = self._request("get", "/api/v1/databases").json()
        return [Database._from_dict(d) for d in data["databases"]]

    def submit(
        self,
        program: str,
        database: str,
        query: str,
        evalue: float = 1e-5,
        max_hits: int = 50,
        word_size: int | None = None,
        outfmt: int = 6,
        extra_args: dict[str, str | int | float] | None = None,
    ) -> Job:
        """Submit a BLAST job and return immediately with the queued Job.

        Args:
            program:    BLAST program — blastn | blastp | blastx | tblastn | tblastx
            database:   Database name as listed by :meth:`databases`.
            query:      FASTA-formatted query string.
            evalue:     E-value threshold (default 1e-5).
            max_hits:   Maximum hits to return (default 50).
            word_size:  Word size override (optional).
            outfmt:     BLAST output format code (default 6 = tabular).
            extra_args: Additional BLAST flags as a dict, e.g. ``{"dust": "no"}``.
        """
        payload: dict = {
            "program": program,
            "database": database,
            "query": query,
            "evalue": evalue,
            "max_hits": max_hits,
            "outfmt": outfmt,
            "extra_args": extra_args or {},
        }
        if word_size is not None:
            payload["word_size"] = word_size
        data = self._request("post", "/api/v1/jobs", json=payload).json()
        return self.status(data["job_id"])

    def status(self, job_id: str) -> Job:
        """Return the current status of a job."""
        return Job._from_dict(self._request("get", f"/api/v1/jobs/{job_id}").json())

    def wait(
        self,
        job_id: str,
        poll_interval: float = 2.0,
        timeout: float | None = None,
        on_poll: Callable[[Job], None] | None = None,
    ) -> Job:
        """Block until the job reaches a terminal state.

        Args:
            job_id:        Job ID returned by :meth:`submit`.
            poll_interval: Initial polling interval in seconds (backs off to 10 s).
            timeout:       Raise :exc:`WaitTimeoutError` after this many seconds.
            on_poll:       Optional callback called with the :class:`Job` after each poll.
        """
        started = time.monotonic()
        interval = poll_interval
        while True:
            job = self.status(job_id)
            if on_poll:
                on_poll(job)
            if job.is_done:
                return job
            if timeout is not None and (time.monotonic() - started) >= timeout:
                raise WaitTimeoutError(job_id, timeout)
            time.sleep(interval)
            interval = min(interval * 1.5, 10.0)

    def results(self, job_id: str) -> BlastResult:
        """Fetch parsed hit results for a completed job.

        Raises:
            JobFailedError:    If the job ended in FAILURE or TIMEOUT.
            ResultExpiredError: If the result file has been deleted (TTL expired).
        """
        job = self.status(job_id)
        if job.status in {"FAILURE", "TIMEOUT", "REVOKED"}:
            raise JobFailedError(job_id, job.status, job.error)
        try:
            data = self._request(
                "get",
                f"/api/v1/jobs/{job_id}/results",
                headers={"Accept": "application/json"},
            ).json()
        except ResultExpiredError:
            raise ResultExpiredError(job_id)
        return BlastResult._from_dict(data)

    def results_tsv(self, job_id: str) -> str:
        """Fetch raw tabular (outfmt 6) output for a completed job."""
        try:
            return self._request(
                "get",
                f"/api/v1/jobs/{job_id}/results",
                headers={"Accept": "text/tab-separated-values"},
            ).text
        except ResultExpiredError:
            raise ResultExpiredError(job_id)

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending or running job. Returns True if it was cancelled."""
        data = self._request("delete", f"/api/v1/jobs/{job_id}").json()
        return bool(data.get("cancelled"))

    # ── High-level convenience ────────────────────────────────────────────────

    def blast(
        self,
        program: str,
        database: str,
        query: str,
        evalue: float = 1e-5,
        max_hits: int = 50,
        word_size: int | None = None,
        outfmt: int = 6,
        extra_args: dict[str, str | int | float] | None = None,
        poll_interval: float = 2.0,
        timeout: float | None = None,
        on_poll: Callable[[Job], None] | None = None,
    ) -> BlastResult:
        """Submit a job, wait for completion, and return parsed results.

        This is the simplest way to run a BLAST search::

            result = client.blast("blastn", "nt_small", ">seq1\\nATGCATGC")

        For long-running jobs, pass ``on_poll`` to receive status updates::

            def log(job):
                print(f"  {job.status} — {job.elapsed_s:.0f}s elapsed")

            result = client.blast("blastn", "nt", query, on_poll=log)
        """
        job = self.submit(
            program=program,
            database=database,
            query=query,
            evalue=evalue,
            max_hits=max_hits,
            word_size=word_size,
            outfmt=outfmt,
            extra_args=extra_args,
        )
        final = self.wait(
            job.id,
            poll_interval=poll_interval,
            timeout=timeout,
            on_poll=on_poll,
        )
        if final.status != "SUCCESS":
            raise JobFailedError(job.id, final.status, final.error)
        return self.results(job.id)

    def blast_file(
        self,
        path: str | Path,
        program: str,
        database: str,
        **kwargs,
    ) -> BlastResult:
        """Submit a BLAST job from a FASTA file and wait for results.

        ``**kwargs`` are forwarded to :meth:`blast`.
        """
        query = Path(path).read_text()
        return self.blast(program=program, database=database, query=query, **kwargs)
