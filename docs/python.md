# apiBLAST — Python bindings

The `apiblast` package includes a Python client library for submitting and retrieving BLAST jobs programmatically — useful in scripts, pipelines, and Jupyter notebooks.

## Installation

```bash
pip install "apiblast[python]"
```

## Quick start

```python
from apiblast import BLASTClient

with BLASTClient("http://blast-server:8000") as client:
    result = client.blast("blastn", "nt_small", ">seq1\nATGCATGCATGCATGC")

for hit in result.hits:
    print(hit.subject_id, hit.pct_identity, hit.evalue)
```

## BLASTClient

```python
BLASTClient(server="http://localhost:8000", timeout=30.0, token=None)
```

`token` is an optional priority token, which exempts your jobs from rate
limits and from deprioritisation. Most users do not need one.

Can also be constructed from the `APIBLAST_SERVER` (and optional
`APIBLAST_TOKEN`) environment variables:

```python
client = BLASTClient.from_env()
```

### Context manager

Using `BLASTClient` as a context manager keeps a persistent HTTP connection open across calls — recommended for scripts that make multiple requests:

```python
with BLASTClient("http://blast-server:8000") as client:
    dbs = client.databases()
    result = client.blast("blastp", "nr", query)
```

Without the context manager, each call opens and closes its own connection.

---

## Methods

### `client.databases() → list[Database]`

List databases available on the server.

```python
for db in client.databases():
    print(db.name, db.type, db.description)
```

### `client.blast(program, database, query, ...) → BlastResult`

Submit a job, wait for it to complete, and return parsed results. The simplest way to run a search.

```python
result = client.blast(
    program="blastn",
    database="nt_small",
    query=">seq1\nATGCATGCATGCATGC",
    evalue=1e-10,
    max_hits=100,
)
print(f"{result.num_hits} hits")
```

Optional arguments:

| Argument | Type | Default | Description |
|---|---|---|---|
| `evalue` | `float` | `1e-5` | E-value threshold |
| `max_hits` | `int` | `50` | Maximum subjects to return per query |
| `extra_args` | `dict` | `{}` | Additional MMseqs2 options, e.g. `{"min-seq-id": 0.9}` or, for blastx, `{"translation-table": 11}`. Only server-allowed options are accepted (see [server docs](server.md#extra_args)) |
| `poll_interval` | `float` | `2.0` | Initial polling interval (seconds) |
| `timeout` | `float \| None` | `None` | Raise `WaitTimeoutError` after this many seconds |
| `on_poll` | `Callable[[Job], None] \| None` | `None` | Callback invoked after each status poll |

**Progress callbacks** — useful in notebooks and long-running scripts:

```python
def log_progress(job):
    elapsed = job.elapsed_s or 0
    print(f"  {job.status} ({elapsed:.0f}s elapsed)", end="\r")

result = client.blast("blastn", "nt", large_query, on_poll=log_progress)
```

### `client.blast_file(path, program, database, ...) → BlastResult`

Convenience wrapper that reads a FASTA file and calls `blast()`.

```python
result = client.blast_file("sequences.fa", "blastp", "nr", max_hits=500)
```

### `client.submit(program, database, query, ...) → Job`

Submit a job without waiting. Returns a `Job` with the queued status.

```python
job = client.submit("blastn", "nt_small", query)
print(job.id, job.status)  # e.g. "a3f1c2d4..." "PENDING"
```

### `client.wait(job_id, poll_interval=2.0, timeout=None, on_poll=None) → Job`

Block until a job reaches a terminal state. Returns the final `Job`.

```python
job = client.submit("blastn", "nt_small", query)
final = client.wait(job.id, timeout=300)
print(final.status)  # SUCCESS | FAILURE | TIMEOUT | REVOKED
```

### `client.status(job_id) → Job`

Check the current status of a job without blocking.

### `client.results(job_id) → BlastResult`

Fetch parsed results for a completed job.

```python
result = client.results(job_id)
df_data = [
    {"subject": h.subject_id, "pct_id": h.pct_identity, "evalue": float(h.evalue)}
    for h in result.hits
]
```

### `client.results_tsv(job_id) → str`

Fetch raw tabular output (BLAST outfmt 6 columns) as a string.

```python
tsv = client.results_tsv(job_id)
with open("hits.tsv", "w") as f:
    f.write(tsv)
```

### `client.cancel(job_id) → bool`

Cancel a pending or running job. Returns `True` if it was cancelled.

---

## Return types

### `BlastResult`

| Attribute | Type | Description |
|---|---|---|
| `job_id` | `str` | Job UUID |
| `num_hits` | `int` | Total number of hits |
| `hits` | `list[BlastHit]` | Hit records |

### `BlastHit`

| Attribute | Type | Description |
|---|---|---|
| `query_id` | `str` | Query sequence ID |
| `subject_id` | `str` | Subject (database) sequence ID |
| `pct_identity` | `float` | Percentage identity |
| `alignment_length` | `int` | Alignment length |
| `mismatches` | `int` | Number of mismatches |
| `gap_opens` | `int` | Number of gap openings |
| `q_start` / `q_end` | `int` | Query alignment coordinates |
| `s_start` / `s_end` | `int` | Subject alignment coordinates |
| `evalue` | `str` | E-value (string, preserves scientific notation) |
| `bitscore` | `float` | Bit score |

### `Job`

| Attribute | Type | Description |
|---|---|---|
| `id` | `str` | Job UUID |
| `status` | `str` | `PENDING \| RUNNING \| SUCCESS \| FAILURE \| TIMEOUT \| REVOKED` |
| `program` | `str` | BLAST program |
| `database` | `str` | Database name |
| `submitted_at` | `str` | ISO 8601 timestamp |
| `elapsed_s` | `float \| None` | Elapsed seconds (once running) |
| `error` | `str \| None` | Error message if failed |
| `is_done` | `bool` | Property: `True` if in a terminal state |

### `Database`

| Attribute | Type | Description |
|---|---|---|
| `name` | `str` | Database name |
| `description` | `str` | Human-readable description |
| `type` | `str` | Property: `"nucleotide"` or `"protein"` |
| `program_types` | `list[str]` | Compatible BLAST programs |
| `size_bytes` | `int` | Total size of index files |

---

## Exceptions

All exceptions inherit from `ApiBlastError`.

| Exception | When raised |
|---|---|
| `ServerError(status_code, detail)` | HTTP error from the server |
| `JobFailedError(job_id, status, error)` | Job ended in FAILURE or TIMEOUT |
| `ResultExpiredError(job_id)` | Result file deleted (TTL expired) |
| `WaitTimeoutError(job_id, timeout)` | `wait()` exceeded the timeout |

```python
from apiblast import BLASTClient, JobFailedError, WaitTimeoutError

with BLASTClient("http://blast-server:8000") as client:
    try:
        result = client.blast("blastn", "nt", query, timeout=600)
    except WaitTimeoutError:
        print("Job took too long — check with client.status(job_id)")
    except JobFailedError as e:
        print(f"Job failed: {e.error}")
```

---

## Pandas integration

```python
import pandas as pd
from apiblast import BLASTClient

with BLASTClient("http://blast-server:8000") as client:
    result = client.blast("blastn", "silva", query)

df = pd.DataFrame([
    {
        "query":    h.query_id,
        "subject":  h.subject_id,
        "pct_id":   h.pct_identity,
        "aln_len":  h.alignment_length,
        "evalue":   float(h.evalue),
        "bitscore": h.bitscore,
    }
    for h in result.hits
])

df.sort_values("evalue").head(10)
```
