"""Unit tests for search cost estimation."""
import pytest

from app.services.cost import estimate_cost, is_heavy

GB = 10**9


def test_baseline_blastp():
    # 1000 aa against 1 GB at default sensitivity and max_hits
    assert estimate_cost("blastp", 1000, GB, 50, {}) == pytest.approx(1.0)


@pytest.mark.parametrize("program", ["blastn", "blastx"])
def test_nucleotide_query_programs_cost_double(program):
    assert estimate_cost(program, 1000, GB, 50, {}) == pytest.approx(2.0)


def test_scales_with_query_and_database():
    assert estimate_cost("blastp", 10_000, 50 * GB, 50, {}) == pytest.approx(500.0)


def test_sensitivity_scales_quadratically():
    assert estimate_cost("blastp", 1000, GB, 50, {"s": 11.4}) == pytest.approx(4.0)


def test_max_hits_below_prefilter_width_is_free():
    assert estimate_cost("blastp", 1000, GB, 300, {}) == estimate_cost("blastp", 1000, GB, 1, {})
    assert estimate_cost("blastp", 1000, GB, 600, {}) == pytest.approx(2.0)


def test_database_size_floor():
    # An unreadable (0 byte) or tiny database still counts as 0.1 GB
    assert estimate_cost("blastp", 1000, 0, 50, {}) == pytest.approx(0.1)


def test_is_heavy_threshold():
    from app.config import get_settings
    threshold = get_settings().COST_HEAVY_THRESHOLD
    assert is_heavy(threshold)
    assert not is_heavy(threshold - 0.01)
