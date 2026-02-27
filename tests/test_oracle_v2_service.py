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


def test_parse_criteria_deserializes_json():
    """_parse_criteria 能将 JSON 字符串反序列化为 list[str]"""
    from app.services.oracle import _parse_criteria
    assert _parse_criteria('["条目1","条目2"]') == ["条目1", "条目2"]
    assert _parse_criteria(None) == []
    assert _parse_criteria("") == []
    assert _parse_criteria("非JSON字符串") == []
    assert _parse_criteria('["only one"]') == ["only one"]


def test_generate_dimensions(db):
    from app.services.oracle import generate_dimensions

    task = Task(
        title="市场调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria=json.dumps(["至少覆盖10个产品"]),
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

# New mock for fastest_first individual scoring (high scores, all pass)
MOCK_INDIVIDUAL_FF_PASS = json.dumps({
    "dimension_scores": {
        "substantiveness": {"band": "B", "score": 80, "evidence": "good", "feedback": "好"},
        "completeness": {"band": "B", "score": 75, "evidence": "完整", "feedback": "完整"},
    },
    "overall_band": "B",
    "revision_suggestions": [
        {"problem": "p1", "suggestion": "s1", "severity": "high"},
        {"problem": "p2", "suggestion": "s2", "severity": "medium"},
    ]
})

# New mock for fastest_first individual scoring (low scores, penalty triggers)
MOCK_INDIVIDUAL_FF_LOW = json.dumps({
    "dimension_scores": {
        "substantiveness": {"band": "D", "score": 40, "evidence": "弱", "feedback": "弱"},
        "completeness": {"band": "D", "score": 35, "evidence": "不完整", "feedback": "不完整"},
    },
    "overall_band": "D",
    "revision_suggestions": [
        {"problem": "p1", "suggestion": "s1", "severity": "high"},
        {"problem": "p2", "suggestion": "s2", "severity": "medium"},
    ]
})


def test_score_submission_fastest_first_pass(db):
    """fastest_first: gate pass + score_individual → penalized_total >= 60 → close task."""
    from app.services.oracle import score_submission

    task = Task(
        title="Test", description="Desc", type=TaskType.fastest_first,
        threshold=0.6, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=0.1,
        acceptance_criteria=json.dumps(["AC"]),
    )
    db.add(task)
    db.commit()

    # Add dimensions (2 fixed)
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

    sub = Submission(task_id=task.id, worker_id="w1", content="good content")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    individual_result = type("R", (), {"stdout": MOCK_INDIVIDUAL_FF_PASS, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return gate_result if call_count == 1 else individual_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess), \
         patch("app.services.oracle.pay_winner"):
        score_submission(db, sub.id, task.id)

    db.refresh(sub)
    db.refresh(task)
    assert sub.status == SubmissionStatus.scored
    assert task.status == TaskStatus.closed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "scoring"
    assert feedback["passed"] is True
    assert "dimension_scores" in feedback
    assert "penalty" in feedback
    assert "final_score" in feedback
    assert feedback["final_score"] >= 60


def test_score_submission_fastest_first_low_score(db):
    """fastest_first: gate pass + score_individual → penalized_total < 60 → scored but NOT closed."""
    from app.services.oracle import score_submission

    task = Task(
        title="Test", description="Desc", type=TaskType.fastest_first,
        threshold=0.6, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=0.1,
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

    sub = Submission(task_id=task.id, worker_id="w1", content="bad content")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    individual_result = type("R", (), {"stdout": MOCK_INDIVIDUAL_FF_LOW, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return gate_result if call_count == 1 else individual_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        score_submission(db, sub.id, task.id)

    db.refresh(sub)
    db.refresh(task)
    assert sub.status == SubmissionStatus.scored
    assert task.status == TaskStatus.open  # NOT closed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "scoring"
    assert feedback["final_score"] < 60
    assert len(feedback["risk_flags"]) > 0


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
        acceptance_criteria=json.dumps(["至少覆盖10个产品"]),
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
        acceptance_criteria=json.dumps(["至少覆盖10个产品"]),
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

MOCK_DIM_SCORE_SUB_V2 = json.dumps({
    "dimension_id": "substantiveness",
    "dimension_name": "实质性",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 85,
         "final_score": 85, "evidence": "good"},
        {"submission": "Submission_B", "raw_score": 70,
         "final_score": 70, "evidence": "ok"},
    ]
})

MOCK_DIM_SCORE_COMP_V2 = json.dumps({
    "dimension_id": "completeness",
    "dimension_name": "完整性",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 80,
         "final_score": 80, "evidence": "good"},
        {"submission": "Submission_B", "raw_score": 60,
         "final_score": 60, "evidence": "ok"},
    ]
})


def test_batch_score_submissions_horizontal(db):
    """After deadline: threshold filter → top 3 by penalized_total → horizontal scoring → ranking."""
    from app.services.oracle import batch_score_submissions

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria=json.dumps(["至少10个产品"]),
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

    # Create 2 gate_passed submissions with individual scores (band + evidence IR format)
    sub1 = Submission(
        task_id=task.id, worker_id="w1", content="content A",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 80, "evidence": "good", "feedback": "good"},
                "completeness": {"band": "B", "score": 75, "evidence": "ok", "feedback": "ok"},
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
                "substantiveness": {"band": "C", "score": 60, "evidence": "basic", "feedback": "basic"},
                "completeness": {"band": "C", "score": 55, "evidence": "incomplete", "feedback": "incomplete"},
            },
            "revision_suggestions": []
        })
    )
    db.add_all([sub1, sub2])
    db.commit()

    # Mock: only dimension_score calls (2 dimensions = 2 calls, no constraint_check)
    modes_called = []
    responses = [
        type("R", (), {"stdout": MOCK_DIM_SCORE_SUB_V2, "returncode": 0})(),
        type("R", (), {"stdout": MOCK_DIM_SCORE_COMP_V2, "returncode": 0})(),
    ]
    call_idx = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_idx
        payload = json.loads(kwargs.get("input", args[0] if args else "{}"))
        modes_called.append(payload.get("mode", "unknown"))
        result = responses[call_idx]
        call_idx += 1
        return result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        batch_score_submissions(db, task.id)

    # Verify no constraint_check calls were made
    assert "constraint_check" not in modes_called
    assert modes_called == ["dimension_score", "dimension_score"]

    db.refresh(sub1)
    db.refresh(sub2)
    assert sub1.status == SubmissionStatus.scored
    assert sub2.status == SubmissionStatus.scored

    feedback1 = json.loads(sub1.oracle_feedback)
    feedback2 = json.loads(sub2.oracle_feedback)
    assert feedback1["type"] == "scoring"
    assert feedback1["rank"] == 1
    assert feedback2["rank"] == 2
    # New fields from penalized_total
    assert "penalty" in feedback1
    assert "weighted_base" in feedback1
    assert "risk_flags" in feedback1
    assert feedback1["final_score"] > feedback2["final_score"]


def test_batch_score_threshold_filter(db):
    """Submissions with any fixed dim band < C are filtered out and scored with individual penalty."""
    from app.services.oracle import batch_score_submissions

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria=json.dumps(["至少10个产品"]),
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

    # sub_good: both fixed dims band B (passes threshold)
    sub_good = Submission(
        task_id=task.id, worker_id="w1", content="good content",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 80, "evidence": "solid", "feedback": "solid"},
                "completeness": {"band": "B", "score": 75, "evidence": "ok", "feedback": "ok"},
            },
            "revision_suggestions": []
        })
    )
    # sub_bad: one fixed dim band D (fails threshold)
    sub_bad = Submission(
        task_id=task.id, worker_id="w2", content="bad content",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "D", "score": 40, "evidence": "weak", "feedback": "weak"},
                "completeness": {"band": "B", "score": 70, "evidence": "ok", "feedback": "ok"},
            },
            "revision_suggestions": []
        })
    )
    db.add_all([sub_good, sub_bad])
    db.commit()

    # Only dimension_score calls for the 1 eligible sub (sub_good only)
    dim_score_sub_single = json.dumps({
        "dimension_id": "substantiveness",
        "scores": [{"submission": "Submission_A", "raw_score": 85,
                     "final_score": 85, "evidence": "good"}]
    })
    dim_score_comp_single = json.dumps({
        "dimension_id": "completeness",
        "scores": [{"submission": "Submission_A", "raw_score": 80,
                     "final_score": 80, "evidence": "good"}]
    })
    responses = [
        type("R", (), {"stdout": dim_score_sub_single, "returncode": 0})(),
        type("R", (), {"stdout": dim_score_comp_single, "returncode": 0})(),
    ]
    call_idx = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_idx
        result = responses[call_idx]
        call_idx += 1
        return result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        batch_score_submissions(db, task.id)

    db.refresh(sub_good)
    db.refresh(sub_bad)

    # sub_good went through horizontal scoring
    assert sub_good.status == SubmissionStatus.scored
    feedback_good = json.loads(sub_good.oracle_feedback)
    assert feedback_good["type"] == "scoring"
    assert feedback_good["rank"] == 1

    # sub_bad was filtered out and scored with individual penalized score
    assert sub_bad.status == SubmissionStatus.scored
    assert sub_bad.score is not None
    assert sub_bad.score < sub_good.score  # penalized score should be lower


# --- Scheduler lifecycle test ---

from app.scheduler import quality_first_lifecycle


def test_lifecycle_phase1_scoring_with_gate_passed_subs(db):
    """Phase 1: deadline expired → scoring, should use gate_passed subs."""
    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2025, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        status=TaskStatus.open,
        acceptance_criteria=json.dumps(["至少10个产品"]),
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
                "substantiveness": {"band": "B", "score": 80, "evidence": "good", "feedback": "good"},
                "completeness": {"band": "B", "score": 70, "evidence": "ok", "feedback": "ok"},
            },
            "revision_suggestions": []
        })
    )
    db.add(sub)
    db.commit()

    dim_score_resp = json.dumps({
        "dimension_id": "substantiveness",
        "scores": [{"submission": "Submission_A", "raw_score": 85,
                     "final_score": 85, "evidence": "good"}]
    })
    dim_score_resp2 = json.dumps({
        "dimension_id": "completeness",
        "scores": [{"submission": "Submission_A", "raw_score": 75,
                     "final_score": 75, "evidence": "ok"}]
    })
    responses = [
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
