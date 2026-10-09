"""Unit tests for result_store helpers."""
from app.services.result_store import (
    cap_hits_per_query,
    finalise_results,
    parse_outfmt6,
    to_blast_strand_convention,
)

# MMseqs2 prints integer bit scores and upper-case exponents
MMSEQS_TSV = (
    "q1\tA\t100.0\t50\t0\t0\t1\t50\t1\t50\t1.234E-20\t95\n"
    "q1\tB\t90.0\t50\t5\t0\t1\t50\t11\t60\t3.1E-10\t60\n"
    "q1\tC\t80.0\t50\t10\t0\t1\t50\t21\t70\t1.0E-05\t40\n"
    "q2\tA\t99.0\t40\t0\t0\t1\t40\t40\t1\t2.0E-15\t80\n"
    "q2\tD\t70.0\t40\t12\t1\t1\t40\t5\t44\t1.0E-02\t30\n"
)


def test_parse_mmseqs_tabular_output():
    hits = parse_outfmt6(MMSEQS_TSV)
    assert len(hits) == 5
    assert hits[0]["pct_identity"] == 100.0
    assert hits[0]["evalue"] == "1.234E-20"
    assert hits[0]["bitscore"] == 95.0
    assert hits[3]["s_start"] > hits[3]["s_end"]


def test_cap_hits_per_query_keeps_best_subjects(tmp_path):
    path = tmp_path / "result.tsv"
    path.write_text(MMSEQS_TSV)
    cap_hits_per_query(path, 2)
    hits = parse_outfmt6(path.read_text())
    assert [(h["query_id"], h["subject_id"]) for h in hits] == [
        ("q1", "A"), ("q1", "B"), ("q2", "A"), ("q2", "D"),
    ]


def test_cap_hits_per_query_keeps_all_rows_of_kept_subject(tmp_path):
    path = tmp_path / "result.tsv"
    path.write_text(
        "q1\tA\t100.0\t50\t0\t0\t1\t50\t1\t50\t1E-20\t95\n"
        "q1\tB\t90.0\t50\t5\t0\t1\t50\t11\t60\t1E-10\t60\n"
        "q1\tA\t85.0\t30\t4\t0\t60\t90\t70\t100\t1E-05\t40\n"
    )
    cap_hits_per_query(path, 1)
    assert [h["subject_id"] for h in parse_outfmt6(path.read_text())] == ["A", "A"]


def test_cap_hits_per_query_empty_file(tmp_path):
    path = tmp_path / "result.tsv"
    path.write_text("")
    cap_hits_per_query(path, 5)
    assert path.read_text() == ""


def test_reverse_strand_hit_rewritten_to_blast_convention(tmp_path):
    path = tmp_path / "result.tsv"
    path.write_text(
        "fwd\tseq_b\t100.000\t400\t0\t0\t1\t400\t101\t500\t2.0E-224\t718\n"
        "rev\tseq_b\t100.000\t400\t0\t0\t400\t1\t101\t500\t2.0E-224\t718\n"
    )
    to_blast_strand_convention(path)
    fwd, rev = parse_outfmt6(path.read_text())
    assert (fwd["q_start"], fwd["q_end"], fwd["s_start"], fwd["s_end"]) == (1, 400, 101, 500)
    assert (rev["q_start"], rev["q_end"], rev["s_start"], rev["s_end"]) == (1, 400, 500, 101)


def test_finalise_only_flips_strand_for_blastn(tmp_path):
    row = "q\tp\t90.0\t100\t10\t0\t300\t1\t1\t100\t1E-30\t150\n"
    blastx = tmp_path / "blastx.tsv"
    blastx.write_text(row)
    finalise_results(blastx, "blastx", 50)
    assert blastx.read_text() == row

    blastn = tmp_path / "blastn.tsv"
    blastn.write_text(row)
    finalise_results(blastn, "blastn", 50)
    hit = parse_outfmt6(blastn.read_text())[0]
    assert (hit["q_start"], hit["q_end"], hit["s_start"], hit["s_end"]) == (1, 300, 100, 1)
