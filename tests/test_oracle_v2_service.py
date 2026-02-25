"""Tests for Oracle V2 service layer."""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, ScoringDimension, TaskType, TaskStatus, SubmissionStatus


MOCK_DIM_RESULT = json.dumps({
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "内容质量", "weight": 0.3, "scoring_guidance": "guide1"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "覆盖度", "weight": 0.3, "scoring_guidance": "guide2"},
        {"id": "data_precision", "name": "数据精度", "type": "dynamic",
         "description": "准确性", "weight": 0.4, "scoring_guidance": "guide3"},
    ],
    "rationale": "test"
})


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_generate_dimensions(db):
    from app.services.oracle import generate_dimensions

    task = Task(
        title="市场调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="至少覆盖10个产品",
    )
    db.add(task)
    db.commit()

    mock_result = type("R", (), {"stdout": MOCK_DIM_RESULT, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        dims = generate_dimensions(db, task)

    assert len(dims) == 3
    db_dims = db.query(ScoringDimension).filter(ScoringDimension.task_id == task.id).all()
    assert len(db_dims) == 3
    assert db_dims[0].dim_id in ["substantiveness", "completeness", "data_precision"]


# --- fastest_first tests ---

MOCK_GATE_PASS = json.dumps({
    "overall_passed": True,
    "criteria_checks": [{"criteria": "AC1", "passed": True, "evidence": "ok"}],
    "summary": "通过"
})

MOCK_CONSTRAINT_FF_PASS = json.dumps({
    "task_relevance": {"passed": True, "reason": "切题"},
    "authenticity": {"passed": True, "reason": "可信"},
    "overall_passed": True, "rejection_reason": None,
})

MOCK_CONSTRAINT_FF_FAIL = json.dumps({
    "task_relevance": {"passed": False, "reason": "偏题"},
    "authenticity": {"passed": True, "reason": "可信"},
    "overall_passed": False, "rejection_reason": "提交偏离任务主题",
})


def test_score_submission_fastest_first_pass(db):
    """fastest_first: gate pass + constraint pass → accepted + close task."""
    from app.services.oracle import score_submission

    task = Task(
        title="Test", description="Desc", type=TaskType.fastest_first,
        threshold=0.7, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=0,
    )
    db.add(task)
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="good content")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    constraint_result = type("R", (), {"stdout": MOCK_CONSTRAINT_FF_PASS, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return gate_result
        return constraint_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        with patch("app.services.oracle.pay_winner"):
            score_submission(db, sub.id, task.id)

    db.refresh(sub)
    db.refresh(task)
    assert sub.status == SubmissionStatus.scored
    assert task.status == TaskStatus.closed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "fastest_first_check"
    assert feedback["passed"] is True


def test_score_submission_fastest_first_constraint_fail(db):
    """fastest_first: gate pass + constraint fail → rejected."""
    from app.services.oracle import score_submission

    task = Task(
        title="Test", description="Desc", type=TaskType.fastest_first,
        threshold=0.7, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=0,
    )
    db.add(task)
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="bad content")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    constraint_result = type("R", (), {"stdout": MOCK_CONSTRAINT_FF_FAIL, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return gate_result
        return constraint_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        score_submission(db, sub.id, task.id)

    db.refresh(sub)
    db.refresh(task)
    assert sub.status == SubmissionStatus.scored
    assert task.status == TaskStatus.open  # Not closed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["passed"] is False


# --- quality_first tests ---

MOCK_GATE_FAIL = json.dumps({
    "overall_passed": False,
    "criteria_checks": [
        {"criteria": "至少10个产品", "passed": False,
         "evidence": "仅8个", "revision_hint": "补充2个"}
    ],
    "summary": "未通过验收"
})

MOCK_INDIVIDUAL_SCORE = json.dumps({
    "dimension_scores": {
        "substantiveness": {"score": 72, "feedback": "较充实"},
        "completeness": {"score": 65, "feedback": "基本覆盖"},
    },
    "revision_suggestions": ["建议增加对比分析", "补充数据来源"]
})


def test_give_feedback_gate_fail(db):
    """quality_first gate fail → gate_failed status, oracle_feedback has failure details."""
    from app.services.oracle import give_feedback

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="至少覆盖10个产品",
    )
    db.add(task)
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="仅8个产品")
    db.add(sub)
    db.commit()

    mock_result = type("R", (), {"stdout": MOCK_GATE_FAIL, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        give_feedback(db, sub.id, task.id)

    db.refresh(sub)
    assert sub.status == SubmissionStatus.gate_failed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "gate_check"
    assert feedback["overall_passed"] is False


def test_give_feedback_gate_pass_then_individual_score(db):
    """quality_first gate pass → score_individual → gate_passed, revision suggestions stored."""
    from app.services.oracle import give_feedback

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="至少覆盖10个产品",
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="内容质量", weight=0.5, scoring_guidance="guide"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="覆盖度", weight=0.5, scoring_guidance="guide"
    )
    db.add_all([dim1, dim2])
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="12个产品调研")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    individual_result = type("R", (), {"stdout": MOCK_INDIVIDUAL_SCORE, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return gate_result
        return individual_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        give_feedback(db, sub.id, task.id)

    db.refresh(sub)
    assert sub.status == SubmissionStatus.gate_passed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "individual_scoring"
    assert "revision_suggestions" in feedback
    assert len(feedback["revision_suggestions"]) == 2


# --- batch_score_submissions tests ---

MOCK_CONSTRAINT_QF_CLEAN = json.dumps({
    "submission_label": "Submission_A",
    "task_relevance": {"passed": True, "analysis": "ok", "score_cap": None},
    "authenticity": {"passed": True, "analysis": "ok", "flagged_issues": [], "score_cap": None},
    "effective_cap": None,
})

MOCK_DIM_SCORE_SUB = json.dumps({
    "dimension_id": "substantiveness",
    "dimension_name": "实质性",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 85, "cap_applied": False,
         "final_score": 85, "evidence": "good"},
        {"submission": "Submission_B", "raw_score": 70, "cap_applied": False,
         "final_score": 70, "evidence": "ok"},
    ]
})

MOCK_DIM_SCORE_COMP = json.dumps({
    "dimension_id": "completeness",
    "dimension_name": "完整性",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 80, "cap_applied": False,
         "final_score": 80, "evidence": "good"},
        {"submission": "Submission_B", "raw_score": 60, "cap_applied": False,
         "final_score": 60, "evidence": "ok"},
    ]
})


def test_batch_score_submissions_horizontal(db):
    """After deadline: top 3 → constraint check → horizontal scoring → ranking."""
    from app.services.oracle import batch_score_submissions

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="至少10个产品",
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="内容质量", weight=0.5, scoring_guidance="guide"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="覆盖度", weight=0.5, scoring_guidance="guide"
    )
    db.add_all([dim1, dim2])
    db.commit()

    # Create 2 gate_passed submissions with individual scores
    sub1 = Submission(
        task_id=task.id, worker_id="w1", content="content A",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"score": 80, "feedback": "good"},
                "completeness": {"score": 75, "feedback": "ok"},
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
                "substantiveness": {"score": 60, "feedback": "basic"},
                "completeness": {"score": 55, "feedback": "incomplete"},
            },
            "revision_suggestions": []
        })
    )
    db.add_all([sub1, sub2])
    db.commit()

    # Mock: constraint_check for each sub, then dimension_score for each dim
    responses = [
        type("R", (), {"stdout": MOCK_CONSTRAINT_QF_CLEAN, "returncode": 0})(),
        type("R", (), {"stdout": MOCK_CONSTRAINT_QF_CLEAN, "returncode": 0})(),
        type("R", (), {"stdout": MOCK_DIM_SCORE_SUB, "returncode": 0})(),
        type("R", (), {"stdout": MOCK_DIM_SCORE_COMP, "returncode": 0})(),
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
    assert sub1.status == SubmissionStatus.scored
    assert sub2.status == SubmissionStatus.scored

    feedback1 = json.loads(sub1.oracle_feedback)
    feedback2 = json.loads(sub2.oracle_feedback)
    assert feedback1["type"] == "scoring"
    assert feedback1["rank"] == 1
    assert feedback2["rank"] == 2
    assert feedback1["weighted_total"] > feedback2["weighted_total"]


# --- Scheduler lifecycle test ---

from app.scheduler import quality_first_lifecycle


def test_lifecycle_phase1_scoring_with_gate_passed_subs(db):
    """Phase 1: deadline expired → scoring, should use gate_passed subs."""
    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2025, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        status=TaskStatus.open,
        acceptance_criteria="至少10个产品",
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="内容质量", weight=0.5, scoring_guidance="guide"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="覆盖度", weight=0.5, scoring_guidance="guide"
    )
    db.add_all([dim1, dim2])
    db.commit()

    sub = Submission(
        task_id=task.id, worker_id="w1", content="content",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"score": 80, "feedback": "good"},
                "completeness": {"score": 70, "feedback": "ok"},
            },
            "revision_suggestions": []
        })
    )
    db.add(sub)
    db.commit()

    constraint_resp = json.dumps({
        "submission_label": "Submission_A",
        "task_relevance": {"passed": True, "analysis": "ok", "score_cap": None},
        "authenticity": {"passed": True, "analysis": "ok", "flagged_issues": [], "score_cap": None},
        "effective_cap": None,
    })
    dim_score_resp = json.dumps({
        "dimension_id": "substantiveness",
        "scores": [{"submission": "Submission_A", "raw_score": 85,
                     "cap_applied": False, "final_score": 85, "evidence": "good"}]
    })
    dim_score_resp2 = json.dumps({
        "dimension_id": "completeness",
        "scores": [{"submission": "Submission_A", "raw_score": 75,
                     "cap_applied": False, "final_score": 75, "evidence": "ok"}]
    })
    responses = [
        type("R", (), {"stdout": constraint_resp, "returncode": 0})(),
        type("R", (), {"stdout": dim_score_resp, "returncode": 0})(),
        type("R", (), {"stdout": dim_score_resp2, "returncode": 0})(),
    ]
    call_idx = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_idx
        result = responses[call_idx]
        call_idx += 1
        return result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess), \
         patch("app.services.escrow.create_challenge_onchain", return_value="0xtx"):
        # Tick 1: open -> scoring
        quality_first_lifecycle(db=db)
        # Tick 2: Phase 2 runs batch_score for gate_passed subs
        quality_first_lifecycle(db=db)

    db.refresh(task)
    db.refresh(sub)
    assert task.status in (TaskStatus.scoring, TaskStatus.challenge_window)
    assert sub.status == SubmissionStatus.scored
