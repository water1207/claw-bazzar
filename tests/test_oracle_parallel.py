"""Test that dimension_score calls are parallelized."""
import json
import time
import threading
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, ScoringDimension, TaskType, SubmissionStatus


def test_dimension_score_calls_run_in_parallel():
    """Verify multiple dimension_score calls execute concurrently."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    task = Task(
        title="Test", description="Desc", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria=json.dumps(["AC"]),
    )
    db.add(task)
    db.commit()

    for dim_id, name, w in [("substantiveness", "实质性", 0.34),
                             ("credibility", "可信度", 0.33),
                             ("completeness", "完整性", 0.33)]:
        db.add(ScoringDimension(
            task_id=task.id, dim_id=dim_id, name=name,
            dim_type="fixed", description="d", weight=w, scoring_guidance="g"
        ))
    db.commit()

    sub = Submission(
        task_id=task.id, worker_id="w1", content="content",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 80, "evidence": "g", "feedback": "g"},
                "credibility": {"band": "B", "score": 70, "evidence": "g", "feedback": "g"},
                "completeness": {"band": "B", "score": 75, "evidence": "g", "feedback": "g"},
            },
            "overall_band": "B",
            "revision_suggestions": []
        })
    )
    db.add(sub)
    db.commit()

    concurrent_threads = []
    call_lock = threading.Lock()

    def make_dim_response(dim_id):
        return json.dumps({
            "dimension_id": dim_id, "scores": [
                {"submission": "Submission_A", "raw_score": 80, "final_score": 80, "evidence": "ok"}
            ]
        })

    def mock_subprocess(*args, **kwargs):
        with call_lock:
            concurrent_threads.append(threading.current_thread().name)
        payload = json.loads(kwargs.get("input", "{}"))
        dim_id = payload.get("dimension", {}).get("id", "substantiveness")
        time.sleep(0.05)  # Simulate LLM latency
        return type("R", (), {"stdout": make_dim_response(dim_id), "returncode": 0})()

    from app.services.oracle import batch_score_submissions
    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        start = time.monotonic()
        batch_score_submissions(db, task.id)
        elapsed = time.monotonic() - start

    # With 3 dims × 0.05s each:
    # Sequential: ~0.15s, Parallel: ~0.05s
    assert elapsed < 0.12, f"Expected parallel execution, but took {elapsed:.3f}s"

    # Verify multiple threads were used
    unique_threads = set(concurrent_threads)
    assert len(unique_threads) > 1, f"Expected multiple threads but got: {unique_threads}"

    db.close()
