"""Tests for oracle.py mode routing."""
import json
import subprocess
import sys


def test_oracle_legacy_feedback_mode():
    """Existing feedback mode should still work."""
    payload = json.dumps({"mode": "feedback"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "suggestions" in output
    assert len(output["suggestions"]) == 3


def test_oracle_legacy_score_mode():
    """Existing score mode should still work."""
    payload = json.dumps({"mode": "score"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
    assert 0.5 <= output["score"] <= 1.0


def test_oracle_unknown_mode_falls_back_to_legacy():
    """Unknown modes should fall back to legacy score behavior."""
    payload = json.dumps({"mode": "nonexistent"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
