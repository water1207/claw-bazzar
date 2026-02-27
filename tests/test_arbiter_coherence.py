# tests/test_arbiter_coherence.py
"""Tests for arbiter coherence status and reward distribution."""
import pytest
from app.models import (
    ArbiterVote, TrustEventType, ChallengeVerdict,
)


def test_arbiter_vote_has_coherence_status_field(client):
    """ArbiterVote model must have a coherence_status column."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    vote = ArbiterVote(
        challenge_id="ch-1",
        arbiter_user_id="arb-1",
        vote=ChallengeVerdict.upheld,
        coherence_status="coherent",
    )
    db.add(vote)
    db.commit()
    db.refresh(vote)
    assert vote.coherence_status == "coherent"


def test_trust_event_type_has_arbiter_coherence():
    """TrustEventType enum must include arbiter_coherence."""
    assert hasattr(TrustEventType, "arbiter_coherence")
    assert TrustEventType.arbiter_coherence.value == "arbiter_coherence"


from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict,
)
from app.services.arbiter_pool import resolve_jury


def _make_arbiter(db, name, wallet):
    user = User(
        nickname=name, wallet=wallet, role=UserRole.worker,
        trust_score=850.0, trust_tier=TrustTier.S,
        is_arbiter=True, staked_amount=100.0, github_id="gh-" + name,
    )
    db.add(user)
    db.commit()
    return user


def _make_challenge(db):
    publisher = User(nickname="pub-c", wallet="0xPUB", role=UserRole.publisher)
    worker = User(nickname="wrk-c", wallet="0xWRK", role=UserRole.worker)
    db.add_all([publisher, worker])
    db.commit()
    task = Task(
        title="Test", description="Test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating, publisher_id=publisher.id,
        bounty=100.0,
    )
    db.add(task)
    db.commit()
    winner_sub = Submission(
        task_id=task.id, worker_id=worker.id, content="w", score=0.9, status="scored",
    )
    db.add(winner_sub)
    db.commit()
    task.winner_submission_id = winner_sub.id
    challenge = Challenge(
        task_id=task.id, challenger_submission_id=winner_sub.id,
        target_submission_id=winner_sub.id, reason="test",
        status=ChallengeStatus.pending, challenger_wallet="0xCHL",
    )
    db.add(challenge)
    db.commit()
    return task, challenge


def test_resolve_jury_2_1_coherence(client):
    """2:1 vote → majority=coherent, minority=incoherent."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge = _make_challenge(db)
    a1 = _make_arbiter(db, "c-arb1", "0xCA1")
    a2 = _make_arbiter(db, "c-arb2", "0xCA2")
    a3 = _make_arbiter(db, "c-arb3", "0xCA3")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.upheld, feedback="a")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.upheld, feedback="b")
    v3 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a3.id,
                     vote=ChallengeVerdict.rejected, feedback="c")
    db.add_all([v1, v2, v3])
    db.commit()

    verdict = resolve_jury(db, challenge.id)
    assert verdict == ChallengeVerdict.upheld

    db.refresh(v1); db.refresh(v2); db.refresh(v3)
    assert v1.coherence_status == "coherent"
    assert v2.coherence_status == "coherent"
    assert v3.coherence_status == "incoherent"


def test_resolve_jury_3_0_coherence(client):
    """3:0 vote → all coherent."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge = _make_challenge(db)
    a1 = _make_arbiter(db, "u-arb1", "0xUA1")
    a2 = _make_arbiter(db, "u-arb2", "0xUA2")
    a3 = _make_arbiter(db, "u-arb3", "0xUA3")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.rejected, feedback="a")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.rejected, feedback="b")
    v3 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a3.id,
                     vote=ChallengeVerdict.rejected, feedback="c")
    db.add_all([v1, v2, v3])
    db.commit()

    verdict = resolve_jury(db, challenge.id)
    assert verdict == ChallengeVerdict.rejected
    db.refresh(v1); db.refresh(v2); db.refresh(v3)
    assert v1.coherence_status == "coherent"
    assert v2.coherence_status == "coherent"
    assert v3.coherence_status == "coherent"


def test_resolve_jury_deadlock_neutral(client):
    """1:1:1 deadlock → verdict=rejected, all neutral."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge = _make_challenge(db)
    a1 = _make_arbiter(db, "d-arb1", "0xDA1")
    a2 = _make_arbiter(db, "d-arb2", "0xDA2")
    a3 = _make_arbiter(db, "d-arb3", "0xDA3")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.upheld, feedback="a")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.rejected, feedback="b")
    v3 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a3.id,
                     vote=ChallengeVerdict.malicious, feedback="c")
    db.add_all([v1, v2, v3])
    db.commit()

    verdict = resolve_jury(db, challenge.id)
    assert verdict == ChallengeVerdict.rejected

    db.refresh(v1); db.refresh(v2); db.refresh(v3)
    assert v1.coherence_status == "neutral"
    assert v2.coherence_status == "neutral"
    assert v3.coherence_status == "neutral"
    assert v1.is_majority is None
    assert v2.is_majority is None
    assert v3.is_majority is None


from app.models import TrustEvent
from app.services.trust import apply_event


def test_apply_event_arbiter_coherence_positive(client):
    """arbiter_coherence with positive delta."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="ac-pos", wallet="0xACP", role=UserRole.worker)
    db.add(user)
    db.commit()

    event = apply_event(
        db, user.id, TrustEventType.arbiter_coherence,
        task_id="t1", coherence_delta=3,
    )
    db.refresh(user)
    assert event.delta == 3.0
    assert user.trust_score == 503.0


def test_apply_event_arbiter_coherence_negative(client):
    """arbiter_coherence with negative delta."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="ac-neg", wallet="0xACN", role=UserRole.worker)
    db.add(user)
    db.commit()

    event = apply_event(
        db, user.id, TrustEventType.arbiter_coherence,
        task_id="t1", coherence_delta=-30,
    )
    db.refresh(user)
    assert event.delta == -30.0
    assert user.trust_score == 470.0


from app.services.trust import compute_coherence_delta


def test_coherence_delta_above_80():
    assert compute_coherence_delta(coherent=5, effective=5) == 3   # 100%
    assert compute_coherence_delta(coherent=5, effective=6) == 3   # 83%


def test_coherence_delta_above_60():
    assert compute_coherence_delta(coherent=2, effective=3) == 2   # 66.7%
    assert compute_coherence_delta(coherent=4, effective=5) == 2   # 80% boundary


def test_coherence_delta_40_to_60():
    assert compute_coherence_delta(coherent=1, effective=2) == 0   # 50%
    assert compute_coherence_delta(coherent=2, effective=5) == 0   # 40%


def test_coherence_delta_below_40():
    assert compute_coherence_delta(coherent=1, effective=3) == -10  # 33%
    assert compute_coherence_delta(coherent=1, effective=5) == -10  # 20%


def test_coherence_delta_zero_percent_ge_2():
    assert compute_coherence_delta(coherent=0, effective=2) == -30
    assert compute_coherence_delta(coherent=0, effective=5) == -30


def test_coherence_delta_zero_percent_lt_2():
    """0% with only 1 effective game -> -10 (not -30)."""
    assert compute_coherence_delta(coherent=0, effective=1) == -10


def test_coherence_delta_zero_effective():
    """0 effective games -> None (no delta to apply)."""
    assert compute_coherence_delta(coherent=0, effective=0) is None


from unittest.mock import patch
from app.scheduler import _settle_after_arbitration


def _setup_arbitrated_task(db, verdicts_config):
    """Create a fully arbitrated task with given challenge configs.

    verdicts_config: list of dicts, each with:
        "verdict": ChallengeVerdict value
        "votes": list of (ChallengeVerdict, coherence_status) per arbiter
    Returns (task, challenges, arbiters).
    """
    publisher = User(nickname="set-pub", wallet="0xSPUB", role=UserRole.publisher)
    worker = User(nickname="set-wrk", wallet="0xSWRK", role=UserRole.worker,
                  trust_score=850.0, trust_tier=TrustTier.S)
    db.add_all([publisher, worker])
    db.commit()

    task = Task(
        title="Settle", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.arbitrating, publisher_id=publisher.id,
        bounty=100.0,
    )
    db.add(task)
    db.commit()

    winner_sub = Submission(
        task_id=task.id, worker_id=worker.id, content="w",
        score=0.9, status="scored",
    )
    db.add(winner_sub)
    db.commit()
    task.winner_submission_id = winner_sub.id

    # Create 3 shared arbiters
    a1 = _make_arbiter(db, "set-a1", "0xSA1")
    a2 = _make_arbiter(db, "set-a2", "0xSA2")
    a3 = _make_arbiter(db, "set-a3", "0xSA3")
    arbiters = [a1, a2, a3]

    challenges = []
    for i, cfg in enumerate(verdicts_config):
        challenger_user = User(
            nickname=f"set-chl-{i}", wallet=f"0xSCHL{i}", role=UserRole.worker,
        )
        db.add(challenger_user)
        db.commit()
        chl_sub = Submission(
            task_id=task.id, worker_id=challenger_user.id,
            content=f"chl-{i}", score=0.5, status="scored",
        )
        db.add(chl_sub)
        db.commit()

        challenge = Challenge(
            task_id=task.id, challenger_submission_id=chl_sub.id,
            target_submission_id=winner_sub.id, reason=f"challenge-{i}",
            status=ChallengeStatus.judged, verdict=cfg["verdict"],
            challenger_wallet=f"0xSCHL{i}",
        )
        db.add(challenge)
        db.commit()

        # Create votes with pre-set coherence_status
        for j, (vote_val, coh_status) in enumerate(cfg["votes"]):
            vote = ArbiterVote(
                challenge_id=challenge.id,
                arbiter_user_id=arbiters[j].id,
                vote=vote_val,
                coherence_status=coh_status,
                is_majority=(coh_status == "coherent"),
            )
            db.add(vote)
        db.commit()
        challenges.append(challenge)

    return task, challenges, arbiters


def test_settle_no_per_challenge_arbiter_trust(client):
    """After settlement, no arbiter_majority or arbiter_minority events exist.
    Only arbiter_coherence events should be created."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenges, arbiters = _setup_arbitrated_task(db, [
        {
            "verdict": ChallengeVerdict.rejected,
            "votes": [
                (ChallengeVerdict.rejected, "coherent"),
                (ChallengeVerdict.rejected, "coherent"),
                (ChallengeVerdict.upheld, "incoherent"),
            ],
        },
    ])

    with patch("app.scheduler._resolve_via_contract"):
        _settle_after_arbitration(db, task)

    events = db.query(TrustEvent).filter(
        TrustEvent.event_type.in_([
            TrustEventType.arbiter_majority,
            TrustEventType.arbiter_minority,
        ])
    ).all()
    assert len(events) == 0

    coherence_events = db.query(TrustEvent).filter(
        TrustEvent.event_type == TrustEventType.arbiter_coherence,
    ).all()
    # 3 arbiters: a1 coherent (rate=100%→+3), a2 coherent (100%→+3),
    # a3 incoherent (0% with 1 game → -10)
    assert len(coherence_events) == 3


def test_settle_coherence_rate_multi_challenge(client):
    """Arbiter participates in 3 challenges: 2 coherent + 1 neutral.
    Effective = 2, coherent = 2, rate = 100% → delta = +3."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenges, arbiters = _setup_arbitrated_task(db, [
        {   # 2:1 consensus
            "verdict": ChallengeVerdict.rejected,
            "votes": [
                (ChallengeVerdict.rejected, "coherent"),
                (ChallengeVerdict.rejected, "coherent"),
                (ChallengeVerdict.upheld, "incoherent"),
            ],
        },
        {   # 3:0 consensus
            "verdict": ChallengeVerdict.rejected,
            "votes": [
                (ChallengeVerdict.rejected, "coherent"),
                (ChallengeVerdict.rejected, "coherent"),
                (ChallengeVerdict.rejected, "coherent"),
            ],
        },
        {   # 1:1:1 deadlock
            "verdict": ChallengeVerdict.rejected,
            "votes": [
                (ChallengeVerdict.upheld, "neutral"),
                (ChallengeVerdict.rejected, "neutral"),
                (ChallengeVerdict.malicious, "neutral"),
            ],
        },
    ])

    with patch("app.scheduler._resolve_via_contract"):
        _settle_after_arbitration(db, task)

    # Arbiter a1: 2 coherent, 1 neutral → effective=2, rate=100% → +3
    a1_event = db.query(TrustEvent).filter(
        TrustEvent.user_id == arbiters[0].id,
        TrustEvent.event_type == TrustEventType.arbiter_coherence,
    ).first()
    assert a1_event is not None
    assert a1_event.delta == 3.0

    # Arbiter a3: 1 incoherent + 1 coherent + 1 neutral → effective=2,
    # coherent=1, rate=50% → 0
    a3_event = db.query(TrustEvent).filter(
        TrustEvent.user_id == arbiters[2].id,
        TrustEvent.event_type == TrustEventType.arbiter_coherence,
    ).first()
    assert a3_event is not None
    assert a3_event.delta == 0.0


def test_settle_only_majority_wallets_passed(client):
    """_resolve_via_contract receives only coherent+neutral arbiter wallets."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenges, arbiters = _setup_arbitrated_task(db, [
        {   # 2:1 → a3 is incoherent
            "verdict": ChallengeVerdict.rejected,
            "votes": [
                (ChallengeVerdict.rejected, "coherent"),
                (ChallengeVerdict.rejected, "coherent"),
                (ChallengeVerdict.upheld, "incoherent"),
            ],
        },
    ])

    with patch("app.scheduler._resolve_via_contract") as mock_resolve:
        _settle_after_arbitration(db, task)
        mock_resolve.assert_called_once()
        args, kwargs = mock_resolve.call_args
        # V2: arbiters are per-verdict inside verdicts (3rd positional arg)
        verdicts = args[2]
        # Collect all arbiter wallets across verdicts
        passed_wallets = []
        for v in verdicts:
            passed_wallets.extend(v.get("arbiters", []))
        # a3 (incoherent) should NOT be in the wallet list
        assert arbiters[2].wallet not in passed_wallets
        # a1, a2 (coherent) should be present
        assert arbiters[0].wallet in passed_wallets
        assert arbiters[1].wallet in passed_wallets
