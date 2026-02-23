import json
import subprocess
import sys
from pathlib import Path

ORACLE = Path(__file__).parent.parent / "oracle" / "oracle.py"


def test_oracle_stub_returns_valid_json():
    payload = json.dumps({
        "task": {"id": "t1", "description": "do something", "type": "fastest_first", "threshold": 0.7},
        "submission": {"id": "s1", "content": "my answer", "revision": 1, "worker_id": "w1"},
    })
    result = subprocess.run(
        [sys.executable, str(ORACLE)],
        input=payload, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
    assert isinstance(output["score"], float)
    assert "feedback" in output


def test_oracle_stub_feedback_mode():
    payload = json.dumps({
        "mode": "feedback",
        "task": {"id": "t1", "description": "do something", "type": "quality_first", "threshold": None},
        "submission": {"id": "s1", "content": "my answer", "revision": 1, "worker_id": "w1"},
    })
    result = subprocess.run(
        [sys.executable, str(ORACLE)],
        input=payload, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "suggestions" in output
    assert isinstance(output["suggestions"], list)
    assert len(output["suggestions"]) == 3
    assert "score" not in output


def test_oracle_stub_score_mode_explicit():
    payload = json.dumps({
        "mode": "score",
        "task": {"id": "t1", "description": "do something", "type": "quality_first", "threshold": None},
        "submission": {"id": "s1", "content": "my answer", "revision": 1, "worker_id": "w1"},
    })
    result = subprocess.run(
        [sys.executable, str(ORACLE)],
        input=payload, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
    assert 0.5 <= output["score"] <= 1.0
