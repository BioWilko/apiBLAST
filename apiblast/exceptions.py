"""Exceptions raised by the apiBLAST Python client."""


class ApiBlastError(Exception):
    """Base class for all apiBLAST client errors."""


class ServerError(ApiBlastError):
    """HTTP error returned by the server."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Server returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class JobFailedError(ApiBlastError):
    """Job ended in FAILURE or TIMEOUT."""
    def __init__(self, job_id: str, status: str, error: str | None = None):
        msg = f"Job {job_id} ended with status {status}"
        if error:
            msg += f": {error}"
        super().__init__(msg)
        self.job_id = job_id
        self.status = status
        self.error = error


class ResultExpiredError(ApiBlastError):
    """Result file has been deleted (TTL expired)."""
    def __init__(self, job_id: str):
        super().__init__(f"Results for job {job_id} have expired (410)")
        self.job_id = job_id


class WaitTimeoutError(ApiBlastError):
    """Job did not complete within the requested timeout."""
    def __init__(self, job_id: str, timeout: float):
        super().__init__(f"Job {job_id} did not complete within {timeout:.0f}s")
        self.job_id = job_id
        self.timeout = timeout
