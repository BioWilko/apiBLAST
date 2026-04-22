#!/usr/bin/env bash
# Print a recommended CELERY_CONCURRENCY value for this machine.
# Run this once during deployment and paste the result into your .env file.
#
# Formula: available cores minus 2 (reserved for OS + uvicorn API process).
# With num_threads=1 hardcoded in BLAST, one Celery worker slot = one CPU core.

set -euo pipefail

if command -v nproc &>/dev/null; then
    CORES=$(nproc --all)
elif command -v sysctl &>/dev/null; then
    CORES=$(sysctl -n hw.logicalcpu)
else
    echo "ERROR: cannot determine CPU count" >&2
    exit 1
fi

CONCURRENCY=$(( CORES > 2 ? CORES - 2 : 1 ))

echo "CELERY_CONCURRENCY=${CONCURRENCY}   # ${CORES} logical cores detected"
echo ""
echo "Also set MAX_QUEUE_DEPTH=$(( CONCURRENCY * 4 ))   # CELERY_CONCURRENCY * 4"
