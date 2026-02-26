"""Tests for penalized_total scoring formula."""
from app.services.oracle import compute_penalized_total


def test_all_above_threshold():
    """All fixed dims >= 60 → penalty = 1.0, final = base."""
    dim_scores = {
        "substantiveness": {"score": 80, "band": "B"},
        "credibility": {"score": 70, "band": "B"},
        "completeness": {"score": 75, "band": "B"},
        "tech_depth": {"score": 90, "band": "A"},
    }
    dims = [
        {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "tech_depth", "dim_type": "dynamic", "weight": 0.25},
    ]
    result = compute_penalized_total(dim_scores, dims)
    assert result["penalty"] == 1.0
    expected_base = (80 + 70 + 75 + 90) * 0.25
    assert result["weighted_base"] == expected_base
    assert result["final_score"] == expected_base
    assert result["penalty_reasons"] == []
    assert result["risk_flags"] == []


def test_one_fixed_below_threshold():
    """credibility=45 → penalty = 45/60 = 0.75."""
    dim_scores = {
        "substantiveness": {"score": 80, "band": "B"},
        "credibility": {"score": 45, "band": "D", "flag": "below_expected"},
        "completeness": {"score": 75, "band": "B"},
    }
    dims = [
        {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.4},
        {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.3},
        {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.3},
    ]
    result = compute_penalized_total(dim_scores, dims)
    base = 80 * 0.4 + 45 * 0.3 + 75 * 0.3
    assert result["weighted_base"] == base
    assert result["penalty"] == 45 / 60
    assert abs(result["final_score"] - base * (45 / 60)) < 0.01
    assert len(result["penalty_reasons"]) == 1
    assert len(result["risk_flags"]) == 1


def test_two_fixed_below_threshold():
    """credibility=45, substantiveness=40 → penalty = (45/60)*(40/60) ≈ 0.5."""
    dim_scores = {
        "substantiveness": {"score": 40, "band": "D"},
        "credibility": {"score": 45, "band": "D"},
        "completeness": {"score": 75, "band": "B"},
    }
    dims = [
        {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.33},
        {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.33},
        {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.34},
    ]
    result = compute_penalized_total(dim_scores, dims)
    expected_penalty = (40 / 60) * (45 / 60)
    assert abs(result["penalty"] - expected_penalty) < 0.01
    assert len(result["penalty_reasons"]) == 2
    assert len(result["risk_flags"]) == 2


def test_dynamic_dim_below_threshold_no_penalty():
    """Dynamic dims below threshold do NOT trigger penalty."""
    dim_scores = {
        "substantiveness": {"score": 80, "band": "B"},
        "credibility": {"score": 70, "band": "B"},
        "completeness": {"score": 75, "band": "B"},
        "tech_depth": {"score": 30, "band": "D"},
    }
    dims = [
        {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "tech_depth", "dim_type": "dynamic", "weight": 0.25},
    ]
    result = compute_penalized_total(dim_scores, dims)
    assert result["penalty"] == 1.0
    assert result["penalty_reasons"] == []
