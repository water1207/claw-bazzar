# Claw Trust 信誉分机制 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the Claw Trust reputation system — logarithmic scoring engine, 3-person arbiter jury, StakingVault contract, dynamic fees/permissions, GitHub OAuth, and weekly leaderboard.

**Architecture:** Layered service architecture with TrustService (scoring engine), ArbiterPoolService (jury management), and StakingService (on-chain staking). All trust score computation is off-chain (SQLite). Dynamic fees enforced by backend Relayer before on-chain calls. StakingVault is a new independent Solidity contract.

**Tech Stack:** Python/FastAPI, SQLAlchemy, Solidity 0.8.20 (Foundry), web3.py, GitHub OAuth, APScheduler

**Design Doc:** `docs/plans/2026-02-25-claw-trust-design.md`
**Reference Spec:** `docs/trust.md`

---

## Task 1: New Enums and Model Fields

**Files:**
- Modify: `app/models.py` (lines 1-125)
- Test: `tests/test_trust_models.py` (create)

**Step 1: Write failing test for new enums and User model fields**

```python
# tests/test_trust_models.py
from app.models import (
    TrustTier, TrustEventType, StakePurpose,
    User, TrustEvent, ArbiterVote, StakeRecord,
)
from app.database import Base, engine, SessionLocal


def test_trust_tier_enum():
    assert TrustTier.S.value == "S"
    assert TrustTier.A.value == "A"
    assert TrustTier.B.value == "B"
    assert TrustTier.C.value == "C"


def test_trust_event_type_enum():
    assert TrustEventType.worker_won.value == "worker_won"
    assert TrustEventType.challenger_won.value == "challenger_won"
    assert TrustEventType.arbiter_majority.value == "arbiter_majority"
    assert TrustEventType.stake_slash.value == "stake_slash"


def test_stake_purpose_enum():
    assert StakePurpose.arbiter_deposit.value == "arbiter_deposit"
    assert StakePurpose.credit_recharge.value == "credit_recharge"


def test_user_model_trust_fields(client):
    """User model has trust-related fields with correct defaults."""
    from app.database import SessionLocal
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(
        nickname="trust-test",
        wallet="0xTEST",
        role="worker",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.trust_score == 500.0
    assert user.trust_tier == TrustTier.A
    assert user.github_id is None
    assert user.github_bonus_claimed is False
    assert user.consolation_total == 0.0
    assert user.is_arbiter is False
    assert user.staked_amount == 0.0
    assert user.stake_bonus == 0.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_trust_models.py -v`
Expected: ImportError — `TrustTier` not found

**Step 3: Add new enums and modify User model in models.py**

In `app/models.py`, add after `ChallengeStatus` enum (line 47):

```python
class TrustTier(str, PyEnum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"


class TrustEventType(str, PyEnum):
    worker_won = "worker_won"
    worker_consolation = "worker_consolation"
    worker_malicious = "worker_malicious"
    challenger_won = "challenger_won"
    challenger_rejected = "challenger_rejected"
    challenger_malicious = "challenger_malicious"
    arbiter_majority = "arbiter_majority"
    arbiter_minority = "arbiter_minority"
    arbiter_timeout = "arbiter_timeout"
    github_bind = "github_bind"
    weekly_leaderboard = "weekly_leaderboard"
    stake_bonus = "stake_bonus"
    stake_slash = "stake_slash"


class StakePurpose(str, PyEnum):
    arbiter_deposit = "arbiter_deposit"
    credit_recharge = "credit_recharge"
```

Modify `User` model (currently lines 84-92). Replace `credit_score` with trust fields:

```python
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    nickname = Column(String, unique=True, nullable=False)
    wallet = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    trust_score = Column(Float, nullable=False, default=500.0)
    trust_tier = Column(Enum(TrustTier), nullable=False, default=TrustTier.A)
    github_id = Column(String, nullable=True)
    github_bonus_claimed = Column(Boolean, nullable=False, default=False)
    consolation_total = Column(Float, nullable=False, default=0.0)
    is_arbiter = Column(Boolean, nullable=False, default=False)
    staked_amount = Column(Float, nullable=False, default=0.0)
    stake_bonus = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
```

Add `Boolean` to the SQLAlchemy imports at the top of models.py:
```python
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, Enum, Boolean
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_trust_models.py -v`
Expected: PASS

**Step 5: Fix all existing tests that reference `credit_score`**

Search for `credit_score` in all test files and replace with `trust_score`. Also update default value expectations from 100.0 to 500.0. Key files:
- `tests/test_users.py` — user creation returns `trust_score: 500.0`
- `tests/test_challenge_integration.py` — credit score adjustments
- `tests/test_arbitration.py` — credit score changes after arbitration
- `app/schemas.py` — `UserOut.credit_score` → `UserOut.trust_score`

Run: `pytest -v`
Expected: All existing tests pass (may need multiple rounds of fixes)

**Step 6: Commit**

```bash
git add app/models.py app/schemas.py tests/
git commit -m "feat(trust): add TrustTier/TrustEventType enums, replace credit_score with trust_score"
```

---

## Task 2: TrustEvent, ArbiterVote, StakeRecord Models

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Modify: `tests/test_trust_models.py`

**Step 1: Write failing tests for new models**

Add to `tests/test_trust_models.py`:

```python
def test_trust_event_model(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="evt-user", wallet="0x1", role="worker")
    db.add(user)
    db.commit()
    event = TrustEvent(
        user_id=user.id,
        event_type=TrustEventType.worker_won,
        task_id="task-123",
        amount=90.0,
        delta=10.0,
        score_before=500.0,
        score_after=510.0,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    assert event.id is not None
    assert event.delta == 10.0


def test_arbiter_vote_model(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    vote = ArbiterVote(
        challenge_id="ch-1",
        arbiter_user_id="user-1",
        vote="upheld",
        feedback="The challenger's submission is clearly better.",
    )
    db.add(vote)
    db.commit()
    db.refresh(vote)
    assert vote.id is not None
    assert vote.is_majority is None


def test_stake_record_model(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    record = StakeRecord(
        user_id="user-1",
        amount=100.0,
        purpose=StakePurpose.arbiter_deposit,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    assert record.slashed is False
```

**Step 2: Run test to verify failures**

Run: `pytest tests/test_trust_models.py::test_trust_event_model -v`
Expected: ImportError — TrustEvent not found

**Step 3: Add new models to models.py**

```python
class TrustEvent(Base):
    __tablename__ = "trust_events"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    event_type = Column(Enum(TrustEventType), nullable=False)
    task_id = Column(String, nullable=True)
    amount = Column(Float, nullable=False, default=0.0)
    delta = Column(Float, nullable=False)
    score_before = Column(Float, nullable=False)
    score_after = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ArbiterVote(Base):
    __tablename__ = "arbiter_votes"

    id = Column(String, primary_key=True, default=_uuid)
    challenge_id = Column(String, nullable=False)
    arbiter_user_id = Column(String, nullable=False)
    vote = Column(Enum(ChallengeVerdict), nullable=True)
    feedback = Column(Text, nullable=True)
    is_majority = Column(Boolean, nullable=True)
    reward_amount = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class StakeRecord(Base):
    __tablename__ = "stake_records"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    purpose = Column(Enum(StakePurpose), nullable=False)
    tx_hash = Column(String, nullable=True)
    slashed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
```

**Step 4: Add corresponding Pydantic schemas to schemas.py**

```python
from .models import (
    TaskType, TaskStatus, SubmissionStatus, UserRole, PayoutStatus,
    ChallengeVerdict, ChallengeStatus, TrustTier, TrustEventType, StakePurpose,
)

# Update UserOut — replace credit_score with trust fields
class UserOut(BaseModel):
    id: str
    nickname: str
    wallet: str
    role: UserRole
    trust_score: float = 500.0
    trust_tier: TrustTier = TrustTier.A
    github_id: Optional[str] = None
    is_arbiter: bool = False
    staked_amount: float = 0.0
    created_at: UTCDatetime

    model_config = {"from_attributes": True}


# New schemas
class TrustProfile(BaseModel):
    trust_score: float
    trust_tier: TrustTier
    challenge_deposit_rate: float
    platform_fee_rate: float
    can_accept_tasks: bool
    can_challenge: bool
    max_task_amount: Optional[float] = None
    is_arbiter: bool
    github_bound: bool
    staked_amount: float
    stake_bonus: float
    consolation_total: float


class TrustEventOut(BaseModel):
    id: str
    event_type: TrustEventType
    task_id: Optional[str] = None
    amount: float
    delta: float
    score_before: float
    score_after: float
    created_at: UTCDatetime

    model_config = {"from_attributes": True}


class ArbiterVoteCreate(BaseModel):
    verdict: ChallengeVerdict
    feedback: str


class ArbiterVoteOut(BaseModel):
    id: str
    challenge_id: str
    arbiter_user_id: str
    vote: Optional[ChallengeVerdict] = None
    feedback: Optional[str] = None
    is_majority: Optional[bool] = None
    reward_amount: Optional[float] = None
    created_at: UTCDatetime

    model_config = {"from_attributes": True}


class StakeRequest(BaseModel):
    amount: float
    purpose: StakePurpose
    permit_deadline: Optional[int] = None
    permit_v: Optional[int] = None
    permit_r: Optional[str] = None
    permit_s: Optional[str] = None


class TrustQuote(BaseModel):
    trust_tier: TrustTier
    challenge_deposit_rate: float
    challenge_deposit_amount: float
    platform_fee_rate: float
    service_fee: float = 0.01


class WeeklyLeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    nickname: str
    wallet: str
    total_settled: float
    bonus: int
```

**Step 5: Run all tests**

Run: `pytest -v`
Expected: All pass

**Step 6: Commit**

```bash
git add app/models.py app/schemas.py tests/test_trust_models.py
git commit -m "feat(trust): add TrustEvent, ArbiterVote, StakeRecord models and schemas"
```

---

## Task 3: TrustService — Scoring Engine

**Files:**
- Create: `app/services/trust.py`
- Create: `tests/test_trust_service.py`

**Step 1: Write failing tests for multiplier and apply_event**

```python
# tests/test_trust_service.py
import math
import pytest
from unittest.mock import patch
from app.models import User, TrustEvent, TrustTier, TrustEventType, UserRole
from app.services.trust import (
    _multiplier, _compute_tier, apply_event,
    get_challenge_deposit_rate, get_platform_fee_rate,
    check_permissions,
)


def test_multiplier_zero():
    assert _multiplier(0) == 1.0


def test_multiplier_10():
    assert abs(_multiplier(10) - (1 + math.log10(2))) < 0.01


def test_multiplier_90():
    assert abs(_multiplier(90) - 2.0) < 0.01


def test_multiplier_990():
    assert abs(_multiplier(990) - 3.0) < 0.01


def test_compute_tier():
    assert _compute_tier(1000) == TrustTier.S
    assert _compute_tier(800) == TrustTier.S
    assert _compute_tier(799) == TrustTier.A
    assert _compute_tier(500) == TrustTier.A
    assert _compute_tier(499) == TrustTier.B
    assert _compute_tier(300) == TrustTier.B
    assert _compute_tier(299) == TrustTier.C
    assert _compute_tier(0) == TrustTier.C


def test_apply_event_worker_won(client):
    """Worker won with 90 USDC bounty: +5 * 2.0 = +10 points."""
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="w1", wallet="0x1", role=UserRole.worker)
    db.add(user)
    db.commit()

    event = apply_event(db, user.id, TrustEventType.worker_won, task_bounty=90.0)

    db.refresh(user)
    assert abs(event.delta - 10.0) < 0.1  # 5 * 2.0
    assert abs(user.trust_score - 510.0) < 0.1
    assert user.trust_tier == TrustTier.A


def test_apply_event_worker_consolation_cap(client):
    """Consolation is fixed +1, capped at 50 total."""
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="w2", wallet="0x2", role=UserRole.worker,
                consolation_total=49.0)
    db.add(user)
    db.commit()

    # First: +1 (total becomes 50)
    event1 = apply_event(db, user.id, TrustEventType.worker_consolation)
    assert event1.delta == 1.0

    # Second: capped, delta=0
    event2 = apply_event(db, user.id, TrustEventType.worker_consolation)
    assert event2.delta == 0.0

    db.refresh(user)
    assert user.consolation_total == 50.0


def test_apply_event_worker_malicious(client):
    """Malicious submission: fixed -100."""
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="w3", wallet="0x3", role=UserRole.worker)
    db.add(user)
    db.commit()

    event = apply_event(db, user.id, TrustEventType.worker_malicious)
    assert event.delta == -100.0

    db.refresh(user)
    assert user.trust_score == 400.0
    assert user.trust_tier == TrustTier.B


def test_apply_event_challenger_won(client):
    """Challenge succeeded with 990 USDC: +10 * 3.0 = +30."""
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="c1", wallet="0x4", role=UserRole.worker)
    db.add(user)
    db.commit()

    event = apply_event(db, user.id, TrustEventType.challenger_won, task_bounty=990.0)
    assert abs(event.delta - 30.0) < 0.1

    db.refresh(user)
    assert abs(user.trust_score - 530.0) < 0.1


def test_apply_event_score_clamp(client):
    """Score never exceeds 1000 or drops below 0."""
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="clamp", wallet="0x5", role=UserRole.worker,
                trust_score=950.0, trust_tier=TrustTier.S)
    db.add(user)
    db.commit()

    # Try to push above 1000
    event = apply_event(db, user.id, TrustEventType.challenger_won, task_bounty=990.0)
    db.refresh(user)
    assert user.trust_score == 1000.0

    # Now push below 0
    user2 = User(nickname="clamp2", wallet="0x6", role=UserRole.worker,
                 trust_score=50.0, trust_tier=TrustTier.C)
    db.add(user2)
    db.commit()
    event2 = apply_event(db, user2.id, TrustEventType.worker_malicious)
    db.refresh(user2)
    assert user2.trust_score == 0.0


def test_apply_event_creates_trust_event(client):
    """Each apply_event writes a TrustEvent log record."""
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="log1", wallet="0x7", role=UserRole.worker)
    db.add(user)
    db.commit()

    apply_event(db, user.id, TrustEventType.github_bind)

    events = db.query(TrustEvent).filter_by(user_id=user.id).all()
    assert len(events) == 1
    assert events[0].event_type == TrustEventType.github_bind
    assert events[0].delta == 50.0
    assert events[0].score_before == 500.0
    assert events[0].score_after == 550.0


def test_get_challenge_deposit_rate():
    assert get_challenge_deposit_rate(TrustTier.S) == 0.05
    assert get_challenge_deposit_rate(TrustTier.A) == 0.10
    assert get_challenge_deposit_rate(TrustTier.B) == 0.30
    with pytest.raises(ValueError):
        get_challenge_deposit_rate(TrustTier.C)


def test_get_platform_fee_rate():
    assert get_platform_fee_rate(TrustTier.S) == 0.15
    assert get_platform_fee_rate(TrustTier.A) == 0.20
    assert get_platform_fee_rate(TrustTier.B) == 0.25
    with pytest.raises(ValueError):
        get_platform_fee_rate(TrustTier.C)


def test_check_permissions_c_level(client):
    """C-level users cannot accept tasks or challenge."""
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="banned", wallet="0x8", role=UserRole.worker,
                trust_score=100.0, trust_tier=TrustTier.C)
    db.add(user)
    db.commit()

    perms = check_permissions(user)
    assert perms["can_accept_tasks"] is False
    assert perms["can_challenge"] is False


def test_check_permissions_b_level(client):
    """B-level users have 50 USDC cap."""
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="warning", wallet="0x9", role=UserRole.worker,
                trust_score=400.0, trust_tier=TrustTier.B)
    db.add(user)
    db.commit()

    perms = check_permissions(user)
    assert perms["can_accept_tasks"] is True
    assert perms["can_challenge"] is True
    assert perms["max_task_amount"] == 50.0
```

**Step 2: Run test to verify failures**

Run: `pytest tests/test_trust_service.py -v`
Expected: ImportError — `app.services.trust` not found

**Step 3: Implement TrustService**

```python
# app/services/trust.py
import math
from sqlalchemy.orm import Session
from app.models import User, TrustEvent, TrustTier, TrustEventType


def _multiplier(amount: float) -> float:
    """Logarithmic amount weighting: M = 1 + log10(1 + amount/10)."""
    return 1 + math.log10(1 + amount / 10)


def _compute_tier(score: float) -> TrustTier:
    if score >= 800:
        return TrustTier.S
    if score >= 500:
        return TrustTier.A
    if score >= 300:
        return TrustTier.B
    return TrustTier.C


# Fixed deltas for each event type
_FIXED_DELTAS = {
    TrustEventType.worker_malicious: -100,
    TrustEventType.challenger_rejected: -3,
    TrustEventType.challenger_malicious: -100,
    TrustEventType.arbiter_majority: 2,
    TrustEventType.arbiter_minority: -15,
    TrustEventType.arbiter_timeout: -10,
    TrustEventType.github_bind: 50,
}

# Weighted deltas (base * multiplier)
_WEIGHTED_BASES = {
    TrustEventType.worker_won: 5,
    TrustEventType.challenger_won: 10,
}


def apply_event(
    db: Session,
    user_id: str,
    event_type: TrustEventType,
    task_bounty: float = 0.0,
    task_id: str | None = None,
    leaderboard_bonus: int = 0,
    stake_amount: float = 0.0,
) -> TrustEvent:
    """Apply a trust event to a user. Returns the TrustEvent record."""
    user = db.query(User).filter_by(id=user_id).one()
    score_before = user.trust_score

    # Calculate delta
    if event_type in _WEIGHTED_BASES:
        m = _multiplier(task_bounty)
        delta = _WEIGHTED_BASES[event_type] * m
    elif event_type in _FIXED_DELTAS:
        delta = float(_FIXED_DELTAS[event_type])
    elif event_type == TrustEventType.worker_consolation:
        if user.consolation_total >= 50.0:
            delta = 0.0
        else:
            delta = 1.0
            user.consolation_total = min(user.consolation_total + 1.0, 50.0)
    elif event_type == TrustEventType.weekly_leaderboard:
        delta = float(leaderboard_bonus)
    elif event_type == TrustEventType.stake_bonus:
        # +50 per $50, capped at +100 total stake_bonus
        potential = (stake_amount / 50.0) * 50.0
        remaining_cap = 100.0 - user.stake_bonus
        delta = min(potential, remaining_cap)
        if delta > 0:
            user.stake_bonus += delta
    elif event_type == TrustEventType.stake_slash:
        # Remove all stake bonus
        delta = -user.stake_bonus if user.stake_bonus > 0 else 0.0
        user.stake_bonus = 0.0
        user.staked_amount = 0.0
        user.is_arbiter = False
    else:
        delta = 0.0

    # Apply and clamp
    new_score = max(0.0, min(1000.0, score_before + delta))
    actual_delta = new_score - score_before

    user.trust_score = new_score
    user.trust_tier = _compute_tier(new_score)

    # Log event
    event = TrustEvent(
        user_id=user_id,
        event_type=event_type,
        task_id=task_id,
        amount=task_bounty,
        delta=actual_delta,
        score_before=score_before,
        score_after=new_score,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_challenge_deposit_rate(tier: TrustTier) -> float:
    rates = {TrustTier.S: 0.05, TrustTier.A: 0.10, TrustTier.B: 0.30}
    if tier == TrustTier.C:
        raise ValueError("C-level users cannot challenge")
    return rates[tier]


def get_platform_fee_rate(tier: TrustTier) -> float:
    rates = {TrustTier.S: 0.15, TrustTier.A: 0.20, TrustTier.B: 0.25}
    if tier == TrustTier.C:
        raise ValueError("C-level users are banned")
    return rates[tier]


def check_permissions(user: User) -> dict:
    """Return permission dict for the user based on trust tier."""
    tier = user.trust_tier
    if tier == TrustTier.C:
        return {
            "can_accept_tasks": False,
            "can_challenge": False,
            "max_task_amount": None,
        }
    result = {
        "can_accept_tasks": True,
        "can_challenge": True,
        "max_task_amount": None,
    }
    if tier == TrustTier.B:
        result["max_task_amount"] = 50.0
    return result
```

**Step 4: Run tests**

Run: `pytest tests/test_trust_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/services/trust.py tests/test_trust_service.py
git commit -m "feat(trust): implement TrustService scoring engine with logarithmic weighting"
```

---

## Task 4: ArbiterPoolService — Jury Selection & Voting

**Files:**
- Create: `app/services/arbiter_pool.py`
- Create: `tests/test_arbiter_pool.py`

**Step 1: Write failing tests for jury selection**

```python
# tests/test_arbiter_pool.py
import pytest
from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict,
)
from app.services.arbiter_pool import (
    select_jury, submit_vote, resolve_jury, check_jury_ready,
)


def _make_arbiter(db, name, wallet):
    """Helper to create an S-tier arbiter user."""
    user = User(
        nickname=name, wallet=wallet, role=UserRole.worker,
        trust_score=850.0, trust_tier=TrustTier.S,
        is_arbiter=True, staked_amount=100.0, github_id="gh-" + name,
    )
    db.add(user)
    db.commit()
    return user


def _make_task_with_challenge(db):
    """Helper to create a task in arbitrating state with a challenge."""
    publisher = User(nickname="pub", wallet="0xPUB", role=UserRole.publisher)
    worker = User(nickname="wrk", wallet="0xWRK", role=UserRole.worker)
    challenger_user = User(nickname="chl", wallet="0xCHL", role=UserRole.worker)
    db.add_all([publisher, worker, challenger_user])
    db.commit()

    task = Task(
        title="Test", description="Test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating, publisher_id=publisher.id,
        bounty=100.0, challenge_duration=7200,
    )
    db.add(task)
    db.commit()

    winner_sub = Submission(
        task_id=task.id, worker_id=worker.id, content="winner",
        score=0.9, status="scored",
    )
    challenger_sub = Submission(
        task_id=task.id, worker_id=challenger_user.id, content="challenger",
        score=0.7, status="scored",
    )
    db.add_all([winner_sub, challenger_sub])
    db.commit()

    task.winner_submission_id = winner_sub.id

    challenge = Challenge(
        task_id=task.id,
        challenger_submission_id=challenger_sub.id,
        target_submission_id=winner_sub.id,
        reason="My submission is better",
        status=ChallengeStatus.pending,
        challenger_wallet="0xCHL",
    )
    db.add(challenge)
    db.commit()
    return task, challenge, publisher, worker, challenger_user


def test_select_jury_picks_3(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")
    a3 = _make_arbiter(db, "arb3", "0xA3")
    a4 = _make_arbiter(db, "arb4", "0xA4")

    votes = select_jury(db, task.id)
    assert len(votes) == 3
    # All votes should be for eligible arbiters (not pub/wrk/chl)
    arbiter_ids = {v.arbiter_user_id for v in votes}
    assert pub.id not in arbiter_ids
    assert wrk.id not in arbiter_ids
    assert chl.id not in arbiter_ids


def test_select_jury_excludes_task_participants(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    # Make the worker also an arbiter — should be excluded
    wrk.trust_score = 850.0
    wrk.trust_tier = TrustTier.S
    wrk.is_arbiter = True
    wrk.staked_amount = 100.0
    wrk.github_id = "gh-wrk"
    db.commit()

    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")
    a3 = _make_arbiter(db, "arb3", "0xA3")

    votes = select_jury(db, task.id)
    arbiter_ids = {v.arbiter_user_id for v in votes}
    assert wrk.id not in arbiter_ids


def test_select_jury_fallback_stub(client):
    """If 0 arbiters available, returns empty list (fallback to stub)."""
    db = next(iter(client.app.dependency_overrides.values()))()
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    votes = select_jury(db, task.id)
    assert len(votes) == 0  # No arbiters → fallback


def test_submit_vote(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)
    a1 = _make_arbiter(db, "arb1", "0xA1")

    vote_record = ArbiterVote(
        challenge_id=challenge.id, arbiter_user_id=a1.id,
    )
    db.add(vote_record)
    db.commit()

    updated = submit_vote(db, vote_record.id, ChallengeVerdict.upheld,
                          "The challenger made valid points")
    assert updated.vote == ChallengeVerdict.upheld
    assert updated.feedback == "The challenger made valid points"


def test_resolve_jury_majority_upheld(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")
    a3 = _make_arbiter(db, "arb3", "0xA3")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.upheld, feedback="Agree")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.upheld, feedback="Agree too")
    v3 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a3.id,
                     vote=ChallengeVerdict.rejected, feedback="Disagree")
    db.add_all([v1, v2, v3])
    db.commit()

    verdict = resolve_jury(db, challenge.id)
    assert verdict == ChallengeVerdict.upheld

    db.refresh(v1)
    db.refresh(v2)
    db.refresh(v3)
    assert v1.is_majority is True
    assert v2.is_majority is True
    assert v3.is_majority is False


def test_resolve_jury_no_majority_defaults_rejected(client):
    """3 different votes → default to rejected."""
    db = next(iter(client.app.dependency_overrides.values()))()
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)
    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")
    a3 = _make_arbiter(db, "arb3", "0xA3")

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
```

**Step 2: Run tests to verify failures**

Run: `pytest tests/test_arbiter_pool.py -v`
Expected: ImportError

**Step 3: Implement ArbiterPoolService**

```python
# app/services/arbiter_pool.py
import random
from collections import Counter
from sqlalchemy.orm import Session
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    ChallengeVerdict, ChallengeStatus,
)

JURY_SIZE = 3


def select_jury(db: Session, task_id: str) -> list[ArbiterVote]:
    """Select up to 3 random arbiters for a task, excluding participants."""
    task = db.query(Task).filter_by(id=task_id).one()

    # Collect all participant user IDs to exclude
    exclude_ids = set()
    if task.publisher_id:
        exclude_ids.add(task.publisher_id)
    submissions = db.query(Submission).filter_by(task_id=task_id).all()
    for sub in submissions:
        exclude_ids.add(sub.worker_id)
    challenges = db.query(Challenge).filter_by(task_id=task_id).all()
    for ch in challenges:
        challenger_sub = db.query(Submission).filter_by(id=ch.challenger_submission_id).first()
        if challenger_sub:
            exclude_ids.add(challenger_sub.worker_id)

    # Query eligible arbiters
    eligible = (
        db.query(User)
        .filter(User.is_arbiter == True, ~User.id.in_(exclude_ids))
        .all()
    )

    if not eligible:
        return []

    selected = random.sample(eligible, min(JURY_SIZE, len(eligible)))

    votes = []
    for user in selected:
        # Create one vote record per challenge per arbiter
        for challenge in challenges:
            vote = ArbiterVote(
                challenge_id=challenge.id,
                arbiter_user_id=user.id,
            )
            db.add(vote)
            votes.append(vote)
    db.commit()
    for v in votes:
        db.refresh(v)
    return votes


def submit_vote(
    db: Session,
    vote_id: str,
    verdict: ChallengeVerdict,
    feedback: str,
) -> ArbiterVote:
    """Arbiter submits their vote."""
    vote = db.query(ArbiterVote).filter_by(id=vote_id).one()
    if vote.vote is not None:
        raise ValueError("Already voted")
    vote.vote = verdict
    vote.feedback = feedback
    db.commit()
    db.refresh(vote)
    return vote


def resolve_jury(db: Session, challenge_id: str) -> ChallengeVerdict:
    """Resolve jury votes for a challenge. Returns the majority verdict."""
    votes = (
        db.query(ArbiterVote)
        .filter_by(challenge_id=challenge_id)
        .filter(ArbiterVote.vote.isnot(None))
        .all()
    )

    if not votes:
        return ChallengeVerdict.rejected

    # Count votes
    counter = Counter(v.vote for v in votes)
    most_common = counter.most_common()

    # Check for majority (>=2 out of 3)
    if most_common[0][1] >= 2:
        majority_verdict = most_common[0][0]
    else:
        # No clear majority → default rejected
        majority_verdict = ChallengeVerdict.rejected

    # Mark majority/minority
    for vote in votes:
        vote.is_majority = (vote.vote == majority_verdict)

    db.commit()
    return majority_verdict


def check_jury_ready(db: Session, challenge_id: str) -> bool:
    """Check if all jury members have voted for a challenge."""
    votes = db.query(ArbiterVote).filter_by(challenge_id=challenge_id).all()
    if not votes:
        return False
    return all(v.vote is not None for v in votes)
```

**Step 4: Run tests**

Run: `pytest tests/test_arbiter_pool.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/services/arbiter_pool.py tests/test_arbiter_pool.py
git commit -m "feat(trust): implement ArbiterPoolService with 3-person jury selection and voting"
```

---

## Task 5: StakingVault Smart Contract

**Files:**
- Create: `contracts/src/StakingVault.sol`
- Create: `contracts/test/StakingVault.t.sol`

**Step 1: Write the Solidity contract**

```solidity
// contracts/src/StakingVault.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface IERC20Permit {
    function permit(
        address owner, address spender, uint256 value,
        uint256 deadline, uint8 v, bytes32 r, bytes32 s
    ) external;
}

contract StakingVault is Ownable {
    IERC20 public immutable usdc;
    IERC20Permit public immutable usdcPermit;

    uint256 public constant EMERGENCY_TIMEOUT = 30 days;

    struct Stake {
        uint256 amount;
        uint256 timestamp;
        bool slashed;
    }

    mapping(address => Stake) public stakes;

    event Staked(address indexed user, uint256 amount);
    event Unstaked(address indexed user, uint256 amount);
    event Slashed(address indexed user, uint256 amount);

    constructor(address _usdc) Ownable(msg.sender) {
        usdc = IERC20(_usdc);
        usdcPermit = IERC20Permit(_usdc);
    }

    function stake(
        address user,
        uint256 amount,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external onlyOwner {
        require(amount > 0, "Amount must be > 0");
        require(!stakes[user].slashed, "User is slashed");

        // Try permit (may fail on testnet USDC)
        try usdcPermit.permit(user, address(this), amount, deadline, v, r, s) {} catch {}

        // Transfer USDC from user to vault
        require(
            usdc.transferFrom(user, address(this), amount),
            "Transfer failed"
        );

        stakes[user].amount += amount;
        if (stakes[user].timestamp == 0) {
            stakes[user].timestamp = block.timestamp;
        }

        emit Staked(user, amount);
    }

    function unstake(address user, uint256 amount) external onlyOwner {
        require(stakes[user].amount >= amount, "Insufficient stake");
        require(!stakes[user].slashed, "User is slashed");

        stakes[user].amount -= amount;
        require(usdc.transfer(user, amount), "Transfer failed");

        emit Unstaked(user, amount);
    }

    function slash(address user) external onlyOwner {
        uint256 amount = stakes[user].amount;
        require(amount > 0, "Nothing to slash");

        stakes[user].amount = 0;
        stakes[user].slashed = true;

        // Send slashed funds to owner (platform treasury)
        require(usdc.transfer(owner(), amount), "Transfer failed");

        emit Slashed(user, amount);
    }

    function emergencyWithdraw(address user) external onlyOwner {
        require(
            block.timestamp >= stakes[user].timestamp + EMERGENCY_TIMEOUT,
            "Too early"
        );
        uint256 amount = stakes[user].amount;
        require(amount > 0, "Nothing to withdraw");

        stakes[user].amount = 0;
        require(usdc.transfer(user, amount), "Transfer failed");

        emit Unstaked(user, amount);
    }
}
```

**Step 2: Write Foundry tests**

```solidity
// contracts/test/StakingVault.t.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/StakingVault.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MockUSDC is ERC20 {
    constructor() ERC20("USDC", "USDC") {
        _mint(msg.sender, 1_000_000e6);
    }
    function decimals() public pure override returns (uint8) { return 6; }
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

contract StakingVaultTest is Test {
    StakingVault vault;
    MockUSDC usdc;
    address owner = address(this);
    address user1 = address(0x1);
    address user2 = address(0x2);

    function setUp() public {
        usdc = new MockUSDC();
        vault = new StakingVault(address(usdc));
        // Fund users
        usdc.mint(user1, 1000e6);
        usdc.mint(user2, 1000e6);
        // Users approve vault
        vm.prank(user1);
        usdc.approve(address(vault), type(uint256).max);
        vm.prank(user2);
        usdc.approve(address(vault), type(uint256).max);
    }

    function test_stake() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        (uint256 amount,,) = vault.stakes(user1);
        assertEq(amount, 100e6);
        assertEq(usdc.balanceOf(address(vault)), 100e6);
    }

    function test_stake_accumulates() public {
        vault.stake(user1, 50e6, 0, 0, bytes32(0), bytes32(0));
        vault.stake(user1, 50e6, 0, 0, bytes32(0), bytes32(0));
        (uint256 amount,,) = vault.stakes(user1);
        assertEq(amount, 100e6);
    }

    function test_unstake() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        vault.unstake(user1, 50e6);
        (uint256 amount,,) = vault.stakes(user1);
        assertEq(amount, 50e6);
        assertEq(usdc.balanceOf(user1), 950e6);
    }

    function test_unstake_insufficient() public {
        vault.stake(user1, 50e6, 0, 0, bytes32(0), bytes32(0));
        vm.expectRevert("Insufficient stake");
        vault.unstake(user1, 100e6);
    }

    function test_slash() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        uint256 ownerBefore = usdc.balanceOf(owner);
        vault.slash(user1);

        (uint256 amount,, bool slashed) = vault.stakes(user1);
        assertEq(amount, 0);
        assertTrue(slashed);
        assertEq(usdc.balanceOf(owner), ownerBefore + 100e6);
    }

    function test_slash_prevents_restake() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        vault.slash(user1);
        vm.expectRevert("User is slashed");
        vault.stake(user1, 50e6, 0, 0, bytes32(0), bytes32(0));
    }

    function test_emergency_withdraw_too_early() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        vm.expectRevert("Too early");
        vault.emergencyWithdraw(user1);
    }

    function test_emergency_withdraw_after_timeout() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        vm.warp(block.timestamp + 31 days);
        vault.emergencyWithdraw(user1);
        (uint256 amount,,) = vault.stakes(user1);
        assertEq(amount, 0);
        assertEq(usdc.balanceOf(user1), 1000e6);
    }

    function test_only_owner() public {
        vm.prank(user1);
        vm.expectRevert();
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
    }

    function test_slash_nothing() public {
        vm.expectRevert("Nothing to slash");
        vault.slash(user1);
    }
}
```

**Step 3: Run Foundry tests**

Run: `cd contracts && forge test -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add contracts/src/StakingVault.sol contracts/test/StakingVault.t.sol
git commit -m "feat(trust): add StakingVault smart contract with stake/unstake/slash"
```

---

## Task 6: StakingService — Backend Interaction Layer

**Files:**
- Create: `app/services/staking.py`
- Create: `tests/test_staking_service.py`

**Step 1: Write failing tests**

```python
# tests/test_staking_service.py
import pytest
from unittest.mock import patch, MagicMock
from app.models import User, StakeRecord, TrustTier, StakePurpose, UserRole
from app.services.staking import (
    stake_for_arbiter, stake_for_credit, check_and_slash, unstake,
)


def test_stake_for_arbiter_success(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(
        nickname="arb-stake", wallet="0xARB", role=UserRole.worker,
        trust_score=850.0, trust_tier=TrustTier.S, github_id="gh-arb",
    )
    db.add(user)
    db.commit()

    with patch("app.services.staking.stake_onchain", return_value="0xtx"):
        record = stake_for_arbiter(db, user.id, deadline=0, v=0, r="0x0", s="0x0")

    db.refresh(user)
    assert user.staked_amount == 100.0
    assert user.is_arbiter is True
    assert record.purpose == StakePurpose.arbiter_deposit
    assert record.amount == 100.0
    assert record.tx_hash == "0xtx"


def test_stake_for_arbiter_not_s_tier(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(
        nickname="low-stake", wallet="0xLOW", role=UserRole.worker,
        trust_score=500.0, trust_tier=TrustTier.A,
    )
    db.add(user)
    db.commit()

    with pytest.raises(ValueError, match="S-tier"):
        stake_for_arbiter(db, user.id, deadline=0, v=0, r="0x0", s="0x0")


def test_stake_for_arbiter_no_github(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(
        nickname="no-gh", wallet="0xNOGH", role=UserRole.worker,
        trust_score=850.0, trust_tier=TrustTier.S,
    )
    db.add(user)
    db.commit()

    with pytest.raises(ValueError, match="GitHub"):
        stake_for_arbiter(db, user.id, deadline=0, v=0, r="0x0", s="0x0")


def test_stake_for_credit(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(nickname="credit-stake", wallet="0xCRD", role=UserRole.worker)
    db.add(user)
    db.commit()

    with patch("app.services.staking.stake_onchain", return_value="0xtx2"):
        record = stake_for_credit(db, user.id, amount=50.0,
                                  deadline=0, v=0, r="0x0", s="0x0")

    db.refresh(user)
    assert user.staked_amount == 50.0
    assert user.stake_bonus == 50.0
    assert user.trust_score == 550.0  # 500 + 50
    assert record.purpose == StakePurpose.credit_recharge


def test_stake_for_credit_cap(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(
        nickname="cap-stake", wallet="0xCAP", role=UserRole.worker,
        stake_bonus=80.0,
    )
    db.add(user)
    db.commit()

    with patch("app.services.staking.stake_onchain", return_value="0xtx3"):
        record = stake_for_credit(db, user.id, amount=50.0,
                                  deadline=0, v=0, r="0x0", s="0x0")

    db.refresh(user)
    # Only +20 remaining cap (100 - 80 = 20), but paid 50 USDC
    assert user.stake_bonus == 100.0
    assert user.staked_amount == 50.0


def test_check_and_slash(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(
        nickname="slash-me", wallet="0xSLASH", role=UserRole.worker,
        trust_score=250.0, trust_tier=TrustTier.C,
        staked_amount=100.0, stake_bonus=50.0, is_arbiter=True,
    )
    db.add(user)
    db.commit()

    with patch("app.services.staking.slash_onchain", return_value="0xslash"):
        slashed = check_and_slash(db, user.id)

    assert slashed is True
    db.refresh(user)
    assert user.staked_amount == 0.0
    assert user.stake_bonus == 0.0
    assert user.is_arbiter is False


def test_check_and_slash_no_stake(client):
    db = next(iter(client.app.dependency_overrides.values()))()
    user = User(
        nickname="no-stake", wallet="0xNOS", role=UserRole.worker,
        trust_score=250.0, trust_tier=TrustTier.C,
    )
    db.add(user)
    db.commit()

    slashed = check_and_slash(db, user.id)
    assert slashed is False
```

**Step 2: Run tests to verify failures**

Run: `pytest tests/test_staking_service.py -v`
Expected: ImportError

**Step 3: Implement StakingService**

```python
# app/services/staking.py
import os
import logging
from sqlalchemy.orm import Session
from app.models import User, StakeRecord, StakePurpose, TrustTier
from app.services.trust import apply_event, TrustEventType

logger = logging.getLogger(__name__)

ARBITER_STAKE_AMOUNT = 100.0  # USDC


def stake_onchain(wallet: str, amount: float, deadline: int,
                  v: int, r: str, s: str) -> str:
    """Call StakingVault.stake() on-chain. Returns tx hash."""
    from web3 import Web3
    rpc = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
    w3 = Web3(Web3.HTTPProvider(rpc))
    contract_addr = os.environ.get("STAKING_CONTRACT_ADDRESS", "")
    private_key = os.environ.get("PLATFORM_PRIVATE_KEY", "")

    # Minimal ABI for stake function
    abi = [{
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"},
        ],
        "name": "stake",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }]

    contract = w3.eth.contract(address=contract_addr, abi=abi)
    amount_wei = int(amount * 1e6)
    account = w3.eth.account.from_key(private_key)

    tx = contract.functions.stake(
        wallet, amount_wei, deadline, v,
        bytes.fromhex(r[2:]) if r.startswith("0x") else bytes.fromhex(r),
        bytes.fromhex(s[2:]) if s.startswith("0x") else bytes.fromhex(s),
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 200000,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


def slash_onchain(wallet: str) -> str:
    """Call StakingVault.slash() on-chain. Returns tx hash."""
    from web3 import Web3
    rpc = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
    w3 = Web3(Web3.HTTPProvider(rpc))
    contract_addr = os.environ.get("STAKING_CONTRACT_ADDRESS", "")
    private_key = os.environ.get("PLATFORM_PRIVATE_KEY", "")

    abi = [{
        "inputs": [{"name": "user", "type": "address"}],
        "name": "slash",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }]

    contract = w3.eth.contract(address=contract_addr, abi=abi)
    account = w3.eth.account.from_key(private_key)

    tx = contract.functions.slash(wallet).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 200000,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


def stake_for_arbiter(
    db: Session, user_id: str,
    deadline: int, v: int, r: str, s: str,
) -> StakeRecord:
    """Stake 100 USDC for Arbiter registration."""
    user = db.query(User).filter_by(id=user_id).one()

    if user.trust_tier != TrustTier.S:
        raise ValueError("Must be S-tier to become Arbiter")
    if not user.github_id:
        raise ValueError("Must bind GitHub first")
    if user.is_arbiter:
        raise ValueError("Already an Arbiter")

    tx_hash = stake_onchain(user.wallet, ARBITER_STAKE_AMOUNT,
                            deadline, v, r, s)

    user.staked_amount += ARBITER_STAKE_AMOUNT
    user.is_arbiter = True

    record = StakeRecord(
        user_id=user_id,
        amount=ARBITER_STAKE_AMOUNT,
        purpose=StakePurpose.arbiter_deposit,
        tx_hash=tx_hash,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def stake_for_credit(
    db: Session, user_id: str, amount: float,
    deadline: int, v: int, r: str, s: str,
) -> StakeRecord:
    """Stake USDC for credit recharge (+50 per $50, cap +100)."""
    user = db.query(User).filter_by(id=user_id).one()

    tx_hash = stake_onchain(user.wallet, amount, deadline, v, r, s)

    user.staked_amount += amount

    # Apply stake bonus via TrustService
    apply_event(db, user_id, TrustEventType.stake_bonus, stake_amount=amount)

    record = StakeRecord(
        user_id=user_id,
        amount=amount,
        purpose=StakePurpose.credit_recharge,
        tx_hash=tx_hash,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def check_and_slash(db: Session, user_id: str) -> bool:
    """Check if user should be slashed (score < 300 and has stake)."""
    user = db.query(User).filter_by(id=user_id).one()

    if user.trust_score >= 300 or user.staked_amount <= 0:
        return False

    try:
        tx_hash = slash_onchain(user.wallet)
    except Exception as e:
        logger.error(f"Slash on-chain failed for {user_id}: {e}")
        tx_hash = None

    # Apply stake_slash event (removes stake_bonus)
    apply_event(db, user_id, TrustEventType.stake_slash)

    # Record the slash
    record = StakeRecord(
        user_id=user_id,
        amount=user.staked_amount,
        purpose=StakePurpose.arbiter_deposit,
        tx_hash=tx_hash,
        slashed=True,
    )
    db.add(record)

    user.staked_amount = 0.0
    user.stake_bonus = 0.0
    user.is_arbiter = False

    db.commit()
    return True


def unstake(db: Session, user_id: str, amount: float) -> StakeRecord:
    """Unstake USDC from the vault."""
    user = db.query(User).filter_by(id=user_id).one()
    if user.staked_amount < amount:
        raise ValueError("Insufficient staked amount")

    from web3 import Web3
    rpc = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
    w3 = Web3(Web3.HTTPProvider(rpc))
    contract_addr = os.environ.get("STAKING_CONTRACT_ADDRESS", "")
    private_key = os.environ.get("PLATFORM_PRIVATE_KEY", "")

    abi = [{
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "unstake",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }]

    contract = w3.eth.contract(address=contract_addr, abi=abi)
    amount_wei = int(amount * 1e6)
    account = w3.eth.account.from_key(private_key)

    tx = contract.functions.unstake(user.wallet, amount_wei).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 200000,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    user.staked_amount -= amount
    # If arbiter and staked below 100, revoke
    if user.is_arbiter and user.staked_amount < ARBITER_STAKE_AMOUNT:
        user.is_arbiter = False

    record = StakeRecord(
        user_id=user_id,
        amount=amount,
        purpose=StakePurpose.credit_recharge,
        tx_hash=tx_hash.hex(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
```

**Step 4: Run tests**

Run: `pytest tests/test_staking_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/services/staking.py tests/test_staking_service.py
git commit -m "feat(trust): implement StakingService with arbiter deposit, credit recharge, and slash"
```

---

## Task 7: Trust & Auth API Routers

**Files:**
- Create: `app/routers/trust.py`
- Create: `app/routers/auth.py`
- Modify: `app/main.py` (register new routers)
- Create: `tests/test_trust_api.py`

**Step 1: Write failing API tests**

```python
# tests/test_trust_api.py
from unittest.mock import patch, MagicMock
from app.models import User, UserRole, TrustTier


def test_get_trust_profile(client):
    resp = client.post("/users", json={
        "nickname": "trust-user", "wallet": "0xTRUST", "role": "worker"
    })
    user_id = resp.json()["id"]

    resp = client.get(f"/users/{user_id}/trust")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trust_score"] == 500.0
    assert data["trust_tier"] == "A"
    assert data["challenge_deposit_rate"] == 0.10
    assert data["platform_fee_rate"] == 0.20
    assert data["can_accept_tasks"] is True
    assert data["can_challenge"] is True


def test_trust_quote(client):
    resp = client.post("/users", json={
        "nickname": "quote-user", "wallet": "0xQUOTE", "role": "worker"
    })
    user_id = resp.json()["id"]

    resp = client.get(f"/trust/quote?user_id={user_id}&bounty=100")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trust_tier"] == "A"
    assert data["challenge_deposit_rate"] == 0.10
    assert data["challenge_deposit_amount"] == 10.0  # 100 * 0.10
    assert data["service_fee"] == 0.01


def test_get_trust_events(client):
    # Create user, bind github (mocked), check events
    resp = client.post("/users", json={
        "nickname": "events-user", "wallet": "0xEVT", "role": "worker"
    })
    user_id = resp.json()["id"]

    # Manually apply an event via internal mechanism
    from app.database import SessionLocal
    from app.services.trust import apply_event, TrustEventType
    # We'll test the events endpoint after applying events via the service
    # For now, just verify the endpoint returns empty list
    resp = client.get(f"/users/{user_id}/trust/events")
    assert resp.status_code == 200
    assert resp.json() == []
```

**Step 2: Run to verify failures**

Run: `pytest tests/test_trust_api.py -v`
Expected: 404 — routes not registered

**Step 3: Implement trust router**

```python
# app/routers/trust.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, TrustEvent
from app.schemas import TrustProfile, TrustQuote, TrustEventOut
from app.services.trust import (
    get_challenge_deposit_rate, get_platform_fee_rate, check_permissions,
)

router = APIRouter()


@router.get("/users/{user_id}/trust", response_model=TrustProfile)
def get_trust_profile(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    perms = check_permissions(user)

    try:
        deposit_rate = get_challenge_deposit_rate(user.trust_tier)
    except ValueError:
        deposit_rate = 0.0
    try:
        fee_rate = get_platform_fee_rate(user.trust_tier)
    except ValueError:
        fee_rate = 0.0

    return TrustProfile(
        trust_score=user.trust_score,
        trust_tier=user.trust_tier,
        challenge_deposit_rate=deposit_rate,
        platform_fee_rate=fee_rate,
        can_accept_tasks=perms["can_accept_tasks"],
        can_challenge=perms["can_challenge"],
        max_task_amount=perms["max_task_amount"],
        is_arbiter=user.is_arbiter,
        github_bound=user.github_id is not None,
        staked_amount=user.staked_amount,
        stake_bonus=user.stake_bonus,
        consolation_total=user.consolation_total,
    )


@router.get("/trust/quote", response_model=TrustQuote)
def trust_quote(
    user_id: str = Query(...),
    bounty: float = Query(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    try:
        deposit_rate = get_challenge_deposit_rate(user.trust_tier)
        fee_rate = get_platform_fee_rate(user.trust_tier)
    except ValueError:
        raise HTTPException(403, "User tier does not allow this action")

    return TrustQuote(
        trust_tier=user.trust_tier,
        challenge_deposit_rate=deposit_rate,
        challenge_deposit_amount=bounty * deposit_rate,
        platform_fee_rate=fee_rate,
        service_fee=0.01,
    )


@router.get("/users/{user_id}/trust/events", response_model=list[TrustEventOut])
def get_trust_events(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    events = (
        db.query(TrustEvent)
        .filter_by(user_id=user_id)
        .order_by(TrustEvent.created_at.desc())
        .limit(100)
        .all()
    )
    return events
```

**Step 4: Implement auth router (GitHub OAuth)**

```python
# app/routers/auth.py
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.services.trust import apply_event, TrustEventType

router = APIRouter(prefix="/auth")

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.environ.get("GITHUB_REDIRECT_URI",
                                      "http://localhost:8000/auth/github/callback")


@router.get("/github")
def github_login(user_id: str = Query(...)):
    """Redirect to GitHub OAuth authorization page."""
    if not GITHUB_CLIENT_ID:
        raise HTTPException(500, "GitHub OAuth not configured")
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope=read:user"
        f"&state={user_id}"
    )
    return RedirectResponse(url)


@router.get("/github/callback")
def github_callback(
    code: str = Query(...),
    state: str = Query(...),  # user_id
    db: Session = Depends(get_db),
):
    """Handle GitHub OAuth callback, bind GitHub and award +50 trust."""
    user_id = state
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.github_bonus_claimed:
        raise HTTPException(400, "GitHub already bound")

    # Exchange code for access token
    resp = httpx.post(
        "https://github.com/login/oauth/access_token",
        json={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
        },
        headers={"Accept": "application/json"},
    )
    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(400, "Failed to get GitHub token")

    # Fetch GitHub user info
    gh_resp = httpx.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    gh_user = gh_resp.json()
    github_id = str(gh_user.get("id", ""))
    if not github_id:
        raise HTTPException(400, "Failed to get GitHub user")

    # Check if this GitHub ID is already bound to another user
    existing = db.query(User).filter_by(github_id=github_id).first()
    if existing and existing.id != user_id:
        raise HTTPException(400, "GitHub account already bound to another user")

    user.github_id = github_id
    user.github_bonus_claimed = True
    apply_event(db, user_id, TrustEventType.github_bind)

    # Redirect to frontend
    return RedirectResponse(f"http://localhost:3000/tasks?github_bound=true")
```

**Step 5: Register routers in main.py**

In `app/main.py`, add after existing router includes:

```python
from app.routers import trust as trust_router_module
from app.routers import auth as auth_router_module

# In the app setup section:
app.include_router(trust_router_module.router)
app.include_router(auth_router_module.router)
```

**Step 6: Run tests**

Run: `pytest tests/test_trust_api.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add app/routers/trust.py app/routers/auth.py app/main.py tests/test_trust_api.py
git commit -m "feat(trust): add trust profile, quote, events API and GitHub OAuth endpoints"
```

---

## Task 8: Arbiter Voting API

**Files:**
- Modify: `app/routers/trust.py` (add vote endpoints)
- Create: `tests/test_arbiter_voting_api.py`

**Step 1: Write failing tests**

```python
# tests/test_arbiter_voting_api.py
from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict,
)


def _setup_challenge_with_jury(client):
    """Create a full scenario with task, challenge, and jury votes."""
    db = next(iter(client.app.dependency_overrides.values()))()

    pub = User(nickname="pub-v", wallet="0xPV", role=UserRole.publisher)
    worker = User(nickname="wrk-v", wallet="0xWV", role=UserRole.worker)
    challenger = User(nickname="chl-v", wallet="0xCV", role=UserRole.worker)
    db.add_all([pub, worker, challenger])
    db.commit()

    task = Task(
        title="Vote Test", description="Test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating, publisher_id=pub.id,
        bounty=100.0, challenge_duration=7200,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=worker.id,
                       content="w", score=0.9, status="scored")
    c_sub = Submission(task_id=task.id, worker_id=challenger.id,
                       content="c", score=0.7, status="scored")
    db.add_all([w_sub, c_sub])
    db.commit()

    task.winner_submission_id = w_sub.id

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Mine is better",
        status=ChallengeStatus.pending, challenger_wallet="0xCV",
    )
    db.add(ch)
    db.commit()

    # Create 3 arbiter users and their vote records
    arbs = []
    votes = []
    for i in range(3):
        a = User(
            nickname=f"arb-v{i}", wallet=f"0xAV{i}", role=UserRole.worker,
            trust_score=850.0, trust_tier=TrustTier.S,
            is_arbiter=True, staked_amount=100.0, github_id=f"gh-v{i}",
        )
        db.add(a)
        db.commit()
        arbs.append(a)

        v = ArbiterVote(challenge_id=ch.id, arbiter_user_id=a.id)
        db.add(v)
        votes.append(v)

    db.commit()
    for v in votes:
        db.refresh(v)

    return task, ch, arbs, votes


def test_get_challenge_votes(client):
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    resp = client.get(f"/challenges/{ch.id}/votes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all(v["vote"] is None for v in data)


def test_submit_vote(client):
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    resp = client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": arbs[0].id,
        "verdict": "upheld",
        "feedback": "The challenger is correct, their work is superior.",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["vote"] == "upheld"
    assert data["feedback"] is not None


def test_submit_vote_not_arbiter(client):
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    resp = client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": "nonexistent-id",
        "verdict": "upheld",
        "feedback": "some feedback",
    })
    assert resp.status_code == 404


def test_submit_vote_duplicate(client):
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": arbs[0].id,
        "verdict": "upheld",
        "feedback": "first vote",
    })
    resp = client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": arbs[0].id,
        "verdict": "rejected",
        "feedback": "second vote",
    })
    assert resp.status_code == 400
```

**Step 2: Run tests to verify failures**

Run: `pytest tests/test_arbiter_voting_api.py -v`
Expected: 404

**Step 3: Add vote endpoints to trust router**

Add to `app/routers/trust.py`:

```python
from app.models import ArbiterVote, Challenge, ChallengeVerdict
from app.schemas import ArbiterVoteOut, ArbiterVoteCreate


@router.get("/challenges/{challenge_id}/votes", response_model=list[ArbiterVoteOut])
def get_challenge_votes(challenge_id: str, db: Session = Depends(get_db)):
    challenge = db.query(Challenge).filter_by(id=challenge_id).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")
    votes = db.query(ArbiterVote).filter_by(challenge_id=challenge_id).all()
    return votes


@router.post("/challenges/{challenge_id}/vote", response_model=ArbiterVoteOut)
def submit_arbiter_vote(
    challenge_id: str,
    body: dict,  # {arbiter_user_id, verdict, feedback}
    db: Session = Depends(get_db),
):
    arbiter_user_id = body.get("arbiter_user_id")
    verdict_str = body.get("verdict")
    feedback = body.get("feedback")

    if not feedback:
        raise HTTPException(400, "Feedback is required")

    vote = (
        db.query(ArbiterVote)
        .filter_by(challenge_id=challenge_id, arbiter_user_id=arbiter_user_id)
        .first()
    )
    if not vote:
        raise HTTPException(404, "Vote record not found for this arbiter")
    if vote.vote is not None:
        raise HTTPException(400, "Already voted")

    vote.vote = ChallengeVerdict(verdict_str)
    vote.feedback = feedback
    db.commit()
    db.refresh(vote)
    return vote
```

**Step 4: Run tests**

Run: `pytest tests/test_arbiter_voting_api.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/routers/trust.py tests/test_arbiter_voting_api.py
git commit -m "feat(trust): add arbiter voting API endpoints"
```

---

## Task 9: Modify Existing Endpoints for Dynamic Fees & Permissions

**Files:**
- Modify: `app/routers/challenges.py` (dynamic deposit, C-level block)
- Modify: `app/routers/submissions.py` (C-level block, B-level cap)
- Modify: `app/routers/tasks.py` (dynamic fee rate)
- Modify: `app/routers/users.py` (return trust fields)
- Modify: `tests/test_challenge_api.py`
- Modify: `tests/test_submissions.py`

**Step 1: Write failing tests for permission checks**

Add to existing test files or create `tests/test_trust_permissions.py`:

```python
# tests/test_trust_permissions.py
from unittest.mock import patch
from app.models import User, Task, Submission, UserRole, TaskType, TrustTier
from datetime import datetime, timezone, timedelta


def _create_quality_task(client, bounty=100.0):
    """Helper: create publisher, quality_first task in challenge_window."""
    db = next(iter(client.app.dependency_overrides.values()))()
    pub = User(nickname="perm-pub", wallet="0xPPUB", role=UserRole.publisher)
    db.add(pub)
    db.commit()

    PAYMENT_MOCK = patch("app.routers.tasks.verify_payment",
                         return_value={"valid": True, "tx_hash": "0xtest"})
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "Perm Test", "description": "test",
            "type": "quality_first",
            "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "publisher_id": pub.id,
            "bounty": bounty,
        }, headers={"X-PAYMENT": "test"})
    return resp.json()["id"], pub, db


def test_c_level_cannot_submit(client):
    """C-level user cannot submit to tasks."""
    task_id, pub, db = _create_quality_task(client)

    banned = User(
        nickname="banned-wrk", wallet="0xBAN", role=UserRole.worker,
        trust_score=100.0, trust_tier=TrustTier.C,
    )
    db.add(banned)
    db.commit()

    resp = client.post(f"/tasks/{task_id}/submissions", json={
        "worker_id": banned.id, "content": "attempt",
    })
    assert resp.status_code == 403


def test_b_level_bounty_cap(client):
    """B-level user cannot accept tasks with bounty > 50 USDC."""
    task_id, pub, db = _create_quality_task(client, bounty=100.0)

    warning_user = User(
        nickname="warning-wrk", wallet="0xWARN", role=UserRole.worker,
        trust_score=400.0, trust_tier=TrustTier.B,
    )
    db.add(warning_user)
    db.commit()

    resp = client.post(f"/tasks/{task_id}/submissions", json={
        "worker_id": warning_user.id, "content": "attempt",
    })
    assert resp.status_code == 403
```

**Step 2: Run tests to verify failures**

Run: `pytest tests/test_trust_permissions.py -v`
Expected: 201 (no permission check yet, should be 403)

**Step 3: Add permission checks to submissions router**

In `app/routers/submissions.py`, after task existence check, add:

```python
from app.models import User
from app.services.trust import check_permissions

# Inside create_submission, after task validation:
worker = db.query(User).filter_by(id=body.worker_id).first()
if worker:
    perms = check_permissions(worker)
    if not perms["can_accept_tasks"]:
        raise HTTPException(403, "Your trust level does not allow accepting tasks")
    if perms["max_task_amount"] and task.bounty and task.bounty > perms["max_task_amount"]:
        raise HTTPException(403, f"Your trust level limits tasks to {perms['max_task_amount']} USDC")
```

**Step 4: Add dynamic deposit to challenges router**

In `app/routers/challenges.py`, modify deposit calculation to use trust tier:

```python
from app.services.trust import get_challenge_deposit_rate, check_permissions

# Inside create_challenge, before balance check:
challenger_sub = db.query(Submission).filter_by(id=body.challenger_submission_id).first()
if challenger_sub:
    challenger_user = db.query(User).filter_by(id=challenger_sub.worker_id).first()
    if challenger_user:
        perms = check_permissions(challenger_user)
        if not perms["can_challenge"]:
            raise HTTPException(403, "Your trust level does not allow challenges")
        try:
            deposit_rate = get_challenge_deposit_rate(challenger_user.trust_tier)
        except ValueError:
            raise HTTPException(403, "Your trust level does not allow challenges")
        # Override deposit amount with dynamic rate
        deposit_amount = task.bounty * deposit_rate if task.bounty else 0
```

**Step 5: Run all tests**

Run: `pytest -v`
Expected: All pass (existing tests may need fixture adjustments for new User fields)

**Step 6: Commit**

```bash
git add app/routers/submissions.py app/routers/challenges.py app/routers/tasks.py tests/
git commit -m "feat(trust): add dynamic fees and permission checks to existing endpoints"
```

---

## Task 10: Scheduler — Arbiter Voting Check & Trust Settlement

**Files:**
- Modify: `app/scheduler.py` (replace direct arbitration with jury flow)
- Modify: `tests/test_scheduler.py`
- Create: `tests/test_trust_settlement.py`

**Step 1: Write failing tests for jury-based arbitration flow**

```python
# tests/test_trust_settlement.py
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict, TrustEvent, TrustEventType,
)


def test_scheduler_selects_jury_on_arbitrating(client):
    """When task enters arbitrating, scheduler selects jury."""
    db = next(iter(client.app.dependency_overrides.values()))()

    # Setup: create arbiters
    for i in range(3):
        a = User(
            nickname=f"sched-arb{i}", wallet=f"0xSA{i}", role=UserRole.worker,
            trust_score=850.0, trust_tier=TrustTier.S,
            is_arbiter=True, staked_amount=100.0, github_id=f"gh-sa{i}",
        )
        db.add(a)

    pub = User(nickname="sched-pub", wallet="0xSP", role=UserRole.publisher)
    wrk = User(nickname="sched-wrk", wallet="0xSW", role=UserRole.worker)
    db.add_all([pub, wrk])
    db.commit()

    task = Task(
        title="Sched Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.challenge_window,
        challenge_window_end=datetime.now(timezone.utc) - timedelta(minutes=1),
        publisher_id=pub.id, bounty=100.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=wrk.id,
                       content="w", score=0.9, status="scored")
    db.add(w_sub)
    db.commit()
    task.winner_submission_id = w_sub.id

    chl_user = User(nickname="sched-chl", wallet="0xSC", role=UserRole.worker)
    db.add(chl_user)
    db.commit()
    c_sub = Submission(task_id=task.id, worker_id=chl_user.id,
                       content="c", score=0.7, status="scored")
    db.add(c_sub)
    db.commit()

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Better",
        status=ChallengeStatus.pending, challenger_wallet="0xSC",
    )
    db.add(ch)
    db.commit()

    # Run scheduler phase 3
    from app.scheduler import quality_first_lifecycle
    with patch("app.scheduler.create_challenge_onchain", return_value="0x"):
        with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
            quality_first_lifecycle(db)

    # Task should be in arbitrating state with jury selected
    db.refresh(task)
    assert task.status == TaskStatus.arbitrating

    votes = db.query(ArbiterVote).filter_by(challenge_id=ch.id).all()
    assert len(votes) == 3


def test_scheduler_resolves_after_all_votes(client):
    """After all 3 arbiter votes, scheduler resolves the challenge."""
    db = next(iter(client.app.dependency_overrides.values()))()

    # Setup full scenario with all votes submitted
    # (This test verifies the scheduler detects completed voting and settles)
    pass  # Detailed implementation follows the pattern above
```

**Step 2: Modify scheduler.py — Phase 3 and Phase 4**

Replace the direct `run_arbitration()` call in Phase 3 with jury selection:

```python
# In scheduler.py, Phase 3 (challenge_window → arbitrating):
# Replace: run_arbitration(db, task.id)
# With:
from app.services.arbiter_pool import select_jury, resolve_jury, check_jury_ready
from app.services.trust import apply_event, TrustEventType

# Phase 3: select jury
votes = select_jury(db, task.id)
if not votes:
    # Fallback to stub arbiter
    run_arbitration(db, task.id)
else:
    task.status = TaskStatus.arbitrating
    # Set arbiter deadline (6 hours)
    # Store in task or new field
    db.commit()

# Phase 4: check if voting complete
for task in arbitrating_tasks:
    challenges = db.query(Challenge).filter_by(task_id=task.id, status=ChallengeStatus.pending).all()
    all_ready = True
    for ch in challenges:
        if not check_jury_ready(db, ch.id):
            # Check 6h timeout
            votes = db.query(ArbiterVote).filter_by(challenge_id=ch.id).all()
            if votes and (datetime.now(timezone.utc) - votes[0].created_at).total_seconds() > 6 * 3600:
                # Timeout: mark non-voters as timeout, resolve with existing votes
                for v in votes:
                    if v.vote is None:
                        apply_event(db, v.arbiter_user_id, TrustEventType.arbiter_timeout)
                verdict = resolve_jury(db, ch.id)
                _apply_verdict_trust(db, ch, verdict, task)
            else:
                all_ready = False
        else:
            verdict = resolve_jury(db, ch.id)
            _apply_verdict_trust(db, ch, verdict, task)

    if all_ready:
        _settle_after_arbitration(db, task)
```

**Step 3: Implement _apply_verdict_trust helper**

```python
def _apply_verdict_trust(db, challenge, verdict, task):
    """Apply trust score changes based on jury verdict."""
    # Majority arbiters: +2
    # Minority arbiters: -15
    votes = db.query(ArbiterVote).filter_by(challenge_id=challenge.id).all()
    for v in votes:
        if v.vote is not None:
            if v.is_majority:
                apply_event(db, v.arbiter_user_id, TrustEventType.arbiter_majority,
                            task_id=task.id)
            else:
                apply_event(db, v.arbiter_user_id, TrustEventType.arbiter_minority,
                            task_id=task.id)

    # Update challenge verdict
    challenge.verdict = verdict
    challenge.status = ChallengeStatus.judged
    db.commit()
```

**Step 4: Run tests**

Run: `pytest tests/test_trust_settlement.py -v && pytest tests/test_scheduler.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/scheduler.py tests/test_trust_settlement.py tests/test_scheduler.py
git commit -m "feat(trust): integrate jury voting into scheduler lifecycle"
```

---

## Task 11: Weekly Leaderboard

**Files:**
- Modify: `app/scheduler.py` (add weekly cron job)
- Create: `tests/test_weekly_leaderboard.py`

**Step 1: Write failing test**

```python
# tests/test_weekly_leaderboard.py
from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, UserRole, TaskType, TaskStatus,
    TrustTier, TrustEvent, TrustEventType,
)


def test_weekly_leaderboard_awards(client):
    db = next(iter(client.app.dependency_overrides.values()))()

    # Create 5 workers with varying settled amounts
    workers = []
    for i in range(5):
        w = User(nickname=f"lb-{i}", wallet=f"0xLB{i}", role=UserRole.worker)
        db.add(w)
        db.commit()
        workers.append(w)

    # Create closed tasks with different bounties
    for i, (worker, bounty) in enumerate(zip(workers, [100, 80, 60, 40, 20])):
        task = Task(
            title=f"LB Task {i}", description="test",
            type=TaskType.quality_first,
            deadline=datetime.now(timezone.utc) - timedelta(days=1),
            status=TaskStatus.closed,
            publisher_id=workers[0].id,
            bounty=bounty, payout_amount=bounty * 0.8,
            winner_submission_id=f"sub-{i}",
        )
        db.add(task)
    db.commit()

    from app.scheduler import run_weekly_leaderboard
    run_weekly_leaderboard(db)

    # Top 3 should get +30
    db.refresh(workers[0])
    events = db.query(TrustEvent).filter_by(
        user_id=workers[0].id,
        event_type=TrustEventType.weekly_leaderboard,
    ).all()
    assert len(events) == 1
    assert events[0].delta == 30.0
```

**Step 2: Implement run_weekly_leaderboard**

```python
# In app/scheduler.py
from app.services.trust import apply_event, TrustEventType

LEADERBOARD_TIERS = [
    (3, 30),    # Top 1-3: +30
    (10, 20),   # Top 4-10: +20
    (30, 15),   # Top 11-30: +15
    (100, 10),  # Top 31-100: +10
]


def run_weekly_leaderboard(db=None):
    """Weekly leaderboard: award trust points to top workers."""
    if db is None:
        db = SessionLocal()

    # Get all closed tasks from this week
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # Aggregate settled amounts per winner worker
    from sqlalchemy import func
    from app.models import Task, Submission, User

    results = (
        db.query(
            Submission.worker_id,
            func.sum(Task.payout_amount).label("total"),
        )
        .join(Task, Task.winner_submission_id == Submission.id)
        .filter(Task.status == TaskStatus.closed)
        .filter(Task.created_at >= week_ago)
        .filter(Task.payout_amount.isnot(None))
        .group_by(Submission.worker_id)
        .order_by(func.sum(Task.payout_amount).desc())
        .limit(100)
        .all()
    )

    rank = 0
    for worker_id, total in results:
        rank += 1
        bonus = 0
        for threshold, points in LEADERBOARD_TIERS:
            if rank <= threshold:
                bonus = points
                break
        if bonus > 0:
            apply_event(
                db, worker_id, TrustEventType.weekly_leaderboard,
                leaderboard_bonus=bonus,
            )
```

Add to `create_scheduler()`:

```python
scheduler.add_job(
    run_weekly_leaderboard, "cron",
    day_of_week="sun", hour=0, minute=0,
    id="weekly_leaderboard",
)
```

**Step 3: Run tests**

Run: `pytest tests/test_weekly_leaderboard.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add app/scheduler.py tests/test_weekly_leaderboard.py
git commit -m "feat(trust): implement weekly leaderboard with tiered trust bonuses"
```

---

## Task 12: Integration — Update _settle_after_arbitration for Trust Scoring

**Files:**
- Modify: `app/scheduler.py` (update _settle_after_arbitration)
- Modify: `tests/test_challenge_integration.py`

**Step 1: Write failing integration test**

```python
# Add to tests/test_challenge_integration.py or create tests/test_trust_integration.py

def test_full_trust_settlement_flow(client):
    """End-to-end: task → challenge → jury vote → trust scores applied."""
    # Setup task, submissions, challenge, jury
    # All 3 arbiters vote "upheld"
    # Verify:
    #   - Winner worker: no trust change (challenged, 0 points per spec)
    #   - Challenger: +10 * M points (challenger_won)
    #   - Majority arbiters: +2 each
    #   - Challenge verdict = upheld
    pass  # Full implementation follows existing integration test patterns
```

**Step 2: Update _settle_after_arbitration**

Replace the direct `credit_score += 5` logic with TrustService calls:

```python
# In _settle_after_arbitration, replace credit score updates with:
from app.services.trust import apply_event, TrustEventType
from app.services.staking import check_and_slash

for ch in challenges:
    if ch.verdict == ChallengeVerdict.upheld:
        # Challenger wins
        challenger_sub = db.query(Submission).filter_by(id=ch.challenger_submission_id).first()
        if challenger_sub:
            apply_event(db, challenger_sub.worker_id, TrustEventType.challenger_won,
                        task_bounty=task.bounty, task_id=task.id)
    elif ch.verdict == ChallengeVerdict.malicious:
        challenger_sub = db.query(Submission).filter_by(id=ch.challenger_submission_id).first()
        if challenger_sub:
            apply_event(db, challenger_sub.worker_id, TrustEventType.challenger_malicious,
                        task_id=task.id)
            check_and_slash(db, challenger_sub.worker_id)

# Winner gets worker_won if they survive
if not any_upheld:
    winner_sub = db.query(Submission).filter_by(id=task.winner_submission_id).first()
    if winner_sub:
        apply_event(db, winner_sub.worker_id, TrustEventType.worker_won,
                    task_bounty=task.bounty, task_id=task.id)
```

**Step 3: Run all tests**

Run: `pytest -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add app/scheduler.py tests/
git commit -m "feat(trust): integrate trust scoring into settlement flow"
```

---

## Task 13: Final Cleanup — Update UserOut Schema, Existing Tests, Documentation

**Files:**
- Modify: `app/schemas.py` (ensure all new fields in UserOut)
- Modify: `tests/*.py` (fix any remaining test failures from credit_score → trust_score)
- Modify: `docs/project-overview.md` (add V10 Claw Trust section)

**Step 1: Run full test suite**

Run: `pytest -v && cd frontend && npm test`
Expected: Identify any remaining failures

**Step 2: Fix all failures**

Common fixes:
- Replace all `credit_score` references with `trust_score`
- Update default value expectations (100 → 500)
- Mock `check_and_slash` in settlement tests
- Ensure new models are created in conftest.py (`Base.metadata.create_all`)

**Step 3: Update project-overview.md**

Add to section 十二 (后续规划):
```markdown
- [x] **V10**: Claw Trust 信誉分机制（对数加权算分、S/A/B/C 四级动态费率、3 人陪审团、StakingVault 质押/Slash、GitHub OAuth 绑定、周榜）
```

**Step 4: Run full test suite again**

Run: `pytest -v`
Expected: All PASS (target: 120+ tests)

**Step 5: Commit**

```bash
git add -A
git commit -m "feat(trust): complete Claw Trust V10 — cleanup, docs, and test fixes"
```

---

## Summary of New/Modified Files

| File | Action | Description |
|------|--------|-------------|
| `app/models.py` | Modify | Add TrustTier, TrustEventType, StakePurpose enums; modify User; add TrustEvent, ArbiterVote, StakeRecord |
| `app/schemas.py` | Modify | Update UserOut; add TrustProfile, TrustEventOut, ArbiterVoteCreate/Out, StakeRequest, TrustQuote, WeeklyLeaderboardEntry |
| `app/services/trust.py` | Create | TrustService — scoring engine, multiplier, tiers, fees, permissions |
| `app/services/arbiter_pool.py` | Create | ArbiterPoolService — jury selection, voting, resolution |
| `app/services/staking.py` | Create | StakingService — stake, unstake, slash on-chain interaction |
| `app/routers/trust.py` | Create | Trust profile, quote, events, arbiter voting API |
| `app/routers/auth.py` | Create | GitHub OAuth login/callback |
| `app/routers/challenges.py` | Modify | Dynamic deposit rate, C-level block |
| `app/routers/submissions.py` | Modify | C-level block, B-level bounty cap |
| `app/routers/tasks.py` | Modify | Dynamic platform fee rate |
| `app/main.py` | Modify | Register trust + auth routers |
| `app/scheduler.py` | Modify | Jury voting check, trust settlement, weekly leaderboard |
| `contracts/src/StakingVault.sol` | Create | Staking vault contract |
| `contracts/test/StakingVault.t.sol` | Create | Foundry tests |
| `tests/test_trust_models.py` | Create | Model tests |
| `tests/test_trust_service.py` | Create | TrustService tests |
| `tests/test_arbiter_pool.py` | Create | ArbiterPoolService tests |
| `tests/test_staking_service.py` | Create | StakingService tests |
| `tests/test_trust_api.py` | Create | Trust API tests |
| `tests/test_arbiter_voting_api.py` | Create | Arbiter voting API tests |
| `tests/test_trust_permissions.py` | Create | Permission check tests |
| `tests/test_trust_settlement.py` | Create | Scheduler integration tests |
| `tests/test_weekly_leaderboard.py` | Create | Weekly leaderboard tests |
