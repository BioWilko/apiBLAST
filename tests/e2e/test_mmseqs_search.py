"""End-to-end searches against real MMseqs2 test databases.

Skipped unless `mmseqs` is on PATH. The databases are built from
tests/e2e/data/ with scripts/seed_test_db.sh. The GPU test additionally needs
a working `nvidia-smi` and APIBLAST_GPU_TESTS=1.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.db import Job
from app.services import blast_runner, result_store

MMSEQS = shutil.which("mmseqs")
REPO = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"

pytestmark = pytest.mark.skipif(MMSEQS is None, reason="mmseqs not installed")


def _gpu_available() -> bool:
    if os.environ.get("APIBLAST_GPU_TESTS") != "1" or not shutil.which("nvidia-smi"):
        return False
    return subprocess.run(["nvidia-smi"], capture_output=True).returncode == 0


def _read_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    name = None
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            records[name] = ""
        elif name:
            records[name] += line.strip()
    return records


def _revcomp(seq: str) -> str:
    return seq.translate(str.maketrans("ACGT", "TGCA"))[::-1]


NT = _read_fasta(DATA / "nt_small.fasta")
PROT = _read_fasta(DATA / "prot_small.fasta")
# gene_a carries prot_a's coding sequence (start codon to stop) after a 120 nt
# random prefix
GENE_A = NT["gene_a"][120:120 + 3 * len(PROT["prot_a"]) + 3]


@pytest.fixture(scope="module")
def db_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("dbs")
    subprocess.run(
        [str(REPO / "scripts" / "seed_test_db.sh"), str(root)],
        check=True, capture_output=True, env={**os.environ, "MMSEQS": MMSEQS},
    )
    return root


def _search(db_root: Path, tmp_path: Path, program: str, database: str, query: str,
            use_gpu: bool = False, extra_args: dict | None = None) -> list[dict]:
    job = MagicMock(spec=Job)
    job.program = program
    job.database = database
    job.evalue = 1e-5
    job.max_hits = 50
    job.extra_args_json = json.dumps(extra_args) if extra_args else None

    query_file = tmp_path / "query.fasta"
    query_file.write_text(query)
    result_file = tmp_path / "result.tsv"

    with patch("app.services.blast_runner.get_settings") as settings, \
         patch("app.services.blast_runner.get_database_path",
               return_value=db_root / database / database):
        settings.return_value.MMSEQS_BIN = Path(MMSEQS)
        settings.return_value.MMSEQS_THREADS = 1
        cmd = blast_runner.build_blast_command(
            job, query_file, result_file, tmp_path / "tmp", use_gpu=use_gpu
        )
    proc = blast_runner.run_blast(cmd, timeout_s=300)
    assert proc.returncode == 0, proc.stderr or proc.stdout[-2000:]
    result_store.finalise_results(result_file, program, job.max_hits)
    return result_store.parse_outfmt6(result_file.read_text())


def test_blastn_forward_hit(db_root, tmp_path):
    hits = _search(db_root, tmp_path, "blastn", "nt_small", f">q\n{NT['seq_b'][100:500]}\n")
    top = hits[0]
    assert top["subject_id"] == "seq_b"
    assert top["pct_identity"] == 100.0
    assert (top["s_start"], top["s_end"]) == (101, 500)


def test_blastn_reverse_complement_hit_uses_blast_convention(db_root, tmp_path):
    query = _revcomp(NT["seq_b"][100:500])
    hits = _search(db_root, tmp_path, "blastn", "nt_small", f">q\n{query}\n")
    top = hits[0]
    assert top["subject_id"] == "seq_b"
    # BLAST: query ascending, subject reversed
    assert (top["q_start"], top["q_end"]) == (1, 400)
    assert (top["s_start"], top["s_end"]) == (500, 101)


def test_blastp_self_hit(db_root, tmp_path):
    hits = _search(db_root, tmp_path, "blastp", "prot_small", f">q\n{PROT['prot_b']}\n")
    assert hits[0]["subject_id"] == "prot_b"
    assert hits[0]["pct_identity"] == 100.0


def test_blastx_minus_strand_maps_to_query_coordinates(db_root, tmp_path):
    hits = _search(db_root, tmp_path, "blastx", "prot_small", f">q\n{_revcomp(GENE_A)}\n")
    top = hits[0]
    assert top["subject_id"] == "prot_a"
    assert top["q_start"] > top["q_end"]


def test_blastx_orf_mode_override(db_root, tmp_path):
    hits = _search(db_root, tmp_path, "blastx", "prot_small", f">q\n{GENE_A}\n",
                   extra_args={"translation-mode": 0})
    assert hits[0]["subject_id"] == "prot_a"
    assert hits[0]["q_start"] < hits[0]["q_end"]


@pytest.mark.skipif(not _gpu_available(), reason="needs a GPU and APIBLAST_GPU_TESTS=1")
def test_blastp_gpu_self_hit(db_root, tmp_path):
    hits = _search(db_root, tmp_path, "blastp", "prot_small", f">q\n{PROT['prot_c']}\n",
                   use_gpu=True)
    assert hits[0]["subject_id"] == "prot_c"
    assert hits[0]["pct_identity"] == 100.0
