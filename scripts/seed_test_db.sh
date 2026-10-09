#!/usr/bin/env bash
# Create tiny MMseqs2 databases for local testing and E2E tests.
#
# Usage:
#   ./scripts/seed_test_db.sh [output_dir]
#
# Builds, from the FASTA fixtures in tests/e2e/data/:
#   <output_dir>/nt_small/nt_small     nucleotide DB with a blastn index
#   <output_dir>/prot_small/prot_small padded protein DB (GPU-compatible)
# Add the printed databases.yml snippet to your databases.yml to use them.
#
# Requires `mmseqs` on PATH (or set MMSEQS to its path).

set -euo pipefail

MMSEQS="${MMSEQS:-mmseqs}"
OUT_DIR="${1:-/tmp/apiblast_test_db}"
DATA_DIR="$(cd "$(dirname "$0")/../tests/e2e/data" && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

mkdir -p "${OUT_DIR}/nt_small" "${OUT_DIR}/prot_small"

# Nucleotide: createdb + createindex for nucleotide (blastn) searches
"${MMSEQS}" createdb "${DATA_DIR}/nt_small.fasta" "${OUT_DIR}/nt_small/nt_small" \
    --dbtype 2 -v 1
"${MMSEQS}" createindex "${OUT_DIR}/nt_small/nt_small" "${TMP_DIR}" \
    --search-type 3 -v 1

# Protein: padded for GPU searches (also searchable on CPU, unindexed)
"${MMSEQS}" createdb "${DATA_DIR}/prot_small.fasta" "${TMP_DIR}/prot_small_raw" \
    --dbtype 1 -v 1
"${MMSEQS}" makepaddedseqdb "${TMP_DIR}/prot_small_raw" "${OUT_DIR}/prot_small/prot_small" -v 1

echo ""
echo "Databases created in: ${OUT_DIR}"
echo "Add to databases.yml:"
echo "  - name: nt_small"
echo "    path: ${OUT_DIR}/nt_small"
echo "    type: nucleotide"
echo "    description: \"Tiny nucleotide test database\""
echo "  - name: prot_small"
echo "    path: ${OUT_DIR}/prot_small"
echo "    type: protein"
echo "    description: \"Tiny protein test database\""
