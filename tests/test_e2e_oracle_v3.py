"""
End-to-end tests for Oracle V3 mechanism.

Covers:
1. fastest_first: gate_check → score_individual → penalized_total → close/stay open
2. quality_first: gate_check → individual_scoring → deadline → threshold filter
   → horizontal comparison (parallel) → ranking → challenge_window → close
3. quality_first with challenge → arbitration → settlement
4. Score hiding during open/scoring phases
5. Below-threshold filter in batch_score
"""
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    Task, Submission, ScoringDimension, User, Challenge,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus, ChallengeVerdict,
    UserRole,
)
from app.services.oracle import (
    give_feedback, score_submission, batch_score_submissions,
    compute_penalized_total, PENALTY_THRESHOLD,
)
from app.scheduler import quality_first_lifecycle

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PAYMENT_MOCK = patch("app.routers.tasks.verify_payment",
                     return_value={"valid": True, "tx_hash": "0xtest"})
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    with patch("app.main.create_scheduler", return_value=MagicMock()), \
         patch("app.main.run_migrations"):
        with TestClient(app) as c:
            # Attach db session factory for direct DB manipulation
            c._test_session_factory = TestSession
            yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def _db_session(client):
    """Get a fresh DB session from the test client's factory."""
    return client._test_session_factory()


# ---------------------------------------------------------------------------
# Oracle mock responses
# ---------------------------------------------------------------------------

MOCK_DIMENSIONS = {
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "内容是否直接回应任务意图", "weight": 0.25,
         "scoring_guidance": "评估内容实质性"},
        {"id": "credibility", "name": "可信度", "type": "fixed",
         "description": "数据和论述可信度", "weight": 0.25,
         "scoring_guidance": "评估数据可信度"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "任务要求覆盖度", "weight": 0.25,
         "scoring_guidance": "评估覆盖度"},
        {"id": "tech_depth", "name": "技术深度", "type": "dynamic",
         "description": "技术分析深度", "weight": 0.25,
         "scoring_guidance": "评估技术分析深度"},
    ],
    "rationale": "基于任务需求生成维度"
}

MOCK_GATE_PASS = {
    "overall_passed": True,
    "criteria_checks": [{"criteria": "AC1", "passed": True, "evidence": "符合"}],
    "summary": "全部通过"
}

MOCK_GATE_FAIL = {
    "overall_passed": False,
    "criteria_checks": [{"criteria": "AC1", "passed": False,
                         "evidence": "不符合", "revision_hint": "请修改"}],
    "summary": "未通过验收"
}

MOCK_INDIVIDUAL_HIGH = {
    "dimension_scores": {
        "substantiveness": {"band": "A", "score": 90, "evidence": "内容充实", "feedback": "优秀"},
        "credibility": {"band": "B", "score": 80, "evidence": "数据可靠", "feedback": "可信"},
        "completeness": {"band": "B", "score": 78, "evidence": "覆盖全面", "feedback": "全面"},
        "tech_depth": {"band": "A", "score": 88, "evidence": "深度好", "feedback": "深入"},
    },
    "overall_band": "A",
    "revision_suggestions": [
        {"problem": "细节不足", "suggestion": "补充更多细节", "severity": "medium"},
        {"problem": "引用缺失", "suggestion": "添加引用来源", "severity": "low"},
    ]
}

MOCK_INDIVIDUAL_MEDIUM = {
    "dimension_scores": {
        "substantiveness": {"band": "C", "score": 62, "evidence": "基本回应", "feedback": "及格"},
        "credibility": {"band": "C", "score": 58, "evidence": "一般可信", "feedback": "一般"},
        "completeness": {"band": "C", "score": 60, "evidence": "基本覆盖", "feedback": "基本"},
        "tech_depth": {"band": "C", "score": 55, "evidence": "浅层分析", "feedback": "浅"},
    },
    "overall_band": "C",
    "revision_suggestions": [
        {"problem": "分析不深", "suggestion": "深入分析", "severity": "high"},
        {"problem": "结论模糊", "suggestion": "明确结论", "severity": "medium"},
    ]
}

MOCK_INDIVIDUAL_LOW = {
    "dimension_scores": {
        "substantiveness": {"band": "D", "score": 40, "evidence": "内容空洞", "feedback": "差"},
        "credibility": {"band": "D", "score": 35, "evidence": "数据存疑", "feedback": "差"},
        "completeness": {"band": "C", "score": 55, "evidence": "部分覆盖", "feedback": "不全"},
        "tech_depth": {"band": "D", "score": 30, "evidence": "无深度", "feedback": "差"},
    },
    "overall_band": "D",
    "revision_suggestions": [
        {"problem": "内容缺失", "suggestion": "重写", "severity": "high"},
        {"problem": "数据错误", "suggestion": "核实数据", "severity": "high"},
    ]
}

MOCK_INDIVIDUAL_BELOW_THRESHOLD = {
    "dimension_scores": {
        "substantiveness": {"band": "D", "score": 45, "evidence": "weak", "feedback": "弱"},
        "credibility": {"band": "B", "score": 75, "evidence": "ok", "feedback": "可以"},
        "completeness": {"band": "C", "score": 60, "evidence": "basic", "feedback": "基本"},
        "tech_depth": {"band": "C", "score": 55, "evidence": "shallow", "feedback": "浅"},
    },
    "overall_band": "C",
    "revision_suggestions": []
}


def _make_dim_score_response(dim_id, dim_name, scores_list):
    """Build a dimension_score oracle response."""
    return {
        "dimension_id": dim_id,
        "dimension_name": dim_name,
        "evaluation_focus": "横向对比",
        "comparative_analysis": "分析",
        "scores": scores_list,
    }


# Horizontal scoring mocks for 3 submissions
MOCK_DIM_SCORES = {
    "substantiveness": _make_dim_score_response("substantiveness", "实质性", [
        {"submission": "Submission_A", "raw_score": 88, "final_score": 88, "evidence": "excellent"},
        {"submission": "Submission_B", "raw_score": 72, "final_score": 72, "evidence": "good"},
        {"submission": "Submission_C", "raw_score": 60, "final_score": 60, "evidence": "basic"},
    ]),
    "credibility": _make_dim_score_response("credibility", "可信度", [
        {"submission": "Submission_A", "raw_score": 85, "final_score": 85, "evidence": "trustworthy"},
        {"submission": "Submission_B", "raw_score": 70, "final_score": 70, "evidence": "decent"},
        {"submission": "Submission_C", "raw_score": 65, "final_score": 65, "evidence": "acceptable"},
    ]),
    "completeness": _make_dim_score_response("completeness", "完整性", [
        {"submission": "Submission_A", "raw_score": 82, "final_score": 82, "evidence": "thorough"},
        {"submission": "Submission_B", "raw_score": 68, "final_score": 68, "evidence": "partial"},
        {"submission": "Submission_C", "raw_score": 58, "final_score": 58, "evidence": "incomplete"},
    ]),
    "tech_depth": _make_dim_score_response("tech_depth", "技术深度", [
        {"submission": "Submission_A", "raw_score": 90, "final_score": 90, "evidence": "deep"},
        {"submission": "Submission_B", "raw_score": 75, "final_score": 75, "evidence": "moderate"},
        {"submission": "Submission_C", "raw_score": 55, "final_score": 55, "evidence": "shallow"},
    ]),
}


def _oracle_subprocess_factory(call_sequence):
    """Create a mock subprocess.run that returns responses in order.
    call_sequence: list of (mode_filter, response_dict) or just response_dict.
    """
    idx = {"n": 0}
    def mock_run(*args, **kwargs):
        i = idx["n"]
        idx["n"] += 1
        if i < len(call_sequence):
            resp = call_sequence[i]
        else:
            # Fallback: return last response
            resp = call_sequence[-1]
        return type("R", (), {"stdout": json.dumps(resp), "returncode": 0})()
    return mock_run


def _oracle_subprocess_by_mode(mode_map):
    """Create a mock subprocess.run that dispatches by 'mode' field in input payload."""
    def mock_run(*args, **kwargs):
        raw_input = kwargs.get("input", "")
        payload = json.loads(raw_input)
        mode = payload.get("mode", "unknown")
        if mode == "dimension_score":
            dim_id = payload.get("dimension", {}).get("id", "")
            resp = mode_map.get(f"dimension_score:{dim_id}", mode_map.get(mode, {}))
        else:
            resp = mode_map.get(mode, {})
        return type("R", (), {"stdout": json.dumps(resp), "returncode": 0})()
    return mock_run


def _create_test_dims(db, task_id):
    """Insert standard 4-dimension set into DB."""
    for dim_data in MOCK_DIMENSIONS["dimensions"]:
        db.add(ScoringDimension(
            task_id=task_id,
            dim_id=dim_data["id"],
            name=dim_data["name"],
            dim_type=dim_data["type"],
            description=dim_data["description"],
            weight=dim_data["weight"],
            scoring_guidance=dim_data["scoring_guidance"],
        ))
    db.commit()


# ===========================================================================
# Test 1: fastest_first — gate pass + high scores → close task
# ===========================================================================

class TestFastestFirstE2E:

    def test_gate_pass_high_score_closes_task(self, db):
        """Gate pass → score_individual (all high) → penalized_total >= 60 → task closed."""
        task = Task(
            title="写测试", description="编写单元测试",
            type=TaskType.fastest_first, threshold=0.6,
            deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
            bounty=0.1, acceptance_criteria=json.dumps(["覆盖率达到80%"]),
        )
        db.add(task)
        db.commit()
        _create_test_dims(db, task.id)

        sub = Submission(task_id=task.id, worker_id="w1", content="完整的测试代码")
        db.add(sub)
        db.commit()

        mock = _oracle_subprocess_factory([MOCK_GATE_PASS, MOCK_INDIVIDUAL_HIGH])
        with patch("app.services.oracle.subprocess.run", side_effect=mock), \
             patch("app.services.oracle.pay_winner"):
            score_submission(db, sub.id, task.id)

        db.refresh(sub)
        db.refresh(task)

        assert sub.status == SubmissionStatus.scored
        assert task.status == TaskStatus.closed
        assert task.winner_submission_id == sub.id

        feedback = json.loads(sub.oracle_feedback)
        assert feedback["type"] == "scoring"
        assert feedback["passed"] is True
        assert feedback["final_score"] >= PENALTY_THRESHOLD
        assert feedback["penalty"] == 1.0  # No penalty for all high scores
        assert len(feedback["risk_flags"]) == 0

    def test_gate_pass_low_score_stays_open(self, db):
        """Gate pass → score_individual (low fixed dims) → penalized_total < 60 → stays open."""
        task = Task(
            title="写文档", description="编写API文档",
            type=TaskType.fastest_first, threshold=0.6,
            deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
            bounty=0.1, acceptance_criteria=json.dumps(["覆盖所有接口"]),
        )
        db.add(task)
        db.commit()
        _create_test_dims(db, task.id)

        sub = Submission(task_id=task.id, worker_id="w1", content="简陋的文档")
        db.add(sub)
        db.commit()

        mock = _oracle_subprocess_factory([MOCK_GATE_PASS, MOCK_INDIVIDUAL_LOW])
        with patch("app.services.oracle.subprocess.run", side_effect=mock):
            score_submission(db, sub.id, task.id)

        db.refresh(sub)
        db.refresh(task)

        assert sub.status == SubmissionStatus.scored
        assert task.status == TaskStatus.open  # NOT closed

        feedback = json.loads(sub.oracle_feedback)
        assert feedback["passed"] is False
        assert feedback["final_score"] < PENALTY_THRESHOLD
        assert feedback["penalty"] < 1.0
        assert len(feedback["penalty_reasons"]) > 0
        assert len(feedback["risk_flags"]) > 0

    def test_gate_fail_scores_zero(self, db):
        """Gate fail → score=0, task stays open."""
        task = Task(
            title="分析", description="竞品分析",
            type=TaskType.fastest_first, threshold=0.6,
            deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
            bounty=0.1, acceptance_criteria=json.dumps(["至少5个竞品"]),
        )
        db.add(task)
        db.commit()

        sub = Submission(task_id=task.id, worker_id="w1", content="不相关内容")
        db.add(sub)
        db.commit()

        mock = _oracle_subprocess_factory([MOCK_GATE_FAIL])
        with patch("app.services.oracle.subprocess.run", side_effect=mock):
            score_submission(db, sub.id, task.id)

        db.refresh(sub)
        db.refresh(task)

        assert sub.status == SubmissionStatus.scored
        assert sub.score == 0.0
        assert task.status == TaskStatus.open

        feedback = json.loads(sub.oracle_feedback)
        assert feedback["passed"] is False
        assert "gate_check" in feedback

    def test_penalized_total_compound_penalty(self, db):
        """Two low fixed dims → compound penalty (multiplicative)."""
        dim_scores = {
            "substantiveness": {"score": 40},  # 40/60 = 0.667
            "credibility": {"score": 30},       # 30/60 = 0.500
            "completeness": {"score": 70},      # OK
            "tech_depth": {"score": 60},         # Dynamic, no penalty
        }
        dims = [
            {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.25},
            {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.25},
            {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.25},
            {"dim_id": "tech_depth", "dim_type": "dynamic", "weight": 0.25},
        ]
        result = compute_penalized_total(dim_scores, dims)

        # weighted_base = 40*0.25 + 30*0.25 + 70*0.25 + 60*0.25 = 50.0
        assert result["weighted_base"] == 50.0
        # penalty = (40/60) * (30/60) = 0.6667 * 0.5 = 0.3333
        assert result["penalty"] < 0.4
        # final = 50.0 * 0.3333 ≈ 16.67
        assert result["final_score"] < 20
        assert len(result["penalty_reasons"]) == 2
        assert "实质性" in result["penalty_reasons"][0]
        assert "可信度" in result["penalty_reasons"][1]


# ===========================================================================
# Test 2: quality_first — full lifecycle (no challenges)
# ===========================================================================

class TestQualityFirstE2E:

    def _setup_quality_task(self, db, deadline=None):
        """Create a quality_first task with dimensions."""
        if deadline is None:
            deadline = datetime(2025, 1, 1, tzinfo=timezone.utc)  # Already expired
        task = Task(
            title="市场调研", description="调研10个竞品",
            type=TaskType.quality_first,
            deadline=deadline, bounty=10.0,
            acceptance_criteria=json.dumps(["至少覆盖10个产品"]),
            challenge_duration=7200,
        )
        db.add(task)
        db.commit()
        _create_test_dims(db, task.id)
        return task

    def _add_gate_passed_sub(self, db, task_id, worker_id, individual_mock):
        """Create a gate_passed submission with individual scoring feedback."""
        user = User(nickname=worker_id, wallet=f"0x{worker_id}", role=UserRole.worker)
        db.add(user)
        db.flush()
        sub = Submission(
            task_id=task_id, worker_id=user.id,
            content=f"调研内容 by {worker_id}",
            status=SubmissionStatus.gate_passed,
            oracle_feedback=json.dumps({
                "type": "individual_scoring",
                **individual_mock,
            }),
        )
        db.add(sub)
        db.commit()
        return sub

    def test_gate_check_and_individual_scoring(self, db):
        """quality_first: gate pass → individual scoring stored, status=gate_passed."""
        task = self._setup_quality_task(db, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc))
        sub = Submission(task_id=task.id, worker_id="w1", content="调研12个产品")
        db.add(sub)
        db.commit()

        mock = _oracle_subprocess_factory([MOCK_GATE_PASS, MOCK_INDIVIDUAL_HIGH])
        with patch("app.services.oracle.subprocess.run", side_effect=mock):
            give_feedback(db, sub.id, task.id)

        db.refresh(sub)
        assert sub.status == SubmissionStatus.gate_passed
        feedback = json.loads(sub.oracle_feedback)
        assert feedback["type"] == "individual_scoring"
        assert "dimension_scores" in feedback
        assert "substantiveness" in feedback["dimension_scores"]
        # Score should NOT be set yet (hidden until challenge_window)
        assert sub.score is None

    def test_gate_fail_stops_pipeline(self, db):
        """quality_first: gate fail → gate_failed, no individual scoring."""
        task = self._setup_quality_task(db, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc))
        sub = Submission(task_id=task.id, worker_id="w1", content="不相关的内容")
        db.add(sub)
        db.commit()

        mock = _oracle_subprocess_factory([MOCK_GATE_FAIL])
        with patch("app.services.oracle.subprocess.run", side_effect=mock):
            give_feedback(db, sub.id, task.id)

        db.refresh(sub)
        assert sub.status == SubmissionStatus.gate_failed
        feedback = json.loads(sub.oracle_feedback)
        assert feedback["type"] == "gate_check"
        assert feedback["overall_passed"] is False

    def test_batch_score_threshold_filter_and_horizontal(self, db):
        """batch_score: below-threshold subs filtered out, eligible get horizontal scoring."""
        task = self._setup_quality_task(db)

        # Worker 1: high scores (passes threshold)
        sub_high = self._add_gate_passed_sub(db, task.id, "w1", MOCK_INDIVIDUAL_HIGH)
        # Worker 2: medium scores (passes threshold — all bands >= C)
        sub_med = self._add_gate_passed_sub(db, task.id, "w2", MOCK_INDIVIDUAL_MEDIUM)
        # Worker 3: has D band on fixed dim (filtered below threshold)
        sub_low = self._add_gate_passed_sub(db, task.id, "w3", MOCK_INDIVIDUAL_BELOW_THRESHOLD)

        # Mock dimension_score calls (only for eligible subs: sub_high, sub_med)
        dim_scores_2subs = {}
        for dim_id, dim_name in [("substantiveness", "实质性"), ("credibility", "可信度"),
                                  ("completeness", "完整性"), ("tech_depth", "技术深度")]:
            dim_scores_2subs[dim_id] = _make_dim_score_response(dim_id, dim_name, [
                {"submission": "Submission_A", "raw_score": 85, "final_score": 85, "evidence": "good"},
                {"submission": "Submission_B", "raw_score": 65, "final_score": 65, "evidence": "basic"},
            ])

        modes_called = []
        def mock_run(*args, **kwargs):
            payload = json.loads(kwargs.get("input", ""))
            mode = payload.get("mode", "unknown")
            modes_called.append(mode)
            dim_id = payload.get("dimension", {}).get("id", "")
            resp = dim_scores_2subs.get(dim_id, {})
            return type("R", (), {"stdout": json.dumps(resp), "returncode": 0})()

        with patch("app.services.oracle.subprocess.run", side_effect=mock_run):
            batch_score_submissions(db, task.id)

        # No constraint_check calls
        assert "constraint_check" not in modes_called
        # Only dimension_score calls (4 dimensions)
        assert all(m == "dimension_score" for m in modes_called)
        assert len(modes_called) == 4

        db.refresh(sub_high)
        db.refresh(sub_med)
        db.refresh(sub_low)

        # All scored
        assert sub_high.status == SubmissionStatus.scored
        assert sub_med.status == SubmissionStatus.scored
        assert sub_low.status == SubmissionStatus.scored

        # sub_high should rank #1
        fb_high = json.loads(sub_high.oracle_feedback)
        assert fb_high["type"] == "scoring"
        assert fb_high["rank"] == 1

        # sub_med should rank #2
        fb_med = json.loads(sub_med.oracle_feedback)
        assert fb_med["rank"] == 2

        # sub_low was below threshold — scored with penalized individual score
        assert sub_low.score is not None
        assert sub_low.score < sub_med.score  # Should be lower due to penalty

        # sub_high has highest score
        assert sub_high.score > sub_med.score

    def test_full_lifecycle_no_challenge(self, db):
        """Full quality_first lifecycle: open → scoring → challenge_window → closed."""
        task = self._setup_quality_task(db)  # deadline already expired

        # Add 2 gate_passed subs
        sub1 = self._add_gate_passed_sub(db, task.id, "w1", MOCK_INDIVIDUAL_HIGH)
        sub2 = self._add_gate_passed_sub(db, task.id, "w2", MOCK_INDIVIDUAL_MEDIUM)

        # Build mode-based mock for batch_score dimension_score calls
        dim_score_mock = {}
        for dim_id, dim_name in [("substantiveness", "实质性"), ("credibility", "可信度"),
                                  ("completeness", "完整性"), ("tech_depth", "技术深度")]:
            dim_score_mock[dim_id] = _make_dim_score_response(dim_id, dim_name, [
                {"submission": "Submission_A", "raw_score": 88, "final_score": 88, "evidence": "A wins"},
                {"submission": "Submission_B", "raw_score": 65, "final_score": 65, "evidence": "B ok"},
            ])

        def mock_run(*args, **kwargs):
            payload = json.loads(kwargs.get("input", ""))
            dim_id = payload.get("dimension", {}).get("id", "")
            resp = dim_score_mock.get(dim_id, {})
            return type("R", (), {"stdout": json.dumps(resp), "returncode": 0})()

        # Phase 1: open → scoring (deadline expired)
        with patch("app.services.oracle.subprocess.run", side_effect=mock_run), \
             patch("app.scheduler.create_challenge_onchain", return_value="0xescrow"):
            quality_first_lifecycle(db=db)
            db.refresh(task)
            assert task.status == TaskStatus.scoring

            # Phase 2: scoring → challenge_window (batch_score runs)
            quality_first_lifecycle(db=db)

        db.refresh(task)
        db.refresh(sub1)
        db.refresh(sub2)

        assert task.status == TaskStatus.challenge_window
        assert task.winner_submission_id == sub1.id  # Higher scorer wins
        assert task.escrow_tx_hash == "0xescrow"
        assert sub1.status == SubmissionStatus.scored
        assert sub2.status == SubmissionStatus.scored

        # Phase 3: challenge_window → closed (no challenges, expire window)
        task.challenge_window_end = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()

        with patch("app.services.escrow.resolve_challenge_onchain", return_value="0xresolve"):
            quality_first_lifecycle(db=db)

        db.refresh(task)
        assert task.status == TaskStatus.closed

    def test_score_hiding_during_open_and_scoring(self, client):
        """Scores are hidden (null) in API responses during open/scoring phases."""
        s = _db_session(client)

        # Create publisher
        pub = User(nickname="pub1", wallet="0xpub", role=UserRole.publisher)
        s.add(pub)
        s.commit()

        task = Task(
            title="调研", description="竞品调研",
            type=TaskType.quality_first,
            deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
            bounty=0.1, acceptance_criteria=json.dumps(["10个产品"]),
            publisher_id=pub.id,
        )
        s.add(task)
        s.commit()
        _create_test_dims(s, task.id)

        # Add submission with individual scoring (simulating post-gate_check)
        sub = Submission(
            task_id=task.id, worker_id="w1", content="调研内容",
            status=SubmissionStatus.gate_passed,
            score=0.75,  # This should be hidden
            oracle_feedback=json.dumps({"type": "individual_scoring", "dimension_scores": {}}),
        )
        s.add(sub)
        s.commit()

        sub_id = sub.id
        task_id = task.id
        s.close()

        # GET submissions while task is open → score should be null
        resp = client.get(f"/tasks/{task_id}/submissions")
        assert resp.status_code == 200
        subs = resp.json()
        assert len(subs) == 1
        assert subs[0]["score"] is None  # Hidden!

        # GET single submission → also hidden
        resp = client.get(f"/tasks/{task_id}/submissions/{sub_id}")
        assert resp.status_code == 200
        assert resp.json()["score"] is None


# ===========================================================================
# Test 3: quality_first with challenge → arbitration → settlement
# ===========================================================================

class TestQualityFirstChallengeE2E:

    def test_challenge_upheld_changes_winner(self, db):
        """Challenge upheld → winner changes to challenger's submission."""
        # Setup task in challenge_window with winner
        task = Task(
            title="调研", description="竞品调研",
            type=TaskType.quality_first,
            deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bounty=10.0, status=TaskStatus.challenge_window,
            challenge_window_end=datetime(2020, 1, 1, tzinfo=timezone.utc),
            acceptance_criteria=json.dumps(["AC"]),
        )
        db.add(task)
        db.commit()

        winner_user = User(nickname="winner", wallet="0xwinner", role=UserRole.worker)
        challenger_user = User(nickname="challenger", wallet="0xchallenger", role=UserRole.worker)
        pub_user = User(nickname="pub", wallet="0xpub", role=UserRole.publisher)
        db.add_all([winner_user, challenger_user, pub_user])
        db.commit()
        task.publisher_id = pub_user.id
        db.commit()

        sub_winner = Submission(
            task_id=task.id, worker_id=winner_user.id,
            content="winner content", status=SubmissionStatus.scored,
            score=0.85,
        )
        sub_challenger = Submission(
            task_id=task.id, worker_id=challenger_user.id,
            content="challenger content", status=SubmissionStatus.scored,
            score=0.80,
        )
        db.add_all([sub_winner, sub_challenger])
        db.commit()

        task.winner_submission_id = sub_winner.id
        db.commit()

        # Create challenge
        challenge = Challenge(
            task_id=task.id,
            challenger_submission_id=sub_challenger.id,
            target_submission_id=sub_winner.id,
            reason="我的更好",
            challenger_wallet="0xchallenger",
        )
        db.add(challenge)
        db.commit()

        # Mock arbitration: upheld verdict
        def mock_arbiter(db_session, task_id):
            c = db_session.query(Challenge).filter(Challenge.task_id == task_id).first()
            c.verdict = ChallengeVerdict.upheld
            c.arbiter_score = 0.9
            c.status = ChallengeStatus.judged
            db_session.commit()

        with patch("app.scheduler.run_arbitration", side_effect=mock_arbiter), \
             patch("app.scheduler.select_jury", return_value=[]), \
             patch("app.services.escrow.resolve_challenge_onchain", return_value="0xresolve"):
            quality_first_lifecycle(db=db)

        db.refresh(task)
        assert task.status == TaskStatus.arbitrating

        # Another tick to settle
        with patch("app.services.escrow.resolve_challenge_onchain", return_value="0xresolve"):
            quality_first_lifecycle(db=db)

        db.refresh(task)
        assert task.status == TaskStatus.closed
        # Winner changed to challenger
        assert task.winner_submission_id == sub_challenger.id

    def test_no_challenge_releases_bounty(self, db):
        """No challenges → challenge_window expires → closed, bounty released."""
        pub_user = User(nickname="pub2", wallet="0xpub2", role=UserRole.publisher)
        winner_user = User(nickname="winner2", wallet="0xwinner2", role=UserRole.worker)
        db.add_all([pub_user, winner_user])
        db.commit()

        task = Task(
            title="调研", description="竞品调研",
            type=TaskType.quality_first,
            deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bounty=10.0, status=TaskStatus.challenge_window,
            challenge_window_end=datetime(2020, 1, 1, tzinfo=timezone.utc),
            acceptance_criteria=json.dumps(["AC"]),
            publisher_id=pub_user.id,
        )
        db.add(task)
        db.commit()

        sub = Submission(
            task_id=task.id, worker_id=winner_user.id,
            content="winner content", status=SubmissionStatus.scored, score=0.85,
        )
        db.add(sub)
        db.commit()

        task.winner_submission_id = sub.id
        db.commit()

        with patch("app.scheduler.resolve_challenge_onchain", return_value="0xrelease") as mock_resolve:
            quality_first_lifecycle(db=db)

        db.refresh(task)
        assert task.status == TaskStatus.closed
        # resolve_challenge_onchain called with empty refunds (no challengers)
        mock_resolve.assert_called_once()
        call_args = mock_resolve.call_args
        assert call_args[0][3] == []  # refunds=[]
        assert call_args[0][4] == []  # arbiter_wallets=[]
        assert call_args[0][5] == 0   # arbiter_reward=0


# ===========================================================================
# Test 4: HTTP-level E2E (client fixture)
# ===========================================================================

class TestHTTPE2E:

    def test_fastest_first_full_http_flow(self, client):
        """HTTP-level: create task → submit → oracle scores → verify response."""
        s = _db_session(client)

        # Register publisher
        resp = client.post("/users", json={
            "nickname": "pub_http", "wallet": "0xpub_http", "role": "publisher"
        })
        assert resp.status_code == 201
        pub_id = resp.json()["id"]

        # Create fastest_first task
        dim_mock = _oracle_subprocess_factory([MOCK_DIMENSIONS])
        with patch("app.services.oracle.subprocess.run", side_effect=dim_mock), \
             PAYMENT_MOCK:
            resp = client.post("/tasks", json={
                "title": "写测试", "description": "编写单元测试",
                "type": "fastest_first", "threshold": 0.6,
                "deadline": "2026-12-31T00:00:00Z",
                "publisher_id": pub_id, "bounty": 0.1,
                "acceptance_criteria": ["覆盖率达到80%"],
            }, headers=PAYMENT_HEADERS)
        assert resp.status_code == 201
        task_data = resp.json()
        task_id = task_data["id"]
        assert len(task_data.get("scoring_dimensions", [])) == 4

        # Register worker
        resp = client.post("/users", json={
            "nickname": "worker_http", "wallet": "0xworker", "role": "worker"
        })
        assert resp.status_code == 201
        worker_id = resp.json()["id"]

        # Submit — oracle runs in background, mock it
        oracle_mock = _oracle_subprocess_factory([MOCK_GATE_PASS, MOCK_INDIVIDUAL_HIGH])
        with patch("app.services.oracle.subprocess.run", side_effect=oracle_mock), \
             patch("app.services.oracle.pay_winner"):
            resp = client.post(f"/tasks/{task_id}/submissions", json={
                "worker_id": worker_id, "content": "完整的测试代码覆盖率85%",
            })
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

        # Verify task closed
        resp = client.get(f"/tasks/{task_id}")
        assert resp.status_code == 200
        task_detail = resp.json()
        assert task_detail["status"] == "closed"
        assert task_detail["winner_submission_id"] == sub_id

        s.close()

    def test_quality_first_http_flow_with_score_hiding(self, client):
        """HTTP-level: create quality_first task → submit → verify score hidden → lifecycle."""
        s = _db_session(client)

        # Register users
        resp = client.post("/users", json={
            "nickname": "pub_qf", "wallet": "0xpub_qf", "role": "publisher"
        })
        pub_id = resp.json()["id"]

        resp = client.post("/users", json={
            "nickname": "worker_qf1", "wallet": "0xw1", "role": "worker"
        })
        w1_id = resp.json()["id"]

        # Create quality_first task
        dim_mock = _oracle_subprocess_factory([MOCK_DIMENSIONS])
        with patch("app.services.oracle.subprocess.run", side_effect=dim_mock), \
             PAYMENT_MOCK:
            resp = client.post("/tasks", json={
                "title": "竞品调研", "description": "调研10个竞品产品",
                "type": "quality_first",
                "deadline": "2026-12-31T00:00:00Z",
                "publisher_id": pub_id, "bounty": 0.1,
                "acceptance_criteria": ["至少覆盖10个产品"],
                "challenge_duration": 7200,
            }, headers=PAYMENT_HEADERS)
        assert resp.status_code == 201
        task_id = resp.json()["id"]

        # Submit — oracle gives gate_check + individual_scoring
        oracle_mock = _oracle_subprocess_factory([MOCK_GATE_PASS, MOCK_INDIVIDUAL_HIGH])
        with patch("app.services.oracle.subprocess.run", side_effect=oracle_mock):
            resp = client.post(f"/tasks/{task_id}/submissions", json={
                "worker_id": w1_id, "content": "完整的竞品调研报告",
            })
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

        # Verify score hidden while task is open
        resp = client.get(f"/tasks/{task_id}/submissions")
        subs_data = resp.json()
        assert len(subs_data) == 1
        assert subs_data[0]["score"] is None  # Hidden!

        s.close()


# ===========================================================================
# Test 5: Parallel dimension_score in batch_score
# ===========================================================================

class TestParallelDimensionScore:

    def test_dimension_score_calls_are_parallel(self, db):
        """batch_score uses ThreadPoolExecutor for dimension_score calls."""
        import threading

        task = Task(
            title="调研", description="调研竞品",
            type=TaskType.quality_first,
            deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bounty=10.0, acceptance_criteria=json.dumps(["AC"]),
        )
        db.add(task)
        db.commit()
        _create_test_dims(db, task.id)

        sub = Submission(
            task_id=task.id, worker_id="w1", content="content",
            status=SubmissionStatus.gate_passed,
            oracle_feedback=json.dumps({
                "type": "individual_scoring",
                "dimension_scores": {
                    "substantiveness": {"band": "B", "score": 80, "evidence": "good", "feedback": "ok"},
                    "credibility": {"band": "B", "score": 75, "evidence": "ok", "feedback": "ok"},
                    "completeness": {"band": "B", "score": 70, "evidence": "ok", "feedback": "ok"},
                    "tech_depth": {"band": "B", "score": 72, "evidence": "ok", "feedback": "ok"},
                },
                "revision_suggestions": []
            }),
        )
        db.add(sub)
        db.commit()

        thread_ids = []
        def mock_run(*args, **kwargs):
            thread_ids.append(threading.current_thread().ident)
            payload = json.loads(kwargs.get("input", ""))
            dim_id = payload.get("dimension", {}).get("id", "unknown")
            resp = _make_dim_score_response(dim_id, "test", [
                {"submission": "Submission_A", "raw_score": 80, "final_score": 80, "evidence": "ok"},
            ])
            return type("R", (), {"stdout": json.dumps(resp), "returncode": 0})()

        with patch("app.services.oracle.subprocess.run", side_effect=mock_run):
            batch_score_submissions(db, task.id)

        # 4 dimensions = 4 calls
        assert len(thread_ids) == 4
        # At least some calls should be on different threads (parallel)
        unique_threads = set(thread_ids)
        assert len(unique_threads) >= 2, f"Expected parallel execution, got threads: {unique_threads}"


# ===========================================================================
# Test 6: Individual IR reference passed to dimension_score
# ===========================================================================

class TestIndividualIRReference:

    def test_dimension_score_receives_individual_ir(self, db):
        """dimension_score receives individual_ir with band + evidence per submission."""
        task = Task(
            title="调研", description="调研竞品",
            type=TaskType.quality_first,
            deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bounty=10.0, acceptance_criteria=json.dumps(["AC"]),
        )
        db.add(task)
        db.commit()
        _create_test_dims(db, task.id)

        sub1 = Submission(
            task_id=task.id, worker_id="w1", content="A content",
            status=SubmissionStatus.gate_passed,
            oracle_feedback=json.dumps({
                "type": "individual_scoring",
                "dimension_scores": {
                    "substantiveness": {"band": "A", "score": 90, "evidence": "excellent", "feedback": "ok"},
                    "credibility": {"band": "B", "score": 80, "evidence": "good", "feedback": "ok"},
                    "completeness": {"band": "A", "score": 88, "evidence": "thorough", "feedback": "ok"},
                    "tech_depth": {"band": "A", "score": 92, "evidence": "deep", "feedback": "ok"},
                },
                "revision_suggestions": []
            }),
        )
        sub2 = Submission(
            task_id=task.id, worker_id="w2", content="B content",
            status=SubmissionStatus.gate_passed,
            oracle_feedback=json.dumps({
                "type": "individual_scoring",
                "dimension_scores": {
                    "substantiveness": {"band": "C", "score": 62, "evidence": "basic", "feedback": "ok"},
                    "credibility": {"band": "C", "score": 60, "evidence": "fair", "feedback": "ok"},
                    "completeness": {"band": "C", "score": 58, "evidence": "partial", "feedback": "ok"},
                    "tech_depth": {"band": "C", "score": 55, "evidence": "shallow", "feedback": "ok"},
                },
                "revision_suggestions": []
            }),
        )
        db.add_all([sub1, sub2])
        db.commit()

        captured_payloads = []
        def mock_run(*args, **kwargs):
            payload = json.loads(kwargs.get("input", ""))
            captured_payloads.append(payload)
            dim_id = payload.get("dimension", {}).get("id", "unknown")
            resp = _make_dim_score_response(dim_id, "test", [
                {"submission": "Submission_A", "raw_score": 85, "final_score": 85, "evidence": "ok"},
                {"submission": "Submission_B", "raw_score": 65, "final_score": 65, "evidence": "ok"},
            ])
            return type("R", (), {"stdout": json.dumps(resp), "returncode": 0})()

        with patch("app.services.oracle.subprocess.run", side_effect=mock_run):
            batch_score_submissions(db, task.id)

        # All 4 dimension_score calls should have individual_ir
        assert len(captured_payloads) == 4
        for payload in captured_payloads:
            assert payload["mode"] == "dimension_score"
            ir = payload.get("individual_ir", {})
            assert "Submission_A" in ir
            assert "Submission_B" in ir
            # Each submission should have band + evidence
            for label in ["Submission_A", "Submission_B"]:
                dim_ir = ir[label]
                assert "band" in dim_ir
                assert "evidence" in dim_ir


# ===========================================================================
# Test 7: Edge cases
# ===========================================================================

class TestEdgeCases:

    def test_batch_score_all_below_threshold(self, db):
        """All submissions below threshold → all scored individually, no horizontal scoring."""
        task = Task(
            title="调研", description="调研竞品",
            type=TaskType.quality_first,
            deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bounty=10.0, acceptance_criteria=json.dumps(["AC"]),
        )
        db.add(task)
        db.commit()
        _create_test_dims(db, task.id)

        # All subs have D band on fixed dims
        sub1 = Submission(
            task_id=task.id, worker_id="w1", content="bad1",
            status=SubmissionStatus.gate_passed,
            oracle_feedback=json.dumps({
                "type": "individual_scoring",
                "dimension_scores": {
                    "substantiveness": {"band": "D", "score": 40, "evidence": "weak", "feedback": "差"},
                    "credibility": {"band": "C", "score": 60, "evidence": "ok", "feedback": "ok"},
                    "completeness": {"band": "C", "score": 55, "evidence": "basic", "feedback": "基本"},
                    "tech_depth": {"band": "D", "score": 35, "evidence": "none", "feedback": "差"},
                },
                "revision_suggestions": []
            }),
        )
        sub2 = Submission(
            task_id=task.id, worker_id="w2", content="bad2",
            status=SubmissionStatus.gate_passed,
            oracle_feedback=json.dumps({
                "type": "individual_scoring",
                "dimension_scores": {
                    "substantiveness": {"band": "E", "score": 20, "evidence": "terrible", "feedback": "极差"},
                    "credibility": {"band": "D", "score": 40, "evidence": "bad", "feedback": "差"},
                    "completeness": {"band": "D", "score": 38, "evidence": "missing", "feedback": "缺"},
                    "tech_depth": {"band": "E", "score": 15, "evidence": "none", "feedback": "极差"},
                },
                "revision_suggestions": []
            }),
        )
        db.add_all([sub1, sub2])
        db.commit()

        oracle_calls = []
        def mock_run(*args, **kwargs):
            oracle_calls.append(1)
            return type("R", (), {"stdout": "{}", "returncode": 0})()

        with patch("app.services.oracle.subprocess.run", side_effect=mock_run):
            batch_score_submissions(db, task.id)

        # No oracle calls (no horizontal scoring needed)
        assert len(oracle_calls) == 0

        db.refresh(sub1)
        db.refresh(sub2)
        assert sub1.status == SubmissionStatus.scored
        assert sub2.status == SubmissionStatus.scored
        assert sub1.score is not None
        assert sub2.score is not None
        # sub1 should score higher than sub2 (less severe penalties)
        assert sub1.score > sub2.score

    def test_single_eligible_still_gets_horizontal(self, db):
        """Even 1 eligible submission goes through horizontal scoring."""
        task = Task(
            title="调研", description="调研竞品",
            type=TaskType.quality_first,
            deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bounty=10.0, acceptance_criteria=json.dumps(["AC"]),
        )
        db.add(task)
        db.commit()
        _create_test_dims(db, task.id)

        sub = Submission(
            task_id=task.id, worker_id="w1", content="good content",
            status=SubmissionStatus.gate_passed,
            oracle_feedback=json.dumps({
                "type": "individual_scoring",
                "dimension_scores": {
                    "substantiveness": {"band": "A", "score": 90, "evidence": "great", "feedback": "好"},
                    "credibility": {"band": "A", "score": 88, "evidence": "solid", "feedback": "好"},
                    "completeness": {"band": "B", "score": 78, "evidence": "ok", "feedback": "好"},
                    "tech_depth": {"band": "A", "score": 85, "evidence": "deep", "feedback": "好"},
                },
                "revision_suggestions": []
            }),
        )
        db.add(sub)
        db.commit()

        oracle_calls = []
        def mock_run(*args, **kwargs):
            payload = json.loads(kwargs.get("input", ""))
            oracle_calls.append(payload.get("mode"))
            dim_id = payload.get("dimension", {}).get("id", "unknown")
            resp = _make_dim_score_response(dim_id, "test", [
                {"submission": "Submission_A", "raw_score": 90, "final_score": 90, "evidence": "great"},
            ])
            return type("R", (), {"stdout": json.dumps(resp), "returncode": 0})()

        with patch("app.services.oracle.subprocess.run", side_effect=mock_run):
            batch_score_submissions(db, task.id)

        assert len(oracle_calls) == 4  # 4 dimensions
        assert all(m == "dimension_score" for m in oracle_calls)

        db.refresh(sub)
        assert sub.status == SubmissionStatus.scored
        fb = json.loads(sub.oracle_feedback)
        assert fb["rank"] == 1
        assert fb["final_score"] > 0

    def test_lifecycle_no_submissions_refunds(self, db):
        """quality_first with no submissions after deadline → full refund, closed."""
        task = Task(
            title="调研", description="调研竞品",
            type=TaskType.quality_first,
            deadline=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bounty=10.0, status=TaskStatus.open,
            acceptance_criteria=json.dumps(["AC"]),
        )
        db.add(task)
        db.commit()

        with patch("app.scheduler.refund_publisher") as mock_refund:
            quality_first_lifecycle(db=db)

        db.refresh(task)
        assert task.status == TaskStatus.closed
        mock_refund.assert_called_once_with(db, task.id, rate=1.0)
