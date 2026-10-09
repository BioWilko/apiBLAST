"""Build and run MMseqs2 search commands.

Every job is a single ``mmseqs easy-search`` against a prebuilt target database.
Program names keep their BLAST spelling and map onto MMseqs2 search types:

- blastn: nucleotide query vs nucleotide DB (``--search-type 3``, both strands)
- blastp: protein query vs protein DB (``--search-type 1``)
- blastx: translated nucleotide query vs protein DB (``--search-type 2``); only
  the query is translated
"""
import json
import os
import signal
import subprocess
from pathlib import Path

from app.config import get_settings
from app.models.db import Job
from app.models.schemas import GPU_PROGRAMS, PROGRAMS
from app.services.db_scanner import get_database_path

_SEARCH_TYPE_ARGS = {
    # MMseqs2 defaults to the forward strand only
    "blastn": ["--search-type", "3", "--strand", "2"],
    "blastp": ["--search-type", "1"],
    "blastx": ["--search-type", "2"],
}

# The 12 BLAST outfmt 6 columns. The MMseqs2 default has fident (0-1) where
# BLAST has pident (0-100).
FORMAT_OUTPUT = "query,target,pident,alnlen,mismatch,gapopen,qstart,qend,tstart,tend,evalue,bits"

# --max-seqs limits prefilter candidates, not reported hits, so it stays at the
# MMseqs2 default or above; max_hits is applied to the results afterwards.
_MIN_PREFILTER_SEQS = 300

# 1 = translate the six reading frames end to end; 0 = ORFs (MMseqs2 default)
_BLASTX_DEFAULT_TRANSLATION_MODE = "1"


def _render_arg(key: str) -> str:
    return f"-{key}" if len(key) == 1 else f"--{key}"


def build_blast_command(
    job: Job,
    query_file: Path,
    result_file: Path,
    tmp_dir: Path,
    use_gpu: bool = False,
) -> list[str]:
    """Return a safe, shell=False command list for running an MMseqs2 search.

    Raises ValueError if the program is unsupported or cannot run on the GPU.
    Raises FileNotFoundError if the mmseqs binary is not found.
    """
    settings = get_settings()

    if job.program not in PROGRAMS:
        raise ValueError(f"Unknown program: {job.program!r}")
    if use_gpu and job.program not in GPU_PROGRAMS:
        raise ValueError(f"Program {job.program!r} cannot run on the GPU")

    binary = settings.MMSEQS_BIN
    if not binary.exists():
        raise FileNotFoundError(
            f"mmseqs binary not found: {binary}. Check MMSEQS_BIN setting."
        )

    cmd: list[str] = [
        str(binary), "easy-search",
        str(query_file),
        str(get_database_path(job.database)),
        str(result_file),
        str(tmp_dir),
        "-e",              str(job.evalue),
        "--max-seqs",      str(max(job.max_hits, _MIN_PREFILTER_SEQS)),
        "--threads",       str(settings.MMSEQS_THREADS),
        "--format-mode",   "0",
        "--format-output", FORMAT_OUTPUT,
        "--remove-tmp-files", "1",
        *_SEARCH_TYPE_ARGS[job.program],
    ]

    extra = json.loads(job.extra_args_json) if job.extra_args_json else {}

    if job.program == "blastx" and "translation-mode" not in extra:
        cmd += ["--translation-mode", _BLASTX_DEFAULT_TRANSLATION_MODE]

    if use_gpu:
        cmd += ["--gpu", "1"]

    for key, val in extra.items():
        cmd += [_render_arg(key), str(val)]

    return cmd


def run_blast(
    cmd: list[str],
    timeout_s: int | None = None,
) -> subprocess.CompletedProcess:
    """Execute an MMseqs2 command and return the CompletedProcess result.

    MMseqs2 workflows are shell scripts that spawn child processes, so the
    command runs in its own session and the whole process group is killed on
    timeout or any other interruption (e.g. SoftTimeLimitExceeded).

    Raises subprocess.TimeoutExpired if timeout_s is exceeded.
    Raises FileNotFoundError if the binary path is wrong.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except BaseException:
        _kill_process_group(proc)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()
