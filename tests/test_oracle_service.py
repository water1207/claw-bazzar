import json
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, TaskType, TaskStatus, SubmissionStatus


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_quality_task(db):
    from datetime import datetime, timezone, timedelta
    task = Task(
        title="Q", description="desc", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        bounty=1.0, max_revisions=3,
    )
    db.add(task)
    db.flush()
    return task


def make_pending_submission(db, task_id, worker_id="w1"):
    sub = Submission(
        task_id=task_id, worker_id=worker_id, revision=1,
        content="my answer", status=SubmissionStatus.pending,
    )
    db.add(sub)
    db.flush()
    return sub


FAKE_FEEDBACK = json.dumps({"suggestions": ["建议A", "建议B", "建议C"]})
FAKE_SCORE = json.dumps({"score": 0.75, "feedback": "good"})


def test_give_feedback_stores_suggestions_and_keeps_pending():
    db = make_db()
    task = make_quality_task(db)
    sub = make_pending_submission(db, task.id)
    db.commit()

    mock_result = type("R", (), {"stdout": FAKE_FEEDBACK, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        from app.services.oracle import give_feedback
        give_feedback(db, sub.id, task.id)

    db.refresh(sub)
    assert sub.status == SubmissionStatus.pending  # stays pending
    assert sub.score is None                        # no score yet
    suggestions = json.loads(sub.oracle_feedback)
    assert len(suggestions) == 3
    assert suggestions[0] == "建议A"


def test_batch_score_submissions_scores_all_pending():
    db = make_db()
    task = make_quality_task(db)
    s1 = make_pending_submission(db, task.id, "w1")
    s2 = make_pending_submission(db, task.id, "w2")
    db.commit()

    mock_result = type("R", (), {"stdout": FAKE_SCORE, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        from app.services.oracle import batch_score_submissions
        batch_score_submissions(db, task.id)

    db.refresh(s1)
    db.refresh(s2)
    assert s1.status == SubmissionStatus.scored
    assert s1.score == 0.75
    assert s2.status == SubmissionStatus.scored
    assert s2.score == 0.75


def test_batch_score_skips_already_scored():
    db = make_db()
    task = make_quality_task(db)
    s1 = make_pending_submission(db, task.id, "w1")
    s1.status = SubmissionStatus.scored
    s1.score = 0.9
    db.commit()

    mock_result = type("R", (), {"stdout": FAKE_SCORE, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result) as mock_run:
        from app.services.oracle import batch_score_submissions
        batch_score_submissions(db, task.id)

    mock_run.assert_not_called()  # already scored, oracle not called
