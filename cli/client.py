"""CLI-facing HTTP client — thin wrapper around BLASTClient."""
from __future__ import annotations

from apiblast.client import BLASTClient
from apiblast.exceptions import ApiBlastError


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


class CliClient:
    """Wraps BLASTClient and converts ApiBlastError → CliError."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._client = BLASTClient(server=base_url, timeout=timeout)

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiBlastError as e:
            raise CliError(str(e)) from e

    def health(self) -> dict:
        return self._call(self._client.health)

    def list_databases(self) -> list[dict]:
        dbs = self._call(self._client.databases)
        return [
            {
                "name": d.name,
                "description": d.description,
                "program_types": d.program_types,
                "path": d.path,
                "size_bytes": d.size_bytes,
                "last_updated": d.last_updated,
            }
            for d in dbs
        ]

    def submit(
        self,
        program: str,
        database: str,
        query: str,
        evalue: float = 1e-5,
        max_hits: int = 50,
        extra_args: dict | None = None,
    ) -> dict:
        job = self._call(
            self._client.submit,
            program=program,
            database=database,
            query=query,
            evalue=evalue,
            max_hits=max_hits,
            extra_args=extra_args,
        )
        return {"job_id": job.id, "status": job.status, "submitted_at": job.submitted_at}

    def get_status(self, job_id: str) -> dict:
        job = self._call(self._client.status, job_id)
        return {
            "job_id": job.id,
            "status": job.status,
            "program": job.program,
            "database": job.database,
            "submitted_at": job.submitted_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "elapsed_s": job.elapsed_s,
            "error": job.error,
            "result_url": job.result_url,
        }

    def get_results_json(self, job_id: str) -> dict:
        result = self._call(self._client.results, job_id)
        return {
            "job_id": result.job_id,
            "num_hits": result.num_hits,
            "hits": [
                {
                    "query_id": h.query_id,
                    "subject_id": h.subject_id,
                    "pct_identity": h.pct_identity,
                    "alignment_length": h.alignment_length,
                    "mismatches": h.mismatches,
                    "gap_opens": h.gap_opens,
                    "q_start": h.q_start,
                    "q_end": h.q_end,
                    "s_start": h.s_start,
                    "s_end": h.s_end,
                    "evalue": h.evalue,
                    "bitscore": h.bitscore,
                }
                for h in result.hits
            ],
        }

    def get_results_tsv(self, job_id: str) -> str:
        return self._call(self._client.results_tsv, job_id)

    def cancel(self, job_id: str) -> dict:
        cancelled = self._call(self._client.cancel, job_id)
        return {"cancelled": cancelled}
