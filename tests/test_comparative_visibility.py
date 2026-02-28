"""Tests for comparative_feedback visibility and score phase rules."""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, ScoringDimension, TaskType, TaskStatus, SubmissionStatus


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_task(db, status=TaskStatus.open):
    task = Task(
        title="T", description="D", type=TaskType.quality_first,
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        bounty=1.0, status=status,
    )
    db.add(task)
    db.flush()
    return task


def _make_sub(db, task_id, comparative_feedback=None):
    sub = Submission(
        task_id=task_id, worker_id="w1", content="c", revision=1,
        status=SubmissionStatus.scored, score=0.85,
        oracle_feedback=json.dumps({"type": "scoring", "rank": 1, "final_score": 85}),
        comparative_feedback=comparative_feedback,
    )
    db.add(sub)
    db.flush()
    return sub


def test_hide_comparative_feedback_open(db):
    """open phase: score=null, comparative_feedback=null."""
    from app.routers.submissions import _maybe_hide_score
    task = _make_task(db, TaskStatus.open)
    cf = json.dumps({"winner_rationale": "A wins", "rankings": []})
    sub = _make_sub(db, task.id, comparative_feedback=cf)
    db.commit()
    result = _maybe_hide_score(sub, task, db)
    assert result.score is None
    assert result.comparative_feedback is None


def test_hide_comparative_feedback_scoring(db):
    """scoring phase: score visible, comparative_feedback=null."""
    from app.routers.submissions import _maybe_hide_score
    task = _make_task(db, TaskStatus.scoring)
    cf = json.dumps({"winner_rationale": "A wins", "rankings": []})
    sub = _make_sub(db, task.id, comparative_feedback=cf)
    db.commit()
    result = _maybe_hide_score(sub, task, db)
    assert result.score is not None
    assert result.comparative_feedback is None


def test_show_comparative_feedback_challenge_window(db):
    """challenge_window phase: score visible, comparative_feedback visible."""
    from app.routers.submissions import _maybe_hide_score
    task = _make_task(db, TaskStatus.challenge_window)
    cf = json.dumps({"winner_rationale": "A wins", "rankings": []})
    sub = _make_sub(db, task.id, comparative_feedback=cf)
    db.commit()
    result = _maybe_hide_score(sub, task, db)
    assert result.score is not None
    assert result.comparative_feedback == cf


def test_dimension_score_prompt_includes_winner_advantage():
    """dimension_score prompt template should require winner_advantage in output."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "oracle"))
    from dimension_score import PROMPT_TEMPLATE
    assert "winner_advantage" in PROMPT_TEMPLATE


def test_batch_score_sets_comparative_feedback_on_winner(db):
    """batch_score_submissions should populate comparative_feedback on the rank=1 submission."""
    from app.services.oracle import batch_score_submissions

    task = Task(
        title="T", description="D", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria=json.dumps(["AC"]),
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="d", weight=0.5, scoring_guidance="g"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="d", weight=0.5, scoring_guidance="g"
    )
    db.add_all([dim1, dim2])
    db.commit()

    sub1 = Submission(
        task_id=task.id, worker_id="w1", content="content A",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 80, "evidence": "good"},
                "completeness": {"band": "B", "score": 75, "evidence": "ok"},
            },
            "revision_suggestions": []
        })
    )
    sub2 = Submission(
        task_id=task.id, worker_id="w2", content="content B",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "C", "score": 60, "evidence": "basic"},
                "completeness": {"band": "C", "score": 55, "evidence": "incomplete"},
            },
            "revision_suggestions": []
        })
    )
    db.add_all([sub1, sub2])
    db.commit()

    mock_dim_sub = json.dumps({
        "dimension_id": "substantiveness",
        "comparative_analysis": "A > B",
        "winner_advantage": "A 的分析更深入全面",
        "scores": [
            {"submission": "Submission_A", "raw_score": 85, "final_score": 85, "evidence": "good"},
            {"submission": "Submission_B", "raw_score": 70, "final_score": 70, "evidence": "ok"},
        ]
    })
    mock_dim_comp = json.dumps({
        "dimension_id": "completeness",
        "comparative_analysis": "A > B",
        "winner_advantage": "A 覆盖了所有验收标准",
        "scores": [
            {"submission": "Submission_A", "raw_score": 80, "final_score": 80, "evidence": "good"},
            {"submission": "Submission_B", "raw_score": 60, "final_score": 60, "evidence": "ok"},
        ]
    })

    responses = [
        type("R", (), {"stdout": mock_dim_sub, "returncode": 0})(),
        type("R", (), {"stdout": mock_dim_comp, "returncode": 0})(),
    ]
    call_idx = 0

    def mock_subprocess(*args, **kwargs):
        nonlocal call_idx
        result = responses[call_idx]
        call_idx += 1
        return result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        batch_score_submissions(db, task.id)

    db.refresh(sub1)
    db.refresh(sub2)

    # Winner (sub1, rank=1) should have comparative_feedback
    assert sub1.comparative_feedback is not None
    cf = json.loads(sub1.comparative_feedback)
    assert "winner_rationale" in cf
    assert "rankings" in cf
    assert len(cf["rankings"]) == 2
    assert cf["rankings"][0]["rank"] == 1

    # Non-winner (sub2, rank=2) should NOT have comparative_feedback
    assert sub2.comparative_feedback is None
