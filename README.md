# apiBLAST

Submit sequence search jobs to an on-premises apiBLAST server from the command line. Searches run on MMseqs2 and return BLAST tabular output.

> **Server operators:** see [docs/server.md](docs/server.md) for installation, deployment, API reference, and hardware tuning.

---

## Installation

```bash
pip install "apiblast[cli]"
```

Requires Python 3.11+. No search software needed on the client machine.

---

## Quick start

```bash
# Point the client at your server (once)
apiblast config set --server http://blast-server:8000

# List available databases
apiblast databases

# Submit a job and get results when done
apiblast submit query.fa --db nt_small --wait

# Or submit and poll separately
JOB=$(apiblast submit query.fa --db nt_small)
apiblast status $JOB
apiblast results $JOB
```

---

## Commands

### `apiblast submit <fasta_file>`

```
--query-type, -t  nucleotide | protein  [default: nucleotide]
--db, -d        Database name (required — see `apiblast databases`)
--evalue        E-value threshold  [default: 1e-5]
--max-hits      Maximum subjects to return per query  [default: 50]
--extra-arg     Extra MMseqs2 option as key=value, repeatable (see below)
--wait          Block until complete and print results
--format        Output format when using --wait: table | tsv | json  [default: table]
--top N         Show only the top N hits
```

`--query-type` describes the query; the database's type comes from the server. The pair decides the search:

| Query | Database | Search |
|---|---|---|
| nucleotide | nucleotide | nucleotide vs nucleotide, both strands |
| protein | protein | protein vs protein |
| nucleotide | protein | query translated, then searched against protein |
| protein | nucleotide | not supported (would require translating the database) |

`--extra-arg` accepts only these options: `min-seq-id`, `c`, `cov-mode`, `s` (sensitivity, CPU searches only), and for translated searches `translation-mode` (`1` = six full frames, the default; `0` = ORFs) and `translation-table` (e.g. `11` for bacteria):

```bash
apiblast submit genes.fa --db prot_db --extra-arg translation-table=11 --wait
```

`--word-size`/`--outfmt` were removed in 2.0.

Without `--wait`, prints the bare job ID to stdout — useful for scripting:

```bash
JOB=$(apiblast submit query.fa --query-type protein --db nr)
```

With `--wait`, blocks with a live progress spinner then renders a hit table:

```bash
apiblast submit query.fa --db silva --wait --top 10
```

### `apiblast results <job_id>`

Fetch results for a job. If the job is still running, polls with a progress spinner until it completes.

```
--format    table | tsv | json  [default: table]
--top N     Truncate to top N hits (table and json modes)
```

```bash
# Render a Rich table (e-values colour-coded green/yellow/red)
apiblast results $JOB

# Raw tabular output for downstream tools
apiblast results $JOB --format tsv | blast2bed

# JSON
apiblast results $JOB --format json | jq '.hits[0]'
```

### `apiblast status <job_id>`

Print the current status of a single job (ID, query type, database, elapsed time, status).

### `apiblast databases`

List all databases available on the configured server (name, molecule type, size, description). Servers host MMseqs2 databases.

### `apiblast jobs`

Show recently submitted jobs from this machine, with status refreshed from the server.

```
--status    Filter by status: PENDING | RUNNING | SUCCESS | FAILURE
--limit     Maximum rows to show  [default: 20]
```

### `apiblast cancel <job_id>`

Cancel a pending or running job.

### `apiblast config`

```bash
apiblast config set --server http://blast-server:8000   # save server URL
apiblast config show                                     # print current config
```

---

## Configuration

| Source | Precedence | Example |
|---|---|---|
| `APIBLAST_SERVER` env var | Highest | `export APIBLAST_SERVER=http://blast-server:8000` |
| `~/.config/apiblast/config.json` | — | written by `apiblast config set` |
| Default | Lowest | `http://localhost:8000` |

Local job history is stored in `~/.config/apiblast/history.json`.

If you have been given a priority token, set `APIBLAST_TOKEN` to send it with every request.

---

## Output formats

The `results` and `submit --wait` commands support three output formats:

| Format | Description | Use case |
|---|---|---|
| `table` (default) | Rich table with colour-coded e-values | Interactive review |
| `tsv` | Raw tabular output in BLAST outfmt 6 columns | Piping to downstream tools |
| `json` | Parsed JSON hits | Scripting with `jq` |

E-value colour coding in table mode: green < 1e-10 · yellow < 1e-5 · red ≥ 1e-5
