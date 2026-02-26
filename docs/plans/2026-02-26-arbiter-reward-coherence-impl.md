# Arbiter Reward & Coherence Rate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Modify arbiter bounty distribution (majority-only rewards) and replace per-challenge trust scoring with Task-level coherence rate calculation.

**Architecture:** Add `coherence_status` field to `ArbiterVote`, modify `resolve_jury()` to detect 1:1:1 deadlocks and tag votes, change `_settle_after_arbitration()` to only pass majority/neutral arbiter wallets to the contract and compute coherence rate for deferred trust scoring. No smart contract changes.

**Tech Stack:** Python, SQLAlchemy, Alembic, pytest, FastAPI

---

### Task 1: Model Changes — Add `coherence_status` to ArbiterVote + `arbiter_coherence` enum

**Files:**
- Modify: `app/models.py:60-74` (TrustEventType enum)
- Modify: `app/models.py:198-208` (ArbiterVote model)

**Step 1: Write the failing test**

Create file `tests/test_arbiter_coherence.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_arbiter_coherence.py -v`
Expected: FAIL — `ArbiterVote.__init__() got unexpected keyword argument 'coherence_status'` and `AttributeError: arbiter_coherence`

**Step 3: Write minimal implementation**

In `app/models.py`, add to `TrustEventType` enum (after line 73):

```python
    arbiter_coherence = "arbiter_coherence"
```

In `app/models.py`, add to `ArbiterVote` class (after line 207, the `reward_amount` line):

```python
    coherence_status = Column(String, nullable=True)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_arbiter_coherence.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add app/models.py tests/test_arbiter_coherence.py
git commit -m "feat: add coherence_status to ArbiterVote + arbiter_coherence event type"
```

---

### Task 2: Alembic Migration for `coherence_status`

**Files:**
- Create: `alembic/versions/<auto>_add_coherence_status.py` (auto-generated)

**Step 1: Generate migration**

```bash
alembic revision --autogenerate -m "add coherence_status to arbiter_votes"
```

**Step 2: Verify generated file**

Open the generated file in `alembic/versions/`. Confirm it contains:

```python
def upgrade() -> None:
    with op.batch_alter_table('arbiter_votes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('coherence_status', sa.String(), nullable=True))
```

**Step 3: Apply migration**

```bash
alembic upgrade head
```

**Step 4: Commit**

```bash
git add alembic/versions/*coherence_status*
git commit -m "migration: add coherence_status to arbiter_votes"
```

---

### Task 3: Update `resolve_jury()` — 1:1:1 Detection + coherence_status

**Files:**
- Modify: `app/services/arbiter_pool.py:68-92` (resolve_jury function)
- Test: `tests/test_arbiter_pool.py` (update existing + add new tests)

**Step 1: Write the failing tests**

Add to `tests/test_arbiter_coherence.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_arbiter_coherence.py::test_resolve_jury_2_1_coherence tests/test_arbiter_coherence.py::test_resolve_jury_3_0_coherence tests/test_arbiter_coherence.py::test_resolve_jury_deadlock_neutral -v`
Expected: FAIL — `coherence_status` is None (not set by current code)

**Step 3: Write implementation**

Replace `resolve_jury()` in `app/services/arbiter_pool.py:68-92` with:

```python
def resolve_jury(db: Session, challenge_id: str) -> ChallengeVerdict:
    """Resolve jury votes for a challenge. Returns the majority verdict.

    Sets coherence_status on each vote:
    - 2:1 or 3:0 → majority="coherent", minority="incoherent"
    - 1:1:1 deadlock → all="neutral", verdict defaults to rejected
    """
    votes = (
        db.query(ArbiterVote)
        .filter_by(challenge_id=challenge_id)
        .filter(ArbiterVote.vote.isnot(None))
        .all()
    )

    if not votes:
        return ChallengeVerdict.rejected

    counter = Counter(v.vote for v in votes)
    most_common = counter.most_common()

    if most_common[0][1] >= 2:
        # Consensus: 2:1 or 3:0
        majority_verdict = most_common[0][0]
        for vote in votes:
            vote.is_majority = (vote.vote == majority_verdict)
            vote.coherence_status = "coherent" if vote.is_majority else "incoherent"
    else:
        # Deadlock: 1:1:1 — status quo (rejected)
        majority_verdict = ChallengeVerdict.rejected
        for vote in votes:
            vote.is_majority = None
            vote.coherence_status = "neutral"

    db.commit()
    return majority_verdict
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_arbiter_coherence.py -v`
Expected: PASS (all 5 tests)

**Step 5: Verify existing tests still pass**

Run: `pytest tests/test_arbiter_pool.py -v`
Expected: PASS (the existing `test_resolve_jury_no_majority_defaults_rejected` test should still pass because it checks verdict=rejected; it won't check coherence_status)

**Step 6: Commit**

```bash
git add app/services/arbiter_pool.py tests/test_arbiter_coherence.py
git commit -m "feat: resolve_jury detects 1:1:1 deadlock, sets coherence_status"
```

---

### Task 4: Update `trust.py` — Support `arbiter_coherence` with dynamic delta

**Files:**
- Modify: `app/services/trust.py:38-96` (apply_event function)

**Step 1: Write the failing test**

Add to `tests/test_arbiter_coherence.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_arbiter_coherence.py::test_apply_event_arbiter_coherence_positive tests/test_arbiter_coherence.py::test_apply_event_arbiter_coherence_negative -v`
Expected: FAIL — `apply_event() got an unexpected keyword argument 'coherence_delta'`

**Step 3: Write implementation**

In `app/services/trust.py`, add `coherence_delta` parameter to `apply_event()` signature at line 38:

```python
def apply_event(
    db: Session,
    user_id: str,
    event_type: TrustEventType,
    task_bounty: float = 0.0,
    task_id: str | None = None,
    leaderboard_bonus: int = 0,
    stake_amount: float = 0.0,
    coherence_delta: float = 0.0,
) -> TrustEvent:
```

Then add a branch for `arbiter_coherence` in the delta calculation logic (after the `stake_slash` elif, before the final `else`):

```python
    elif event_type == TrustEventType.arbiter_coherence:
        delta = float(coherence_delta)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_arbiter_coherence.py -v`
Expected: PASS (all 7 tests)

**Step 5: Run full existing trust tests**

Run: `pytest tests/test_trust_service.py -v`
Expected: PASS (unchanged behavior)

**Step 6: Commit**

```bash
git add app/services/trust.py tests/test_arbiter_coherence.py
git commit -m "feat: trust.apply_event supports arbiter_coherence with dynamic delta"
```

---

### Task 5: Coherence Rate Calculator Function

**Files:**
- Modify: `app/services/trust.py` (add `compute_coherence_delta` function)

**Step 1: Write the failing test**

Add to `tests/test_arbiter_coherence.py`:

```python
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
    """0% with only 1 effective game → -10 (not -30)."""
    assert compute_coherence_delta(coherent=0, effective=1) == -10


def test_coherence_delta_zero_effective():
    """0 effective games → None (no delta to apply)."""
    assert compute_coherence_delta(coherent=0, effective=0) is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_arbiter_coherence.py::test_coherence_delta_above_80 -v`
Expected: FAIL — `ImportError: cannot import name 'compute_coherence_delta'`

**Step 3: Write implementation**

Add to `app/services/trust.py` (at end of file):

```python
def compute_coherence_delta(coherent: int, effective: int) -> int | None:
    """Compute trust score delta from arbiter coherence rate.

    Returns None if no effective games (nothing to settle).
    Tiers: >80%→+3, >60%→+2, 40-60%→0, <40%→-10, 0%&≥2→-30.
    """
    if effective == 0:
        return None

    rate = coherent / effective

    if rate == 0 and effective >= 2:
        return -30
    if rate < 0.40:
        return -10
    if rate <= 0.60:
        return 0
    if rate <= 0.80:
        return 2
    return 3
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_arbiter_coherence.py -v`
Expected: PASS (all 14 tests)

**Step 5: Commit**

```bash
git add app/services/trust.py tests/test_arbiter_coherence.py
git commit -m "feat: compute_coherence_delta — coherence rate tier calculator"
```

---

### Task 6: Remove Per-Challenge Trust Scoring + Add Coherence Settlement

**Files:**
- Modify: `app/scheduler.py:85-102` (_apply_verdict_trust — remove arbiter_majority/minority)
- Modify: `app/scheduler.py:316-412` (_settle_after_arbitration — add coherence settlement + filtered wallets)

**Step 1: Write the failing test**

Add to `tests/test_arbiter_coherence.py`:

```python
from unittest.mock import patch
from app.models import (
    Challenge, ChallengeStatus, PayoutStatus, TrustEvent,
)
from app.scheduler import _settle_after_arbitration


def _setup_arbitrated_task(db, verdicts_config):
    """Create a fully arbitrated task with given challenge configs.

    verdicts_config: list of dicts, each with:
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
    # 3 arbiters, each with 1 effective game
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
        call_args = mock_resolve.call_args
        passed_wallets = call_args[1].get("arbiter_wallets") or call_args[0][3] if len(call_args[0]) > 3 else call_args[1].get("arbiter_wallets")
        # a3 (incoherent) should NOT be in the wallet list
        assert arbiters[2].wallet not in passed_wallets
        # a1, a2 (coherent) should be present
        assert arbiters[0].wallet in passed_wallets
        assert arbiters[1].wallet in passed_wallets
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_arbiter_coherence.py::test_settle_no_per_challenge_arbiter_trust -v`
Expected: FAIL — arbiter_majority events will be found (old behavior)

**Step 3: Write implementation**

**3a.** In `app/scheduler.py`, replace `_apply_verdict_trust()` (lines 85-102) with a version that no longer applies per-challenge arbiter trust:

```python
def _apply_verdict_trust(
    db: Session, challenge: Challenge, verdict, task: Task
) -> None:
    """Set challenge verdict and status. Arbiter trust is deferred to Task-level coherence."""
    from .models import ChallengeStatus as CS
    challenge.verdict = verdict
    challenge.status = CS.judged
    db.commit()
```

**3b.** In `app/scheduler.py`, modify `_settle_after_arbitration()` — replace the arbiter wallet collection block (lines 396-410) with coherence-aware logic:

Replace lines 395-410 (from `# Collect arbiter wallets` to `_resolve_via_contract(...)`) with:

```python
        # Collect arbiter wallets: only coherent + neutral (not incoherent)
        from .models import User
        arbiter_wallet_set = set()
        for c in challenges:
            jury_votes = db.query(ArbiterVote).filter_by(challenge_id=c.id).all()
            for v in jury_votes:
                if v.coherence_status in ("coherent", "neutral"):
                    arbiter_wallet_set.add(v.arbiter_user_id)
        if arbiter_wallet_set:
            arbiter_users = db.query(User).filter(User.id.in_(arbiter_wallet_set)).all()
            arbiter_wallets = [u.wallet for u in arbiter_users if u.wallet]
        else:
            import os
            platform_wallet = os.environ.get("PLATFORM_WALLET", "")
            arbiter_wallets = [platform_wallet] if platform_wallet else []
        _resolve_via_contract(db, task, verdicts, arbiter_wallets)
```

**3c.** At the end of `_settle_after_arbitration()`, before `db.commit()`, add coherence rate settlement:

```python
    # Settle arbiter reputation via coherence rate
    from .services.trust import compute_coherence_delta
    all_votes = []
    for c in challenges:
        all_votes.extend(
            db.query(ArbiterVote).filter_by(challenge_id=c.id).all()
        )
    arbiter_groups: dict[str, list[ArbiterVote]] = {}
    for v in all_votes:
        arbiter_groups.setdefault(v.arbiter_user_id, []).append(v)

    for user_id, votes in arbiter_groups.items():
        effective = [v for v in votes
                     if v.coherence_status in ("coherent", "incoherent")]
        coherent_count = sum(1 for v in effective if v.coherence_status == "coherent")
        delta = compute_coherence_delta(coherent_count, len(effective))
        if delta is not None and delta != 0:
            apply_event(db, user_id, TrustEventType.arbiter_coherence,
                        task_id=task.id, coherence_delta=delta)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_arbiter_coherence.py -v`
Expected: PASS (all 17 tests)

**Step 5: Run all existing tests**

Run: `pytest -v`
Expected: PASS. If any existing scheduler/arbiter/trust tests fail, investigate — likely `test_resolve_jury_no_majority_defaults_rejected` in `test_arbiter_pool.py` (currently checks `is_majority` via `vote.vote == majority_verdict` but doesn't check coherence — should still pass since coherence_status is set in resolve_jury).

**Step 6: Commit**

```bash
git add app/scheduler.py tests/test_arbiter_coherence.py
git commit -m "feat: deferred arbiter trust via coherence rate, majority-only wallet distribution"
```

---

### Task 7: Final Verification & Full Test Suite

**Files:**
- All modified files

**Step 1: Run full backend test suite**

Run: `pytest -v`
Expected: ALL PASS (132+ tests)

**Step 2: Verify no regressions in arbiter pool tests**

Run: `pytest tests/test_arbiter_pool.py -v`
Expected: PASS

**Step 3: Verify no regressions in trust tests**

Run: `pytest tests/test_trust_service.py tests/test_trust_settlement.py -v`
Expected: PASS

**Step 4: Verify challenge integration tests**

Run: `pytest tests/test_challenge_integration.py -v`
Expected: PASS

**Step 5: Final commit if any fixups needed**

Only commit if Step 1-4 revealed issues that required fixes.
