# apiBLAST — Server

On-premises BLAST API server for local network users. Submit nucleotide and protein sequence alignment jobs to a shared server with async queuing, rate limiting, and hardware-aware concurrency control.

## Architecture

```
Client → FastAPI (REST) → Celery worker → BLAST+ binary → filesystem results
                ↑                ↑
            SlowAPI          Redis broker
          (rate limits)    (job queue + TTL)
              SQLite/PostgreSQL (job metadata)
```

**Stack:** FastAPI · Celery · Redis · SQLAlchemy · SlowAPI · BLAST+ 2.14+

---

## Quickstart (local dev)

### Prerequisites

- Python 3.11+
- Redis (`brew install redis` or `docker run -p 6379:6379 redis:7`)
- BLAST+ binaries on PATH (e.g. `brew install blast` on macOS)

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Edit .env — set BLAST_BIN_DIR, BLAST_RESULT_DIR

# 3. Configure databases
cp databases.example.yml databases.yml
# Edit databases.yml — add the BLAST databases available on this server

# 4. Create a test database (optional, for smoke testing)
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

---

## Docker (recommended for production)

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD and any BLAST paths

cp databases.example.yml databases.yml
# Edit databases.yml — list the BLAST databases mounted into the container

# Calculate the right worker concurrency for your server:
./scripts/compute_concurrency.sh
# → paste CELERY_CONCURRENCY=N into .env

docker compose up -d
```

| Service | Port | Purpose |
|---|---|---|
| API | 8000 | REST API |
| Flower | 5555 | Celery monitoring dashboard |
| PostgreSQL | 5432 | Job metadata |
| Redis | 6379 | Task broker |

Scale workers horizontally: `docker compose up --scale worker=N`

Mount your BLAST databases into the `blast_dbs` volume (read-only):
```bash
# In docker-compose.yml, replace the named volume with a bind mount:
blast_dbs:
  driver: local
  driver_opts:
    type: none
    o: bind
    device: /path/to/your/blast/databases
```

---

## API Reference

### Submit a job

```
POST /api/v1/jobs
```

```json
{
  "program":    "blastn",
  "database":   "nt_small",
  "query":      ">seq1\nATGCATGCATGCATGC",
  "evalue":     1e-5,
  "max_hits":   50,
  "outfmt":     6,
  "extra_args": {"dust": "no"}
}
```

Returns `201` with `job_id` and `poll_url`.

### Poll status

```
GET /api/v1/jobs/{job_id}
```

`status` is one of: `PENDING | RUNNING | SUCCESS | FAILURE | TIMEOUT | REVOKED`

### Retrieve results

```
GET /api/v1/jobs/{job_id}/results
Accept: application/json          # parsed hits (default)
Accept: text/tab-separated-values # raw BLAST tabular output
```

### Other endpoints

| Method | Path | Description |
|---|---|---|
| `DELETE` | `/api/v1/jobs/{job_id}` | Cancel a pending/running job |
| `GET` | `/api/v1/databases` | List available BLAST databases |
| `GET` | `/health` | Liveness check |
| `GET` | `/health/ready` | Readiness check (Redis + DB) |

---

## Rate limiting

Per-IP limits enforced via SlowAPI (Redis-backed):

| Limit | Value |
|---|---|
| Submissions per minute | 10 |
| Submissions per hour | 100 |
| Global queue depth | `CELERY_CONCURRENCY × 4` |
| Max query length (nt) | 500,000 bp |
| Max query length (aa) | 100,000 residues |
| Max sequences per job | 100 |

`429` responses include a `Retry-After: 60` header.
`503` is returned when the server queue is full.

---

## Hardware tuning

### Concurrency

BLAST's `-num_threads` is hardcoded to `1`. Only the word-matching phase is multi-threaded; using multiple Celery workers is consistently more efficient. Worker concurrency is set via:

```bash
./scripts/compute_concurrency.sh
# Outputs: CELERY_CONCURRENCY=14  (for a 16-core server)
```

Rule of thumb: `nproc - 2` (reserve 2 cores for OS + API process).

### Memory

Large BLAST databases (nt, nr) are memory-mapped by the OS on first access. Ensure the server has enough RAM to hold the largest database you expect to use concurrently. A rough guide:

| Database | Approximate RAM needed |
|---|---|
| 16S rRNA | < 1 GB |
| refseq_rna | ~20 GB |
| nt | ~150 GB |
| nr | ~300 GB |

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
| `BLAST_BIN_DIR` | `/opt/homebrew/bin` | Directory containing `blastn`, `blastp`, etc. |
| `BLAST_DB_CONFIG` | `databases.yml` | Path to the database configuration file |
| `BLAST_RESULT_DIR` | `/data/blast/results` | Writable directory for job results |
| `CELERY_CONCURRENCY` | `4` | Number of parallel BLAST workers |
| `BLAST_SOFT_TIMEOUT_S` | `3600` | SIGTERM after this many seconds |
| `BLAST_HARD_TIMEOUT_S` | `3900` | SIGKILL (must be > soft) |
| `MAX_QUEUE_DEPTH` | `16` | Max pending + running jobs before `503` |
| `MAX_CONCURRENT_DBS` | `3` | Max distinct databases active at once |
| `MEMORY_FLOOR_MB` | `512` | Minimum free RAM to accept a job |
| `RESULT_TTL_S` | `86400` | Result file retention (default 24 h) |
| `FLOWER_BASIC_AUTH` | `admin:changeme` | Flower dashboard credentials — **change this** |

---

## Adding a new BLAST database

Databases are defined explicitly in `databases.yml` (path set by `BLAST_DB_CONFIG`). Add an entry and restart the API — no code changes required:

```yaml
databases:
  - name: refseq_rna
    path: /data/blast/db/refseq_rna
    type: nucleotide          # nucleotide | protein
    description: "NCBI RefSeq RNA sequences (~20 GB RAM when active)"
```

The `path` is passed directly as the `-db` argument to BLAST+ binaries (omit file extensions). Verify the entry is visible:

```bash
curl http://localhost:8000/api/v1/databases
```

See `databases.example.yml` for a full annotated example with common NCBI databases.

---

## Development

```bash
# Run all tests (no Redis or BLAST+ required)
pytest

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# End-to-end test (requires live BLAST+ and Redis)
./scripts/seed_test_db.sh
pytest tests/e2e/

# Lint
ruff check .
```
