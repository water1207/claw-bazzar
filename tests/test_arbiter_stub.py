import json
import subprocess
import sys
from pathlib import Path

ARBITER_SCRIPT = Path(__file__).parent.parent / "oracle" / "arbiter.py"


def test_arbiter_stub_rejects_all():
    payload = json.dumps({
        "task": {"id": "t1", "description": "test"},
        "winner_submission": {"id": "s1", "content": "winner content", "score": 0.9},
        "challenges": [
            {
                "id": "c1",
                "reason": "I am better",
                "challenger_submission": {"id": "s2", "content": "challenger content", "score": 0.85},
            },
            {
                "id": "c2",
                "reason": "Me too",
                "challenger_submission": {"id": "s3", "content": "another", "score": 0.7},
            },
        ],
    })
    result = subprocess.run(
        [sys.executable, str(ARBITER_SCRIPT)],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output["verdicts"]) == 2
    for v in output["verdicts"]:
        assert v["verdict"] == "rejected"
        assert v["score"] == 0
        assert "Stub arbiter" in v["feedback"]
