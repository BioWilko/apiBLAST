#!/usr/bin/env bash
# Create a tiny BLAST nucleotide database for local testing and E2E tests.
#
# Usage:
#   ./scripts/seed_test_db.sh [output_dir [db_name]]
#
# Output: <output_dir>/<db_name>.* (BLAST index files)
# Add the printed databases.yml snippet to your databases.yml to use it.

set -euo pipefail

OUT_DIR="${1:-/tmp/blast_test_db}"
DB_NAME="${2:-nt_small}"
mkdir -p "${OUT_DIR}"

FASTA="${OUT_DIR}/${DB_NAME}.fasta"

cat > "${FASTA}" <<'FASTA'
>seq_alpha
ATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGC
ATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGC
>seq_beta
TTTTAAAACCCCGGGGTTTTAAAACCCCGGGGTTTTAAAACCCCGGGGTTTTAAAACCCCGGGG
TTTTAAAACCCCGGGGTTTTAAAACCCCGGGGTTTTAAAACCCCGGGGTTTTAAAACCCCGGGG
>seq_gamma
GCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGC
GCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGCGC
>seq_delta
AAAAGGGGCCCCTTTTAAAAGGGGCCCCTTTTAAAAGGGGCCCCTTTTAAAAGGGGCCCCTTTT
AAAAGGGGCCCCTTTTAAAAGGGGCCCCTTTTAAAAGGGGCCCCTTTTAAAAGGGGCCCCTTTT
>seq_epsilon
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
FASTA

makeblastdb \
    -in "${FASTA}" \
    -dbtype nucl \
    -out "${OUT_DIR}/nt_small" \
    -title "Test sequences"

echo ""
echo "Database created at: ${OUT_DIR}/nt_small"
echo "Add to databases.yml:"
echo "  - name: nt_small"
echo "    path: ${OUT_DIR}/nt_small"
echo "    type: nucleotide"
echo "    description: \"Tiny test database for smoke testing\""
