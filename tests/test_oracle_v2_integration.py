"""End-to-end integration test for Oracle V2 quality_first lifecycle."""
import json
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, ScoringDimension,
    TaskType, TaskStatus, SubmissionStatus,
)
from app.services.oracle import generate_dimensions, give_feedback, batch_score_submissions
from app.scheduler import quality_first_lifecycle


def test_quality_first_full_lifecycle():
    """T0 create → T1 dimensions → T2 submissions + gate + individual score → T3 horizontal score."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # T0: Create task
    task = Task(
        title="市场调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=100.0,
        acceptance_criteria="至少覆盖10个产品", max_revisions=3,
    )
    db.add(task)
    db.commit()

    # T1: Generate dimensions
    dim_gen_result = type("R", (), {"stdout": json.dumps({
        "dimensions": [
            {"id": "substantiveness", "name": "实质性", "type": "fixed",
             "description": "内容质量", "weight": 0.5, "scoring_guidance": "guide"},
            {"id": "completeness", "name": "完整性", "type": "fixed",
             "description": "覆盖度", "weight": 0.5, "scoring_guidance": "guide"},
        ], "rationale": "test"
    }), "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=dim_gen_result):
        generate_dimensions(db, task)
    assert db.query(ScoringDimension).filter(ScoringDimension.task_id == task.id).count() == 2

    # T2: Submit 3 submissions
    gate_pass = json.dumps({
        "overall_passed": True,
        "criteria_checks": [{"criteria": "AC", "passed": True, "evidence": "ok"}],
        "summary": "通过"
    })
    individual_scores = [
        json.dumps({"dimension_scores": {"substantiveness": {"score": 85, "feedback": "好"},
                     "completeness": {"score": 80, "feedback": "好"}}, "revision_suggestions": ["建议A"]}),
        json.dumps({"dimension_scores": {"substantiveness": {"score": 70, "feedback": "中"},
                     "completeness": {"score": 65, "feedback": "中"}}, "revision_suggestions": ["建议B"]}),
        json.dumps({"dimension_scores": {"substantiveness": {"score": 60, "feedback": "弱"},
                     "completeness": {"score": 55, "feedback": "弱"}}, "revision_suggestions": ["建议C"]}),
    ]

    subs = []
    for i in range(3):
        sub = Submission(task_id=task.id, worker_id=f"w{i}", content=f"content {i}", revision=1)
        db.add(sub)
        db.commit()

        call_count = 0
        def mock_sub(*args, idx=i, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return type("R", (), {"stdout": gate_pass, "returncode": 0})()
            return type("R", (), {"stdout": individual_scores[idx], "returncode": 0})()

        with patch("app.services.oracle.subprocess.run", side_effect=mock_sub):
            give_feedback(db, sub.id, task.id)
        db.refresh(sub)
        assert sub.status == SubmissionStatus.gate_passed
        subs.append(sub)

    # T3: Deadline passes → horizontal scoring
    task.deadline = datetime(2025, 1, 1, tzinfo=timezone.utc)
    task.status = TaskStatus.open
    db.commit()

    constraint_clean = json.dumps({
        "submission_label": "X", "effective_cap": None,
        "task_relevance": {"passed": True, "analysis": "ok", "score_cap": None},
        "authenticity": {"passed": True, "analysis": "ok", "flagged_issues": [], "score_cap": None},
    })
    dim_sub = json.dumps({"dimension_id": "substantiveness", "scores": [
        {"submission": "Submission_A", "raw_score": 90, "cap_applied": False, "final_score": 90, "evidence": "best"},
        {"submission": "Submission_B", "raw_score": 70, "cap_applied": False, "final_score": 70, "evidence": "mid"},
        {"submission": "Submission_C", "raw_score": 55, "cap_applied": False, "final_score": 55, "evidence": "low"},
    ]})
    dim_comp = json.dumps({"dimension_id": "completeness", "scores": [
        {"submission": "Submission_A", "raw_score": 85, "cap_applied": False, "final_score": 85, "evidence": "best"},
        {"submission": "Submission_B", "raw_score": 65, "cap_applied": False, "final_score": 65, "evidence": "mid"},
        {"submission": "Submission_C", "raw_score": 50, "cap_applied": False, "final_score": 50, "evidence": "low"},
    ]})

    responses = [
        type("R", (), {"stdout": constraint_clean, "returncode": 0})(),  # constraint sub0
        type("R", (), {"stdout": constraint_clean, "returncode": 0})(),  # constraint sub1
        type("R", (), {"stdout": constraint_clean, "returncode": 0})(),  # constraint sub2
        type("R", (), {"stdout": dim_sub, "returncode": 0})(),           # dim: substantiveness
        type("R", (), {"stdout": dim_comp, "returncode": 0})(),          # dim: completeness
    ]
    call_idx = 0
    def mock_batch(*args, **kwargs):
        nonlocal call_idx
        r = responses[call_idx]
        call_idx += 1
        return r

    with patch("app.services.oracle.subprocess.run", side_effect=mock_batch), \
         patch("app.services.escrow.create_challenge_onchain", return_value="0xtx"):
        quality_first_lifecycle(db=db)

    db.refresh(task)
    for s in subs:
        db.refresh(s)

    assert task.status in (TaskStatus.scoring, TaskStatus.challenge_window)
    assert subs[0].status == SubmissionStatus.scored
    feedback = json.loads(subs[0].oracle_feedback)
    assert feedback["type"] == "scoring"
    assert feedback["rank"] == 1

    db.close()
