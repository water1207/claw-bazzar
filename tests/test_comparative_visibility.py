"""Tests for comparative_feedback visibility and score phase rules."""
import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, TaskType, TaskStatus, SubmissionStatus


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
