# apiBLAST Helm chart

Helm chart for apiBLAST 2.0 (MMseqs2 backend) in the `ns-cli-climb-gre-se`
namespace. Written in the same style as `climb-gre-helm`: every pod runs as
1000:100 on the `hub.jupyter.org/node-purpose: user-compute` nodes, all state
lives in subfolders of the existing `cephfs-shared-team` PVC, and credentials
come from a gitignored `values-secrets.yaml`.

## Resources

| Resource                                   | Description                                                                 |
| ------------------------------------------ | --------------------------------------------------------------------------- |
| Deployment + Service `apiblast-api`        | FastAPI (`uvicorn --workers 2`) on ClusterIP port 8000. **Replicas must stay 1.** An initContainer runs `alembic upgrade head` first |
| Deployment `apiblast-worker`               | Celery CPU worker, queues `blast,celery`, concurrency `celery.concurrency`  |
| Deployment `apiblast-worker-gpu`           | Celery GPU worker, queue `blast_gpu`, concurrency 1, `nvidia.com/gpu: 1`. Only if `gpuWorker.enabled` |
| Deployment `apiblast-beat`                 | Celery beat (hourly `expire_results`)                                       |
| StatefulSet + Service `apiblast-postgres`  | `postgres:16-alpine`, data in `apiblast/postgres`                           |
| Deployment + Service `apiblast-redis`      | `redis:7.4-alpine --save 60 1`, data in `apiblast/redis`                    |
| ConfigMap `apiblast-config`                | App settings (replaces `.env`) and `databases.yml`                          |
| Secret `apiblast-credentials`              | `SECRET_KEY`, `POSTGRES_PASSWORD`, `DATABASE_URL`                           |

All Deployments use `strategy: Recreate`. There is no Ingress: the API is
reachable only from inside the cluster.

Folders used on `cephfs-shared-team`:

| Folder              | Mounted at                     | Access            |
| ------------------- | ------------------------------ | ----------------- |
| `apiblast/db`       | `/data/db`               | read-only         |
| `apiblast/results`  | `/data/results`          | read-write        |
| `apiblast/postgres` | `/var/lib/postgresql/data`     | Postgres only     |
| `apiblast/redis`    | `/data` (redis pod)            | Redis only        |

A small root `init-dirs` initContainer creates `results`, `postgres` and
`redis` if missing and chowns them (non-recursively) to the pod's uid:gid.
Disable it with `volumes.initDirs.enabled=false` if the folders are pre-created.

## Database format (precondition)

The chart does not build databases. Operators must provide MMseqs2 sequence
databases on `cephfs-shared-team` under `apiblast/db/<name>/<name>`, e.g.
MMseqs2's standard databases from `mmseqs databases`. BLAST databases
(`makeblastdb` output) are not supported.

- **Nucleotide** DBs: indexed with `createindex --search-type 3`.
- **Protein** DBs: padded with `makepaddedseqdb` (for the GPU worker; on CPU
  they are searched unindexed).

## Configuring databases

`databases` in `values.yaml` is rendered to `/etc/apiblast/databases.yml`
(`DB_CONFIG`). Each entry needs `name` and `type`
(`nucleotide` | `protein`); `description` is optional. `path` is the
directory holding the DB and defaults to `/data/db/<name>`, so the app
searches `/data/db/<name>/<name>`:

```yaml
databases:
  - name: silva
    type: nucleotide
    description: "SILVA ribosomal RNA"
  - name: swissprot
    type: protein
    description: "UniProt Swiss-Prot"
```

Nucleotide DBs serve `blastn`; protein DBs serve `blastp` and `blastx`.
Changing `databases` changes the ConfigMap checksum, so `helm upgrade` rolls
the api and worker pods.

## Credentials

Credentials live in the `apiblast-credentials` Secret and are **never
committed**:

```bash
cp helm/values-secrets.yaml.example values-secrets.yaml   # then fill in
```

- `credentials.secretKey`: `openssl rand -hex 32`
- `credentials.postgresPassword`: password for the `apiblast` Postgres role
- `credentials.databaseUrl`:
  `postgresql+psycopg2://apiblast:<pw>@apiblast-postgres:5432/apiblast`
  (`<pw>` must match `postgresPassword`)

`values-secrets.yaml` is gitignored (repo `.gitignore`) and listed in
`.helmignore`.

**Caveat: the Postgres password is applied only at `initdb`**, i.e. the first
time Postgres starts on an empty `apiblast/postgres` folder. Changing
`postgresPassword` later does not change the role's password: run
`ALTER USER apiblast PASSWORD '...'` in the Postgres pod (and update
`databaseUrl` to match), or start again from an empty `apiblast/postgres`.

## Install

```bash
# Validate / dry-run
helm lint helm/
helm template apiblast helm/ -f values-secrets.yaml | less

# Install
helm install apiblast helm/ -f values-secrets.yaml -n ns-cli-climb-gre-se
```

If initdb fails as uid 1000 on CephFS, run Postgres as the alpine image's own
user instead:

```yaml
postgres:
  securityContext:
    runAsUser: 70
    runAsGroup: 70
    fsGroup: 70
    runAsNonRoot: true
```

## Upgrades

Drain (scale api to 0, wait for jobs), then `helm upgrade`.

## In-cluster access

From any pod in the cluster (e.g. a team notebook):

```bash
curl http://apiblast-api.ns-cli-climb-gre-se.svc.cluster.local:8000/health/ready
export APIBLAST_SERVER=http://apiblast-api.ns-cli-climb-gre-se.svc.cluster.local:8000
```

Inside the namespace, `http://apiblast-api:8000` also works.

## GPU worker

`gpuWorker.enabled` (default `true`) controls both the `apiblast-worker-gpu`
Deployment and the `MMSEQS_GPU_ENABLED` setting, so the API only routes
blastp/blastx to the `blast_gpu` queue while the GPU worker exists. The GPU
worker holds the A100 permanently and runs one job at a time.
`gpuWorker.threads` sets its `MMSEQS_THREADS`.

## Degraded mode (the GPU or its node is unavailable)

Run these in order:

1. `kubectl scale deploy/apiblast-api --replicas=0`
2. `kubectl exec deploy/apiblast-worker -- celery -A app.tasks.celery_app.celery_app purge -Q blast_gpu -f`
3. `kubectl exec statefulset/apiblast-postgres -- psql -U apiblast -c "UPDATE jobs SET status='REVOKED', finished_at=now(), error_message='GPU unavailable' WHERE status IN ('PENDING','RUNNING') AND program IN ('blastp','blastx');"`
   - This covers jobs that were queued and jobs that were running on the dead
     GPU pod.
   - Both count towards the queue-depth guard.
   - Unacked messages are redelivered after the 24 h `visibility_timeout`. The
     worker skips jobs that are already finished (REVOKED included), so those are no-ops.
4. `helm upgrade apiblast helm/ -f values-secrets.yaml --reuse-values --set gpuWorker.enabled=false`
   This sets `MMSEQS_GPU_ENABLED=false`, removes the GPU worker and brings
   the API back.

To return to normal, `helm upgrade ... --set gpuWorker.enabled=true` once the
GPU is back.
