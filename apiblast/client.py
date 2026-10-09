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

    Can be used as a context manager (recommended for multiple requests) or
    in one-shot mode where each method opens and closes its own HTTP
    connection.

    Args:
        server: Base URL of the apiBLAST server (no trailing slash).
        timeout: HTTP request timeout in seconds applied to every request.

    Example:
        >>> from apiblast import BLASTClient
        >>> with BLASTClient("http://blast-server:8000") as client:
        ...     result = client.blast("blastn", "nt_small", ">seq1\\nATGCATGC")
        ...     for hit in result.hits:
        ...         print(hit.subject_id, hit.evalue)
    """

    def __init__(self, server: str = _DEFAULT_SERVER, timeout: float = 30.0):
        self._base = server.rstrip("/")
        self._timeout = timeout
        self._http: httpx.Client | None = None

    @classmethod
    def from_env(cls, timeout: float = 30.0) -> "BLASTClient":
        """Create a client from the ``APIBLAST_SERVER`` environment variable.

        Falls back to ``http://localhost:8000`` if the variable is not set.

        Args:
            timeout: HTTP request timeout in seconds.

        Returns:
            A new :class:`BLASTClient` pointing at the configured server.

        Example:
            >>> import os
            >>> os.environ["APIBLAST_SERVER"] = "http://blast-server:8000"
            >>> from apiblast import BLASTClient
            >>> client = BLASTClient.from_env()
        """
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
        """Check server liveness.

        Returns:
            A dict with at least ``{"status": "ok", "version": "<semver>"}``.

        Raises:
            ServerError: If the server returns a non-2xx response.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     info = client.health()
            ...     print(info["version"])
        """
        return self._request("get", "/health").json()

    def databases(self) -> list[Database]:
        """List databases available on the server.

        Returns:
            A list of :class:`~apiblast.models.Database` objects, one per
            configured database.

        Raises:
            ServerError: If the server returns a non-2xx response.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     dbs = client.databases()
            ...     nucleotide_dbs = [db.name for db in dbs if db.type == "nucleotide"]
            ...     print(nucleotide_dbs)
        """
        data = self._request("get", "/api/v1/databases").json()
        return [Database._from_dict(d) for d in data["databases"]]

    def submit(
        self,
        program: str,
        database: str,
        query: str,
        evalue: float = 1e-5,
        max_hits: int = 50,
        extra_args: dict[str, str | int | float] | None = None,
    ) -> Job:
        """Submit a BLAST job and return immediately with the queued job.

        The returned :class:`~apiblast.models.Job` will typically have status
        ``PENDING`` or ``STARTED``. Use :meth:`wait` or poll :meth:`status`
        to track progress, then call :meth:`results` when done.

        Args:
            program: Search program. One of ``blastn`` (nucleotide
                database), ``blastp`` or ``blastx`` (protein database).
            database: Database name as returned by :meth:`databases`.
            query: FASTA-formatted query string (one or more sequences).
            evalue: E-value cutoff — hits with e-value above this are excluded.
            max_hits: Maximum number of subjects to return per query.
            extra_args: Additional MMseqs2 options as key/value pairs, e.g.
                ``{"min-seq-id": 0.95}`` or, for blastx,
                ``{"translation-table": 11}``. Only options the server
                allows are accepted.

        Returns:
            A :class:`~apiblast.models.Job` representing the queued job.

        Raises:
            ServerError: If the server rejects the request (e.g. unknown
                program or database, invalid parameters).
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     job = client.submit(
            ...         "blastn", "nt_small", ">seq1\\nATGCATGC",
            ...         evalue=1e-10, max_hits=10,
            ...     )
            ...     print(f"Submitted job {job.id} (status: {job.status})")
        """
        payload: dict = {
            "program": program,
            "database": database,
            "query": query,
            "evalue": evalue,
            "max_hits": max_hits,
            "extra_args": extra_args or {},
        }
        data = self._request("post", "/api/v1/jobs", json=payload).json()
        return self.status(data["job_id"])

    def status(self, job_id: str) -> Job:
        """Return the current status of a job.

        Args:
            job_id: Job identifier as returned by :meth:`submit`.

        Returns:
            A :class:`~apiblast.models.Job` with the latest server-side state.

        Raises:
            ServerError: If the job ID does not exist (HTTP 404) or another
                server error occurs.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     job = client.submit("blastn", "nt_small", ">seq1\\nATGC")
            ...     job = client.status(job.id)
            ...     print(job.status)
        """
        return Job._from_dict(self._request("get", f"/api/v1/jobs/{job_id}").json())

    def wait(
        self,
        job_id: str,
        poll_interval: float = 2.0,
        timeout: float | None = None,
        on_poll: Callable[[Job], None] | None = None,
    ) -> Job:
        """Block until the job reaches a terminal state.

        Polls :meth:`status` repeatedly with exponential back-off, starting at
        ``poll_interval`` and capping at 10 seconds per poll.

        Args:
            job_id: Job identifier as returned by :meth:`submit`.
            poll_interval: Initial polling interval in seconds. Grows by 1.5×
                each iteration up to a maximum of 10 seconds.
            timeout: If set, raise :exc:`~apiblast.exceptions.WaitTimeoutError`
                after this many wall-clock seconds regardless of job state.
                The job continues running on the server.
            on_poll: Optional callback invoked with the current
                :class:`~apiblast.models.Job` after each status poll. Useful
                for logging progress.

        Returns:
            The :class:`~apiblast.models.Job` in its terminal state
            (``SUCCESS``, ``FAILURE``, ``TIMEOUT``, or ``REVOKED``).

        Raises:
            WaitTimeoutError: If ``timeout`` elapses before the job finishes.
            ServerError: If a status request fails.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     job = client.submit("blastn", "nt_small", ">seq1\\nATGC")
            ...     final = client.wait(
            ...         job.id,
            ...         timeout=300.0,
            ...         on_poll=lambda j: print(f"  {j.status}"),
            ...     )
            ...     print(f"Done: {final.status}")
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

        Args:
            job_id: Job identifier as returned by :meth:`submit`.

        Returns:
            A :class:`~apiblast.models.BlastResult` containing the parsed hits.

        Raises:
            JobFailedError: If the job ended in ``FAILURE``, ``TIMEOUT``, or
                ``REVOKED``.
            ResultExpiredError: If the result file has been deleted by the
                server's TTL cleanup (HTTP 410).
            ServerError: If another server error occurs.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     job = client.submit("blastn", "nt_small", ">seq1\\nATGC")
            ...     client.wait(job.id)
            ...     result = client.results(job.id)
            ...     print(f"{result.num_hits} hits")
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
        """Fetch raw tabular output for a completed job.

        Returns the server's raw TSV text without any parsing: the 12 columns
        of BLAST's tabular format (``-outfmt 6``), with no header. Useful when
        downstream tools expect plain BLAST tabular output.

        Args:
            job_id: Job identifier as returned by :meth:`submit`.

        Returns:
            The raw tab-separated results string as returned by the server.

        Raises:
            ResultExpiredError: If the result file has been deleted by the
                server's TTL cleanup (HTTP 410).
            ServerError: If another server error occurs.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     job = client.submit("blastn", "nt_small", ">seq1\\nATGC")
            ...     client.wait(job.id)
            ...     tsv = client.results_tsv(job.id)
            ...     print(tsv[:200])
        """
        try:
            return self._request(
                "get",
                f"/api/v1/jobs/{job_id}/results",
                headers={"Accept": "text/tab-separated-values"},
            ).text
        except ResultExpiredError:
            raise ResultExpiredError(job_id)

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending or running job.

        Has no effect if the job has already reached a terminal state.

        Args:
            job_id: Job identifier as returned by :meth:`submit`.

        Returns:
            ``True`` if the job was successfully cancelled, ``False`` if the
            server indicates it was not (e.g. already finished).

        Raises:
            ServerError: If the server returns an error response.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     job = client.submit("blastn", "nt", ">seq1\\nATGC")
            ...     cancelled = client.cancel(job.id)
            ...     print("Cancelled" if cancelled else "Already finished")
        """
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
        extra_args: dict[str, str | int | float] | None = None,
        poll_interval: float = 2.0,
        timeout: float | None = None,
        on_poll: Callable[[Job], None] | None = None,
    ) -> BlastResult:
        """Submit a BLAST job, wait for completion, and return parsed results.

        Convenience wrapper that combines :meth:`submit`, :meth:`wait`, and
        :meth:`results` in a single call. This is the recommended entry point
        for most use cases.

        Args:
            program: Search program. One of ``blastn`` (nucleotide
                database), ``blastp`` or ``blastx`` (protein database).
            database: Database name as returned by :meth:`databases`.
            query: FASTA-formatted query string (one or more sequences).
            evalue: E-value cutoff — hits with e-value above this are excluded.
            max_hits: Maximum number of subjects to return per query.
            extra_args: Additional MMseqs2 options as key/value pairs, e.g.
                ``{"min-seq-id": 0.95}`` or, for blastx,
                ``{"translation-table": 11}``. Only options the server
                allows are accepted.
            poll_interval: Initial polling interval in seconds for :meth:`wait`.
            timeout: Client-side timeout in seconds. Raises
                :exc:`~apiblast.exceptions.WaitTimeoutError` if elapsed.
            on_poll: Optional callback invoked with the
                :class:`~apiblast.models.Job` after each status poll.

        Returns:
            A :class:`~apiblast.models.BlastResult` with the parsed hits.

        Raises:
            JobFailedError: If the job ends in ``FAILURE``, ``TIMEOUT``, or
                ``REVOKED``.
            WaitTimeoutError: If ``timeout`` elapses before the job finishes.
            ResultExpiredError: If results expire between job completion and
                retrieval (rare race condition with short TTLs).
            ServerError: If the server returns an error response.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     result = client.blast("blastn", "nt_small", ">seq1\\nATGCATGC")
            ...     print(f"Found {result.num_hits} hits")

            Log progress for long-running searches:

            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     result = client.blast(
            ...         "blastn", "nt", ">seq1\\nATGCATGC",
            ...         timeout=600.0,
            ...         on_poll=lambda j: print(f"  {j.status}"),
            ...     )
        """
        job = self.submit(
            program=program,
            database=database,
            query=query,
            evalue=evalue,
            max_hits=max_hits,
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

        Reads the entire file into memory and forwards its contents to
        :meth:`blast`. All keyword arguments accepted by :meth:`blast` are
        supported (``evalue``, ``max_hits``, ``timeout``, ``on_poll``, etc.).

        Args:
            path: Path to a FASTA file. Accepts both ``str`` and
                :class:`pathlib.Path`.
            program: Search program. One of ``blastn`` (nucleotide
                database), ``blastp`` or ``blastx`` (protein database).
            database: Database name as returned by :meth:`databases`.
            **kwargs: Additional keyword arguments forwarded to :meth:`blast`.

        Returns:
            A :class:`~apiblast.models.BlastResult` with the parsed hits.

        Raises:
            FileNotFoundError: If ``path`` does not exist.
            JobFailedError: If the job ends in a failure state.
            WaitTimeoutError: If the ``timeout`` kwarg elapses.
            ResultExpiredError: If results expire before retrieval.
            ServerError: If the server returns an error response.
            httpx.TransportError: If the server cannot be reached.

        Example:
            >>> from pathlib import Path
            >>> from apiblast import BLASTClient
            >>> with BLASTClient("http://blast-server:8000") as client:
            ...     result = client.blast_file(
            ...         Path("sequences.fasta"), "blastn", "nt_small",
            ...         evalue=1e-10,
            ...     )
            ...     print(f"Found {result.num_hits} hits")
        """
        query = Path(path).read_text()
        return self.blast(program=program, database=database, query=query, **kwargs)
