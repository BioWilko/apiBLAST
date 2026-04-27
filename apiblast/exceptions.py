"""Exceptions raised by the apiBLAST Python client."""


class ApiBlastError(Exception):
    """Base class for all apiBLAST client errors.

    All exceptions raised by the apiBLAST client inherit from this class,
    making it easy to catch any client-related error with a single handler.

    Example:
        >>> from apiblast import BLASTClient, ApiBlastError
        >>> try:
        ...     with BLASTClient("http://blast-server:8000") as client:
        ...         client.health()
        ... except ApiBlastError as e:
        ...     print(f"apiBLAST error: {e}")
    """


class ServerError(ApiBlastError):
    """HTTP error returned by the server.

    Raised when the apiBLAST server responds with a non-2xx HTTP status code
    other than 410 (which raises :exc:`ResultExpiredError` instead).

    Attributes:
        status_code: The HTTP status code returned by the server.
        detail: The error detail message from the server response body.

    Example:
        >>> from apiblast import BLASTClient
        >>> from apiblast.exceptions import ServerError
        >>> try:
        ...     with BLASTClient("http://blast-server:8000") as client:
        ...         client.status("nonexistent-job-id")
        ... except ServerError as e:
        ...     print(f"HTTP {e.status_code}: {e.detail}")
    """

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Server returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class JobFailedError(ApiBlastError):
    """Job ended in FAILURE, TIMEOUT, or REVOKED.

    Raised by :meth:`~apiblast.BLASTClient.results` and
    :meth:`~apiblast.BLASTClient.blast` when a job reaches a terminal
    failure state.

    Attributes:
        job_id: The unique identifier of the failed job.
        status: The terminal status string — one of ``FAILURE``, ``TIMEOUT``,
            or ``REVOKED``.
        error: Optional error message from the BLAST process, if available.

    Example:
        >>> from apiblast import BLASTClient
        >>> from apiblast.exceptions import JobFailedError
        >>> try:
        ...     with BLASTClient("http://blast-server:8000") as client:
        ...         result = client.blast("blastn", "nt", ">seq1\\nATGC")
        ... except JobFailedError as e:
        ...     print(f"Job {e.job_id} failed with status {e.status}")
        ...     if e.error:
        ...         print(f"BLAST error: {e.error}")
    """

    def __init__(self, job_id: str, status: str, error: str | None = None):
        msg = f"Job {job_id} ended with status {status}"
        if error:
            msg += f": {error}"
        super().__init__(msg)
        self.job_id = job_id
        self.status = status
        self.error = error


class ResultExpiredError(ApiBlastError):
    """Result file has been deleted by the server's TTL-based cleanup.

    Raised when the server returns HTTP 410, indicating the result file for
    the requested job no longer exists. The job must be resubmitted to obtain
    results.

    Attributes:
        job_id: The unique identifier of the job whose results have expired.

    Example:
        >>> from apiblast import BLASTClient
        >>> from apiblast.exceptions import ResultExpiredError
        >>> try:
        ...     with BLASTClient("http://blast-server:8000") as client:
        ...         result = client.results("old-job-id")
        ... except ResultExpiredError as e:
        ...     print(f"Results for job {e.job_id} have expired — resubmit the job.")
    """

    def __init__(self, job_id: str):
        super().__init__(f"Results for job {job_id} have expired (410)")
        self.job_id = job_id


class WaitTimeoutError(ApiBlastError):
    """Job did not complete within the requested client-side timeout.

    Raised by :meth:`~apiblast.BLASTClient.wait` and
    :meth:`~apiblast.BLASTClient.blast` when the ``timeout`` parameter is set
    and the job has not reached a terminal state before it elapses. The job
    continues running on the server; use :meth:`~apiblast.BLASTClient.status`
    to check progress or :meth:`~apiblast.BLASTClient.cancel` to stop it.

    Attributes:
        job_id: The unique identifier of the job that timed out.
        timeout: The client-side timeout in seconds that was exceeded.

    Example:
        >>> from apiblast import BLASTClient
        >>> from apiblast.exceptions import WaitTimeoutError
        >>> try:
        ...     with BLASTClient("http://blast-server:8000") as client:
        ...         result = client.blast("blastn", "nt", ">seq1\\nATGC", timeout=60.0)
        ... except WaitTimeoutError as e:
        ...     print(f"Job {e.job_id} did not finish within {e.timeout:.0f}s")
    """

    def __init__(self, job_id: str, timeout: float):
        super().__init__(f"Job {job_id} did not complete within {timeout:.0f}s")
        self.job_id = job_id
        self.timeout = timeout
