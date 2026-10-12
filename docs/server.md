# apiBLAST — Server

On-premises sequence search API for local network users. Submit nucleotide and protein search jobs to a shared server with async queuing, rate limiting, and hardware-aware concurrency control. Searches run on [MMseqs2](https://github.com/soedinglab/MMseqs2) (release 18-8cc5c); results use BLAST's tabular output format.

## Architecture

```
Client → FastAPI (REST) → Celery worker (CPU) → mmseqs easy-search → filesystem results
                ↑         Celery worker (GPU) ↗
            SlowAPI          Redis broker
          (rate limits)    (job queue + TTL)
              SQLite/PostgreSQL (job metadata)
```

**Stack:** FastAPI · Celery · Redis · SQLAlchemy · SlowAPI · MMseqs2 18-8cc5c

### Search types

Clients give the query's molecule type (`query_type`); the database's comes from its configured `type`. The pair picks the search:

| `query_type` | Database | MMseqs2 search | Runs on |
|---|---|---|---|
| `nucleotide` | nucleotide | `--search-type 3 --strand 2` | CPU |
| `protein` | protein | `--search-type 1` | GPU when enabled, else CPU |
| `nucleotide` | protein | `--search-type 2` (query translated) | GPU when enabled, else CPU |

Protein queries against a nucleotide database are rejected with `422`: they would require translating the target database.

With `MMSEQS_GPU_ENABLED=true`, searches against protein databases go to the `blast_gpu` Celery queue, served by a single GPU worker; searches against nucleotide databases always run on the CPU workers (`blast` queue). Internally jobs are still stored as `blastn`/`blastp`/`blastx`.

---

## Deployment

Production runs on Kubernetes with the Helm chart in [`helm/`](../helm/README.md): API, CPU worker, GPU worker, Celery beat, Redis and PostgreSQL. See `helm/README.md` for install, configuration, degraded mode (GPU unavailable) and upgrades.

### Database format

**Only MMseqs2 sequence databases are supported.** BLAST databases (`makeblastdb` output: `.nsq`, `.psq`, `.nal`, … files) cannot be searched and have to be rebuilt from FASTA as MMseqs2 databases; MMseqs2 profile databases (e.g. Pfam) are not supported either. The server logs an error at startup for any configured database that is not an MMseqs2 database.

Building databases is outside apiBLAST. Each entry in `databases.yml` must point to a prebuilt MMseqs2 database at `<path>/<name>`, for example one of MMseqs2's standard databases (`mmseqs databases`, e.g. SILVA, NT, UniProtKB/Swiss-Prot, UniRef90):

- **Nucleotide** (`type: nucleotide`, searched by nucleotide queries): indexed with `mmseqs createindex --search-type 3`. Without the index, searches still work but are slow; the server logs a warning.
- **Protein** (`type: protein`, searched by protein and translated nucleotide queries): padded with `mmseqs makepaddedseqdb` so it can be searched on the GPU. CPU searches use it unindexed.

---

## Quickstart (local dev)

### Prerequisites

- Python 3.11+
- Redis (`brew install redis` or `docker run -p 6379:6379 redis:7`)
- `mmseqs` on PATH (e.g. `brew install mmseqs2`, or a release binary from [mmseqs.com/latest](https://mmseqs.com/latest))

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Edit .env — set MMSEQS_BIN

# 3. Configure databases
cp databases.example.yml databases.yml
# Edit databases.yml — add the MMseqs2 databases available on this server

# 4. Create tiny test databases (optional, for smoke testing)
./scripts/seed_test_db.sh

# 5. Initialise the metadata database
alembic upgrade head

# 6. Start Redis (if not already running)
redis-server &

# 7. Start the Celery worker
celery -A app.tasks.celery_app.celery_app worker \
  --queues=blast,celery --concurrency=4 --loglevel=info &

# 8. Start the API
uvicorn app.main:app --reload
```

API is at `http://localhost:8000` · Auto-generated docs at `http://localhost:8000/docs`

Local development runs CPU-only; leave `MMSEQS_GPU_ENABLED=false`.

---

## API Reference

### Submit a job

```
POST /api/v1/jobs
```

```json
{
  "query_type": "nucleotide",
  "database":   "silva",
  "query":      ">seq1\nATGCATGCATGCATGC",
  "evalue":     1e-5,
  "max_hits":   50,
  "extra_args": {"min-seq-id": 0.9}
}
```

Returns `201` with `job_id` and `poll_url`. Unknown fields are rejected with `422`.

`max_hits` is the maximum number of distinct subjects reported per query.

#### `extra_args`

Only these MMseqs2 options are accepted; values must be numbers:

| Key | Searches | Meaning |
|---|---|---|
| `min-seq-id` | all | Minimum sequence identity, as a fraction (0.95 = 95 %) |
| `c` | all | Minimum alignment coverage (fraction), see `cov-mode` |
| `cov-mode` | all | Coverage mode (0 = query and target, 1 = target, 2 = query, …) |
| `s` | CPU jobs only | Sensitivity, 1–7.5 (default 5.7). Rejected for GPU jobs, which always run at maximum sensitivity |
| `translation-mode` | translated | `1` = translate the six full reading frames (default), `0` = translate ORFs only |
| `translation-table` | translated | Genetic code, e.g. `11` for bacteria and archaea (default `1`, standard) |

#### Removed in 2.0

`outfmt` and `word_size` no longer exist. For compatibility with 1.x clients, `"outfmt": 6` and `"word_size": null` are accepted and ignored; any other value returns `422`.

### Poll status

```
GET /api/v1/jobs/{job_id}
```

`status` is one of: `PENDING | RUNNING | SUCCESS | FAILURE | TIMEOUT | REVOKED`

### Retrieve results

```
GET /api/v1/jobs/{job_id}/results
Accept: application/json          # parsed hits (default)
Accept: text/tab-separated-values # raw tabular output, BLAST outfmt 6 columns
```

### Other endpoints

| Method | Path | Description |
|---|---|---|
| `DELETE` | `/api/v1/jobs/{job_id}` | Cancel a pending/running job |
| `GET` | `/api/v1/databases` | List available databases |
| `GET` | `/health` | Liveness check |
| `GET` | `/health/ready` | Readiness check (Redis + DB) |

---

## Results compared with BLAST

Results use BLAST's 12 tabular columns and coordinate conventions (for a reverse-strand nucleotide hit, `s_start > s_end`; for a minus-frame translated hit, `q_start > q_end`), but they are not identical to BLAST's:

- **Sensitivity:** CPU searches at the default sensitivity (`s` 5.7) can miss distant homologs and very short queries that BLAST finds. Raise `s` (up to 7.5) for harder searches.
- **E-values and bit scores** come from different statistics and are not directly comparable with BLAST values; thresholds tuned on BLAST may need revisiting. Bit scores are whole numbers.
- **One alignment per query–subject pair**, where BLAST may report several HSPs.
- **Low-complexity masking** uses tantan rather than DUST/SEG; highly repetitive queries may return no hits.
- **Subject IDs** are the first word of each database FASTA header.
- **GPU and CPU results differ** for searches against protein databases, because the GPU uses a different prefilter at maximum sensitivity.
- **Translated searches are not frameshift-aware.** Each frame (or ORF) is aligned separately, so genes in error-prone sequence (long reads, draft assemblies) give fragmented, lower-scoring hits. In ORF mode (`translation-mode: 0`), ORFs shorter than 30 codons are dropped, so queries under ~90 nt find nothing; the default frame mode has no such limit.

---

## Rate limiting

Per-IP limits enforced via SlowAPI (Redis-backed):

| Limit | Value |
|---|---|
| Submissions per minute | `RATE_LIMIT_SUBMIT_PER_MINUTE` (10) |
| Submissions per hour | `RATE_LIMIT_SUBMIT_PER_HOUR` (100) |
| Other requests per minute | 200 |
| Global queue depth | `MAX_QUEUE_DEPTH` (16) pending + running jobs |
| Max query length (`query_type: nucleotide`) | 500,000 bp |
| Max query length (`query_type: protein`) | 100,000 residues |
| Max sequences per job | 100 |

`429` responses include a `Retry-After: 60` header.
`503` is returned when the server queue is full.
`413` is returned for request bodies over
`2 × max(MAX_QUERY_LENGTH_NT, MAX_QUERY_LENGTH_AA) + 1 MB` (2 MB by default),
before the body is read. Validation errors (`422`) list each error's type,
location and message, without echoing the submitted values.

Holders of a [priority token](#priority-tokens) are exempt from the request
limits and the queue depth, but not from the query size limits.

---

## Prioritisation

Each CPU search gets a cost estimate at submission, roughly

```
cost = search factor × query kilo-residues × database GB × (s / 5.7)² × max(max_hits, 300) / 300
```

where the search factor is 2 for nucleotide queries (both strands, or six
translated frames) and 1 for protein queries, and the database size is its on-disk size
(including any `.idx`, with a 0.1 GB floor). Jobs with
`cost ≥ COST_HEAVY_THRESHOLD` (default 1000) are queued behind all other
jobs; they still run in submission order among themselves, and only wait
while lighter jobs are queued. Examples at the default threshold:

| Search | Cost | Heavy? |
|---|---|---|
| Nucleotide, one 30 kb genome vs a 5 GB database | 300 | no |
| Nucleotide, 100 × 1.5 kb 16S reads vs a 5 GB database | 1,500 | yes |
| Protein, 100 × 400 aa proteins vs a 1 GB database | 40 | no |
| Protein, 100 × 400 aa proteins vs a 100 GB database | 4,000 | yes |

GPU searches are never deprioritised. Each submission logs its cost, so the
threshold can be tuned against the jobs' measured run times.

---

## Priority tokens

Priority tokens are optional; requests without one behave as above. A token
is sent as a bearer token:

```bash
curl -H "Authorization: Bearer apb_..." -X POST .../api/v1/jobs -d @job.json
```

Its holder bypasses rate limits, the queue depth limit and deprioritisation:
their jobs go to the front of the queue. A request with an unknown or revoked
token gets `401`.

Tokens are created, listed and revoked on the server, where only a hash of
each token is stored. The token itself is printed once, at creation:

```bash
python -m app.admin tokens create --label "alice (outbreak team)"
python -m app.admin tokens list
python -m app.admin tokens revoke <id-or-prefix>
```

Revoking a token takes effect immediately.

---

## Hardware tuning

### Concurrency

Each search runs with `MMSEQS_THREADS` threads (default `1`); parallelism comes from Celery worker processes. Worker concurrency is set via:

```bash
./scripts/compute_concurrency.sh
# Outputs: CELERY_CONCURRENCY=14  (for a 16-core server)
```

Rule of thumb: `nproc - 2` (reserve 2 cores for OS + API process).

The GPU worker runs one job at a time (Celery concurrency 1) with its own `MMSEQS_THREADS`, set in the Helm chart's `gpuWorker.threads`.

### Memory

Database and index files are memory-mapped and benefit from the OS page cache. MMseqs2 index files are considerably larger than the sequence data, so size worker memory for the largest indexed nucleotide database in use.

The server enforces a `MEMORY_FLOOR_MB` hard floor (default 512 MB) — jobs are rejected with `FAILURE` if available RAM drops below this.

### DB cache thrashing

Set `MAX_CONCURRENT_DBS` (default 3) to limit how many distinct databases can be active simultaneously. Jobs requiring a 4th+ database are retried after 30 seconds rather than evicting cached databases from OS page cache.

---

## Configuration

All settings are environment variables (`.env` file or system env):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./apiblast.db` | Switch to PostgreSQL for production |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `MMSEQS_BIN` | `/usr/local/bin/mmseqs` | Path to the `mmseqs` binary |
| `MMSEQS_THREADS` | `1` | Threads per search |
| `MMSEQS_GPU_ENABLED` | `false` | Route searches against protein databases to the `blast_gpu` queue (needs a GPU worker) |
| `DB_CONFIG` | `databases.yml` | Path to the database configuration file |
| `RESULT_DIR` | `/data/results` | Writable directory for job results |
| `CELERY_CONCURRENCY` | `4` | Number of parallel search workers |
| `JOB_SOFT_TIMEOUT_S` | `3600` | SIGTERM after this many seconds |
| `JOB_HARD_TIMEOUT_S` | `3900` | SIGKILL (must be > soft) |
| `MAX_QUEUE_DEPTH` | `16` | Max pending + running jobs before `503` |
| `COST_HEAVY_THRESHOLD` | `1000` | Estimated cost at which CPU jobs are deprioritised (see [Prioritisation](#prioritisation)) |
| `RATE_LIMIT_SUBMIT_PER_MINUTE` | `10` | Per-IP job submissions per minute |
| `RATE_LIMIT_SUBMIT_PER_HOUR` | `100` | Per-IP job submissions per hour |
| `MAX_CONCURRENT_DBS` | `3` | Max distinct databases active at once |
| `MEMORY_FLOOR_MB` | `512` | Minimum free RAM to accept a job |
| `RESULT_TTL_S` | `86400` | Result file retention (default 24 h) |

---

## Adding a database

Databases are defined explicitly in `databases.yml` (path set by `DB_CONFIG`). Add an entry and restart the API — no code changes required:

```yaml
databases:
  - name: silva
    path: /data/db/silva
    type: nucleotide          # nucleotide | protein
    description: "SILVA ribosomal RNA"
```

`path` is the directory; MMseqs2 searches the database at `<path>/<name>`, so the database files must be named `silva`, `silva.dbtype`, `silva.index`, `silva_h`, … inside that directory (see [Database format](#database-format)). Verify the entry is visible:

```bash
curl http://localhost:8000/api/v1/databases
```

See `databases.example.yml` for a full annotated example.

---

## Development

```bash
# Run all tests (no Redis or MMseqs2 required; e2e tests are skipped)
pytest

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# End-to-end searches against real MMseqs2 (needs mmseqs on PATH; the tests
# build their own tiny databases with scripts/seed_test_db.sh)
pytest tests/e2e/

# Include the GPU end-to-end test (on a machine with an NVIDIA GPU)
APIBLAST_GPU_TESTS=1 pytest tests/e2e/

# Lint
ruff check .
```
