import json
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, ScoringDimension, TaskType, TaskStatus, SubmissionStatus


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


FAKE_GATE_PASS = json.dumps({
    "overall_passed": True,
    "criteria_checks": [{"criteria": "AC", "passed": True, "evidence": "ok"}],
    "summary": "通过"
})
FAKE_INDIVIDUAL = json.dumps({
    "dimension_scores": {
        "substantiveness": {"score": 72, "feedback": "ok"},
    },
    "revision_suggestions": ["建议A", "建议B", "建议C"]
})
FAKE_SCORE = json.dumps({"score": 0.75, "feedback": "good"})


def test_give_feedback_gate_pass_sets_gate_passed():
    """V2: gate pass + individual score → gate_passed status."""
    db = make_db()
    task = make_quality_task(db)

    dim = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="desc", weight=1.0, scoring_guidance="guide"
    )
    db.add(dim)

    sub = make_pending_submission(db, task.id)
    db.commit()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return type("R", (), {"stdout": FAKE_GATE_PASS, "returncode": 0})()
        return type("R", (), {"stdout": FAKE_INDIVIDUAL, "returncode": 0})()

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        from app.services.oracle import give_feedback
        give_feedback(db, sub.id, task.id)

    db.refresh(sub)
    assert sub.status == SubmissionStatus.gate_passed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "individual_scoring"
    assert len(feedback["revision_suggestions"]) == 3


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


def test_give_feedback_marks_policy_violation_on_injection(db_session):
    import json as _json
    import datetime
    from unittest.mock import patch
    from app.models import Task, Submission, User, UserRole, TaskType, TaskStatus, SubmissionStatus, TrustEvent, TrustEventType
    from app.services.oracle import give_feedback

    worker = User(id="w1", nickname="w1", wallet="0xW1", role=UserRole.worker)
    db_session.add(worker)

    task = Task(
        title="t", description="d", type=TaskType.quality_first,
        deadline=datetime.datetime(2099, 1, 1), publisher_id="p",
        bounty=0, status=TaskStatus.open
    )
    db_session.add(task)
    db_session.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="inject attempt", revision=1)
    db_session.add(sub)
    db_session.commit()

    injection_result = {
        "injection_detected": True,
        "reason": "instruction_override_en matched",
        "field": "submission_payload"
    }
    with patch("app.services.oracle._call_oracle", return_value=injection_result), \
         patch("app.services.staking.check_and_slash", return_value=False):
        give_feedback(db_session, sub.id, task.id)

    db_session.refresh(sub)
    assert sub.status == SubmissionStatus.policy_violation
    feedback = _json.loads(sub.oracle_feedback)
    assert feedback["type"] == "injection"
    assert "reason" in feedback

    # Verify worker_malicious trust event was applied
    event = db_session.query(TrustEvent).filter_by(user_id="w1", event_type=TrustEventType.worker_malicious).first()
    assert event is not None
    db_session.refresh(worker)
    assert worker.trust_score == 400.0  # 500 - 100


def test_score_submission_marks_policy_violation_on_injection(db_session):
    import json as _json
    import datetime
    from unittest.mock import patch
    from app.models import Task, Submission, User, UserRole, TaskType, TaskStatus, SubmissionStatus, TrustEvent, TrustEventType
    from app.services.oracle import score_submission

    worker = User(id="w1", nickname="w1ff", wallet="0xW1", role=UserRole.worker)
    db_session.add(worker)

    task = Task(
        title="t", description="d", type=TaskType.fastest_first, threshold=60,
        deadline=datetime.datetime(2099, 1, 1), publisher_id="p",
        bounty=0, status=TaskStatus.open
    )
    db_session.add(task)
    db_session.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="inject attempt", revision=1)
    db_session.add(sub)
    db_session.commit()

    injection_result = {
        "injection_detected": True,
        "reason": "role_injection_en matched",
        "field": "submission_payload"
    }
    with patch("app.services.oracle._call_oracle", return_value=injection_result), \
         patch("app.services.staking.check_and_slash", return_value=False):
        score_submission(db_session, sub.id, task.id)

    db_session.refresh(sub)
    assert sub.status == SubmissionStatus.policy_violation

    # Verify worker_malicious trust event was applied
    event = db_session.query(TrustEvent).filter_by(user_id="w1", event_type=TrustEventType.worker_malicious).first()
    assert event is not None
    db_session.refresh(worker)
    assert worker.trust_score == 400.0  # 500 - 100
