"""HTTP client wrapper for the apiBLAST server."""
from __future__ import annotations

import httpx


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    raise CliError(f"Server returned {resp.status_code}: {detail}")


class CliClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _get(self, path: str, **kwargs) -> httpx.Response:
        with httpx.Client(base_url=self._base, timeout=self._timeout) as c:
            resp = c.get(path, **kwargs)
        _raise_for_status(resp)
        return resp

    def _post(self, path: str, **kwargs) -> httpx.Response:
        with httpx.Client(base_url=self._base, timeout=self._timeout) as c:
            resp = c.post(path, **kwargs)
        _raise_for_status(resp)
        return resp

    def _delete(self, path: str) -> httpx.Response:
        with httpx.Client(base_url=self._base, timeout=self._timeout) as c:
            resp = c.delete(path)
        _raise_for_status(resp)
        return resp

    # ── API methods ───────────────────────────────────────────────────────────

    def health(self) -> dict:
        return self._get("/health").json()

    def list_databases(self) -> list[dict]:
        return self._get("/api/v1/databases").json()["databases"]

    def submit(
        self,
        program: str,
        database: str,
        query: str,
        evalue: float = 1e-5,
        max_hits: int = 50,
        word_size: int | None = None,
        outfmt: int = 6,
        extra_args: dict | None = None,
    ) -> dict:
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
        return self._post("/api/v1/jobs", json=payload).json()

    def get_status(self, job_id: str) -> dict:
        return self._get(f"/api/v1/jobs/{job_id}").json()

    def get_results_json(self, job_id: str) -> dict:
        resp = self._get(
            f"/api/v1/jobs/{job_id}/results",
            headers={"Accept": "application/json"},
        )
        return resp.json()

    def get_results_tsv(self, job_id: str) -> str:
        resp = self._get(
            f"/api/v1/jobs/{job_id}/results",
            headers={"Accept": "text/tab-separated-values"},
        )
        return resp.text

    def cancel(self, job_id: str) -> dict:
        return self._delete(f"/api/v1/jobs/{job_id}").json()
