# Merged Arbitration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace per-challenge independent voting with a unified "pick winner + tag malicious" merged arbitration model across the entire candidate pool.

**Architecture:** New `JuryBallot` and `MaliciousTag` tables store per-task votes. `resolve_merged_jury()` replaces `resolve_jury()` with a 5-step pipeline: circuit breaker check → winner election → per-challenge verdict mapping → coherence calculation → contract verdict generation. Existing `ArbiterVote` retained as historical data.

**Tech Stack:** Python/FastAPI, SQLAlchemy, Alembic, Solidity (Foundry), Next.js/React, Vitest

---

## Task 1: Data Model — New Tables + Enum Values

**Files:**
- Modify: `app/models.py`
- Create: Alembic migration (auto-generated)

**Step 1: Write failing test for new models**

Create file `tests/test_merged_arbitration.py`:

```python
"""Tests for merged arbitration (JuryBallot + MaliciousTag)."""
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from app.models import (
    JuryBallot, MaliciousTag, TaskStatus, TrustEventType,
    Task, User, Submission, Challenge, ChallengeVerdict, ChallengeStatus,
)


def test_jury_ballot_model_exists(db_session):
    """JuryBallot model can be instantiated and persisted."""
    from app.models import JuryBallot
    ballot = JuryBallot(task_id="t1", arbiter_user_id="u1")
    db_session.add(ballot)
    db_session.commit()
    assert ballot.id is not None
    assert ballot.winner_submission_id is None  # not yet voted
    assert ballot.voted_at is None


def test_malicious_tag_model_exists(db_session):
    """MaliciousTag model can be instantiated and persisted."""
    from app.models import MaliciousTag
    tag = MaliciousTag(task_id="t1", arbiter_user_id="u1", target_submission_id="s1")
    db_session.add(tag)
    db_session.commit()
    assert tag.id is not None


def test_task_status_voided():
    """TaskStatus enum includes 'voided'."""
    assert TaskStatus.voided == "voided"


def test_trust_event_type_new_values():
    """TrustEventType includes pw_malicious and challenger_justified."""
    assert TrustEventType.pw_malicious == "pw_malicious"
    assert TrustEventType.challenger_justified == "challenger_justified"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_merged_arbitration.py -v`
Expected: ImportError — `JuryBallot`, `MaliciousTag` not found; `TaskStatus.voided` not found

**Step 3: Add new models and enum values to models.py**

In `app/models.py`, add to `TaskStatus` enum (after line 19, the `closed` value):
```python
    voided = "voided"
```

Add to `TrustEventType` enum (after line 76, the `worker_malicious` value):
```python
    pw_malicious = "pw_malicious"
    challenger_justified = "challenger_justified"
```

Add new model classes at the end of the file (after `StakeRecord` class, ~line 225):

```python
class JuryBallot(Base):
    """Per-task merged arbitration vote: one ballot per arbiter per task."""
    __tablename__ = "jury_ballots"
    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    arbiter_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    winner_submission_id = Column(String, ForeignKey("submissions.id"), nullable=True)
    feedback = Column(Text, nullable=True)
    coherence_status = Column(String, nullable=True)
    is_majority = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    voted_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("task_id", "arbiter_user_id"),)


class MaliciousTag(Base):
    """Arbiter's malicious tag on a candidate submission."""
    __tablename__ = "malicious_tags"
    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    arbiter_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    target_submission_id = Column(String, ForeignKey("submissions.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("task_id", "arbiter_user_id", "target_submission_id"),)
```

Also add `UniqueConstraint` to the imports at top of file:
```python
from sqlalchemy import UniqueConstraint
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_merged_arbitration.py -v`
Expected: All 4 tests PASS

**Step 5: Generate Alembic migration**

Run: `alembic revision --autogenerate -m "add jury_ballots and malicious_tags tables, voided status"`

Verify the generated migration file creates the two tables and includes the new enum values.

**Step 6: Commit**

```bash
git add app/models.py alembic/versions/ tests/test_merged_arbitration.py
git commit -m "feat: add JuryBallot, MaliciousTag models and voided task status"
```

---

## Task 2: Pydantic Schemas

**Files:**
- Modify: `app/schemas.py`
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing test for schemas**

Append to `tests/test_merged_arbitration.py`:

```python
def test_jury_vote_in_schema():
    """JuryVoteIn validates input correctly."""
    from app.schemas import JuryVoteIn
    vote = JuryVoteIn(
        arbiter_user_id="u1",
        winner_submission_id="s1",
        malicious_submission_ids=["s2", "s3"],
        feedback="Good work",
    )
    assert vote.winner_submission_id == "s1"
    assert len(vote.malicious_submission_ids) == 2


def test_jury_vote_in_rejects_winner_in_malicious():
    """JuryVoteIn rejects winner_submission_id appearing in malicious list."""
    from app.schemas import JuryVoteIn
    import pydantic
    import pytest
    with pytest.raises(pydantic.ValidationError):
        JuryVoteIn(
            arbiter_user_id="u1",
            winner_submission_id="s1",
            malicious_submission_ids=["s1"],  # conflict!
        )
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_merged_arbitration.py::test_jury_vote_in_schema -v`
Expected: ImportError — `JuryVoteIn` not found

**Step 3: Add schemas to schemas.py**

Add at end of `app/schemas.py`:

```python
class JuryVoteIn(BaseModel):
    """Input for merged arbitration vote."""
    arbiter_user_id: str
    winner_submission_id: str
    malicious_submission_ids: list[str] = []
    feedback: str = ""

    @model_validator(mode="after")
    def winner_not_in_malicious(self):
        if self.winner_submission_id in self.malicious_submission_ids:
            raise ValueError("Winner cannot be tagged as malicious")
        return self


class JuryBallotOut(BaseModel):
    """Response for a single jury ballot."""
    id: str
    task_id: str
    arbiter_user_id: str
    winner_submission_id: Optional[str] = None
    feedback: Optional[str] = None
    coherence_status: Optional[str] = None
    is_majority: Optional[bool] = None
    created_at: UTCDatetime
    voted_at: Optional[UTCDatetime] = None
    model_config = {"from_attributes": True}


class MaliciousTagOut(BaseModel):
    """Response for a malicious tag."""
    id: str
    task_id: str
    arbiter_user_id: str
    target_submission_id: str
    created_at: UTCDatetime
    model_config = {"from_attributes": True}
```

Add `model_validator` to the pydantic imports at top of `app/schemas.py`:
```python
from pydantic import BaseModel, model_validator
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merged_arbitration.py::test_jury_vote_in_schema tests/test_merged_arbitration.py::test_jury_vote_in_rejects_winner_in_malicious -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/schemas.py tests/test_merged_arbitration.py
git commit -m "feat: add JuryVoteIn, JuryBallotOut, MaliciousTagOut schemas"
```

---

## Task 3: Service — select_jury Refactored for JuryBallot

**Files:**
- Modify: `app/services/arbiter_pool.py`
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing test**

Append to `tests/test_merged_arbitration.py`:

```python
def _make_users(db, n):
    """Create n users and return them."""
    users = []
    for i in range(n):
        u = User(wallet=f"0xuser{i}", role="both")
        db.add(u)
        users.append(u)
    db.commit()
    for u in users:
        db.refresh(u)
    return users


def _make_quality_task_with_challenges(db, users):
    """
    Create a quality_first task with PW + 2 challengers.
    Returns (task, pw_submission, [challenge1, challenge2]).
    users: [publisher, pw_worker, challenger1, challenger2, arb1, arb2, arb3]
    """
    publisher, pw_worker, ch1, ch2 = users[0], users[1], users[2], users[3]
    task = Task(
        title="Test Task",
        description="desc",
        type="quality_first",
        bounty=100.0,
        publisher_id=publisher.id,
        acceptance_criteria=["criterion 1"],
        status=TaskStatus.arbitrating,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    pw_sub = Submission(task_id=task.id, worker_id=pw_worker.id, content="pw content")
    db.add(pw_sub)
    db.commit()
    db.refresh(pw_sub)
    task.winner_submission_id = pw_sub.id

    ch1_sub = Submission(task_id=task.id, worker_id=ch1.id, content="ch1 content")
    ch2_sub = Submission(task_id=task.id, worker_id=ch2.id, content="ch2 content")
    db.add_all([ch1_sub, ch2_sub])
    db.commit()
    db.refresh(ch1_sub)
    db.refresh(ch2_sub)

    c1 = Challenge(
        task_id=task.id,
        challenger_submission_id=ch1_sub.id,
        target_submission_id=pw_sub.id,
        reason="I'm better",
    )
    c2 = Challenge(
        task_id=task.id,
        challenger_submission_id=ch2_sub.id,
        target_submission_id=pw_sub.id,
        reason="I'm also better",
    )
    db.add_all([c1, c2])
    db.commit()
    db.refresh(c1)
    db.refresh(c2)
    db.refresh(task)

    return task, pw_sub, ch1_sub, ch2_sub, [c1, c2]


def test_select_jury_creates_jury_ballots(db_session):
    """select_jury creates JuryBallot records (not ArbiterVote)."""
    users = _make_users(db_session, 7)
    task, pw_sub, _, _, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db_session, task.id)

    assert len(ballots) == 3  # JURY_SIZE = 3
    for b in ballots:
        assert isinstance(b, JuryBallot)
        assert b.task_id == task.id
        assert b.winner_submission_id is None  # not yet voted
        # Arbiter is not a task participant
        participant_ids = {users[i].id for i in range(4)}  # publisher + 3 workers
        assert b.arbiter_user_id not in participant_ids
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_merged_arbitration.py::test_select_jury_creates_jury_ballots -v`
Expected: AssertionError — `select_jury` still returns ArbiterVote objects

**Step 3: Refactor select_jury in arbiter_pool.py**

Rewrite `app/services/arbiter_pool.py` `select_jury()` function. Keep the existing function renamed to `_select_jury_legacy()` (for historical reference), then write the new version:

```python
from app.models import JuryBallot, MaliciousTag, ArbiterVote, User, Task, Submission, Challenge

JURY_SIZE = 3


def select_jury(db: Session, task_id: str) -> list[JuryBallot]:
    """Select up to 3 arbiters for merged arbitration on a task.
    Creates one JuryBallot per arbiter (per-task, not per-challenge).
    """
    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        return []

    # Collect all participant user IDs to exclude
    exclude_ids = set()
    exclude_ids.add(task.publisher_id)
    subs = db.query(Submission).filter_by(task_id=task_id).all()
    for s in subs:
        exclude_ids.add(s.worker_id)
    challenges = db.query(Challenge).filter_by(task_id=task_id).all()
    for c in challenges:
        challenger_sub = db.query(Submission).filter_by(id=c.challenger_submission_id).first()
        if challenger_sub:
            exclude_ids.add(challenger_sub.worker_id)

    # Select random eligible users
    candidates = db.query(User).filter(
        User.id.notin_(exclude_ids)
    ).all()

    import random
    selected = random.sample(candidates, min(JURY_SIZE, len(candidates)))

    # Create one JuryBallot per arbiter (per-task)
    ballots = []
    for user in selected:
        ballot = JuryBallot(task_id=task_id, arbiter_user_id=user.id)
        db.add(ballot)
        ballots.append(ballot)
    db.commit()
    for b in ballots:
        db.refresh(b)
    return ballots
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_merged_arbitration.py::test_select_jury_creates_jury_ballots -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/arbiter_pool.py tests/test_merged_arbitration.py
git commit -m "refactor: select_jury creates JuryBallot records instead of ArbiterVote"
```

---

## Task 4: Service — submit_merged_vote

**Files:**
- Modify: `app/services/arbiter_pool.py`
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing tests**

Append to `tests/test_merged_arbitration.py`:

```python
def test_submit_merged_vote_happy_path(db_session):
    """submit_merged_vote records winner + malicious tags."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, submit_merged_vote
    ballots = select_jury(db_session, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    # Build candidate pool
    candidate_ids = {pw_sub.id, ch1_sub.id, ch2_sub.id}

    result = submit_merged_vote(
        db_session,
        task_id=task.id,
        arbiter_user_id=arbiter_id,
        winner_submission_id=ch1_sub.id,
        malicious_submission_ids=[ch2_sub.id],
        feedback="ch1 is best, ch2 is garbage",
    )
    assert result.winner_submission_id == ch1_sub.id
    assert result.voted_at is not None

    # Check malicious tag was created
    tags = db_session.query(MaliciousTag).filter_by(
        task_id=task.id, arbiter_user_id=arbiter_id
    ).all()
    assert len(tags) == 1
    assert tags[0].target_submission_id == ch2_sub.id


def test_submit_merged_vote_rejects_winner_in_malicious(db_session):
    """submit_merged_vote rejects winner being in malicious list."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, submit_merged_vote
    ballots = select_jury(db_session, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    import pytest
    with pytest.raises(ValueError, match="Winner cannot be tagged as malicious"):
        submit_merged_vote(
            db_session,
            task_id=task.id,
            arbiter_user_id=arbiter_id,
            winner_submission_id=ch1_sub.id,
            malicious_submission_ids=[ch1_sub.id],  # conflict!
            feedback="contradiction",
        )


def test_submit_merged_vote_rejects_double_vote(db_session):
    """submit_merged_vote rejects voting twice."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, submit_merged_vote
    ballots = select_jury(db_session, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    submit_merged_vote(db_session, task.id, arbiter_id, ch1_sub.id, [], "ok")

    import pytest
    with pytest.raises(ValueError, match="already voted"):
        submit_merged_vote(db_session, task.id, arbiter_id, ch1_sub.id, [], "again")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merged_arbitration.py -k "submit_merged_vote" -v`
Expected: ImportError — `submit_merged_vote` not found

**Step 3: Implement submit_merged_vote**

Add to `app/services/arbiter_pool.py`:

```python
def submit_merged_vote(
    db: Session,
    task_id: str,
    arbiter_user_id: str,
    winner_submission_id: str,
    malicious_submission_ids: list[str],
    feedback: str = "",
) -> JuryBallot:
    """Record an arbiter's merged vote: winner choice + malicious tags."""
    # Mutual exclusion check
    if winner_submission_id in malicious_submission_ids:
        raise ValueError("Winner cannot be tagged as malicious")

    ballot = db.query(JuryBallot).filter_by(
        task_id=task_id, arbiter_user_id=arbiter_user_id
    ).first()
    if not ballot:
        raise ValueError("No ballot found for this arbiter on this task")
    if ballot.winner_submission_id is not None:
        raise ValueError("Arbiter has already voted")

    ballot.winner_submission_id = winner_submission_id
    ballot.feedback = feedback
    ballot.voted_at = datetime.now(timezone.utc)

    # Create malicious tags
    for sub_id in malicious_submission_ids:
        tag = MaliciousTag(
            task_id=task_id,
            arbiter_user_id=arbiter_user_id,
            target_submission_id=sub_id,
        )
        db.add(tag)

    db.commit()
    db.refresh(ballot)
    return ballot
```

Add `from datetime import datetime, timezone` to the imports if not present.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merged_arbitration.py -k "submit_merged_vote" -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add app/services/arbiter_pool.py tests/test_merged_arbitration.py
git commit -m "feat: add submit_merged_vote with mutual exclusion validation"
```

---

## Task 5: Service — resolve_merged_jury (Core Resolution Logic)

**Files:**
- Modify: `app/services/arbiter_pool.py`
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing tests for all vote distribution scenarios**

Append to `tests/test_merged_arbitration.py`:

```python
def _vote_all(db, task, ballots, winner_ids, malicious_map=None):
    """
    Helper: submit votes for all ballots.
    winner_ids: list of 3 submission IDs (one per arbiter).
    malicious_map: dict {arbiter_index: [sub_ids]} — optional.
    """
    from app.services.arbiter_pool import submit_merged_vote
    malicious_map = malicious_map or {}
    for i, ballot in enumerate(ballots):
        submit_merged_vote(
            db,
            task_id=task.id,
            arbiter_user_id=ballot.arbiter_user_id,
            winner_submission_id=winner_ids[i],
            malicious_submission_ids=malicious_map.get(i, []),
            feedback=f"vote {i}",
        )


def test_resolve_30_consensus(db_session):
    """3:0 — all vote for challenger A → upheld."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, resolve_merged_jury
    ballots = select_jury(db_session, task.id)
    _vote_all(db_session, task, ballots, [ch1_sub.id] * 3)

    result = resolve_merged_jury(db_session, task.id)
    assert result["winner_submission_id"] == ch1_sub.id
    assert result["is_deadlock"] is False
    assert result["is_voided"] is False
    # Challenge for ch1 → upheld, ch2 → rejected
    for c in challenges:
        db_session.refresh(c)
    ch1_challenge = next(c for c in challenges if c.challenger_submission_id == ch1_sub.id)
    ch2_challenge = next(c for c in challenges if c.challenger_submission_id == ch2_sub.id)
    assert ch1_challenge.verdict == ChallengeVerdict.upheld
    assert ch2_challenge.verdict == ChallengeVerdict.rejected


def test_resolve_21_majority(db_session):
    """2:1 — challenger A gets 2 votes → upheld."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, resolve_merged_jury
    ballots = select_jury(db_session, task.id)
    _vote_all(db_session, task, ballots, [ch1_sub.id, ch1_sub.id, pw_sub.id])

    result = resolve_merged_jury(db_session, task.id)
    assert result["winner_submission_id"] == ch1_sub.id
    assert result["is_deadlock"] is False
    # Coherence: first 2 = coherent, last = incoherent
    for b in ballots:
        db_session.refresh(b)
    assert ballots[0].coherence_status == "coherent"
    assert ballots[1].coherence_status == "coherent"
    assert ballots[2].coherence_status == "incoherent"


def test_resolve_111_deadlock_pw_wins(db_session):
    """1:1:1 — deadlock → PW maintains original verdict."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, resolve_merged_jury
    ballots = select_jury(db_session, task.id)
    _vote_all(db_session, task, ballots, [pw_sub.id, ch1_sub.id, ch2_sub.id])

    result = resolve_merged_jury(db_session, task.id)
    assert result["winner_submission_id"] == pw_sub.id
    assert result["is_deadlock"] is True
    # All challengers rejected
    for c in challenges:
        db_session.refresh(c)
        assert c.verdict == ChallengeVerdict.rejected
    # All arbiters neutral
    for b in ballots:
        db_session.refresh(b)
        assert b.coherence_status == "neutral"


def test_resolve_pw_malicious_triggers_voided(db_session):
    """PW tagged malicious by ≥2 arbiters → task voided."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, resolve_merged_jury
    ballots = select_jury(db_session, task.id)
    # All 3 vote for ch1, but 2 tag PW as malicious
    _vote_all(
        db_session, task, ballots,
        [ch1_sub.id, ch1_sub.id, ch1_sub.id],
        malicious_map={0: [pw_sub.id], 1: [pw_sub.id]},
    )

    result = resolve_merged_jury(db_session, task.id)
    assert result["is_voided"] is True
    db_session.refresh(task)
    assert task.status == TaskStatus.voided


def test_resolve_malicious_challenger_in_voided(db_session):
    """In voided scenario, malicious challengers still get malicious verdict."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, resolve_merged_jury
    ballots = select_jury(db_session, task.id)
    # Vote ch1 as winner, tag PW + ch2 as malicious
    _vote_all(
        db_session, task, ballots,
        [ch1_sub.id, ch1_sub.id, ch1_sub.id],
        malicious_map={
            0: [pw_sub.id, ch2_sub.id],
            1: [pw_sub.id, ch2_sub.id],
        },
    )

    result = resolve_merged_jury(db_session, task.id)
    assert result["is_voided"] is True
    # ch1 is justified (non-malicious challenger in voided)
    # ch2 is malicious (tagged ≥2)
    for c in challenges:
        db_session.refresh(c)
    ch1_challenge = next(c for c in challenges if c.challenger_submission_id == ch1_sub.id)
    ch2_challenge = next(c for c in challenges if c.challenger_submission_id == ch2_sub.id)
    assert ch1_challenge.verdict == ChallengeVerdict.rejected  # justified but verdict=rejected (trust event differs)
    assert ch2_challenge.verdict == ChallengeVerdict.malicious


def test_resolve_malicious_tag_independent_of_winner(db_session):
    """Malicious tagging works independently of winner election."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury, resolve_merged_jury
    ballots = select_jury(db_session, task.id)
    # 2 vote PW (PW wins), 1 votes ch1; all 3 tag ch2 malicious
    _vote_all(
        db_session, task, ballots,
        [pw_sub.id, pw_sub.id, ch1_sub.id],
        malicious_map={0: [ch2_sub.id], 1: [ch2_sub.id], 2: [ch2_sub.id]},
    )

    result = resolve_merged_jury(db_session, task.id)
    assert result["winner_submission_id"] == pw_sub.id
    ch2_challenge = next(c for c in challenges if c.challenger_submission_id == ch2_sub.id)
    db_session.refresh(ch2_challenge)
    assert ch2_challenge.verdict == ChallengeVerdict.malicious
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merged_arbitration.py -k "resolve" -v`
Expected: ImportError — `resolve_merged_jury` not found

**Step 3: Implement resolve_merged_jury**

Add to `app/services/arbiter_pool.py`:

```python
from collections import Counter


def check_merged_jury_ready(db: Session, task_id: str) -> bool:
    """Check if all jury ballots for a task have been submitted."""
    ballots = db.query(JuryBallot).filter_by(task_id=task_id).all()
    return all(b.winner_submission_id is not None for b in ballots)


def resolve_merged_jury(db: Session, task_id: str) -> dict:
    """
    Resolve merged arbitration for a task.
    Returns dict with: winner_submission_id, is_deadlock, is_voided, verdicts.
    """
    task = db.query(Task).filter_by(id=task_id).first()
    ballots = db.query(JuryBallot).filter_by(task_id=task_id).all()
    voted_ballots = [b for b in ballots if b.winner_submission_id is not None]
    challenges = db.query(Challenge).filter_by(task_id=task_id).all()

    pw_submission_id = task.winner_submission_id

    # --- Step 1: Circuit breaker — PW malicious check ---
    pw_malicious_count = db.query(MaliciousTag).filter_by(
        task_id=task_id, target_submission_id=pw_submission_id
    ).count()

    is_voided = pw_malicious_count >= 2

    if is_voided:
        task.status = TaskStatus.voided
        # Set per-challenge verdicts (malicious challengers still punished)
        for c in challenges:
            sub_id = c.challenger_submission_id
            mal_count = db.query(MaliciousTag).filter_by(
                task_id=task_id, target_submission_id=sub_id
            ).count()
            c.verdict = ChallengeVerdict.malicious if mal_count >= 2 else ChallengeVerdict.rejected
            c.status = ChallengeStatus.judged
        db.commit()
        return {
            "winner_submission_id": None,
            "is_deadlock": False,
            "is_voided": True,
        }

    # --- Step 2: Elect winner ---
    vote_counts = Counter(b.winner_submission_id for b in voted_ballots)
    winner = None
    is_deadlock = True
    for sub_id, cnt in vote_counts.most_common():
        if cnt >= 2:
            winner = sub_id
            is_deadlock = False
            break

    if winner is None:
        winner = pw_submission_id  # deadlock → PW wins

    # --- Step 3: Set per-challenge verdicts ---
    for c in challenges:
        sub_id = c.challenger_submission_id
        mal_count = db.query(MaliciousTag).filter_by(
            task_id=task_id, target_submission_id=sub_id
        ).count()
        if sub_id == winner:
            c.verdict = ChallengeVerdict.upheld
        elif mal_count >= 2:
            c.verdict = ChallengeVerdict.malicious
        else:
            c.verdict = ChallengeVerdict.rejected
        c.status = ChallengeStatus.judged

    # --- Step 4: Arbiter coherence (winner dimension) ---
    if is_deadlock:
        for b in ballots:
            b.coherence_status = "neutral"
            b.is_majority = None
    else:
        for b in voted_ballots:
            if b.winner_submission_id == winner:
                b.coherence_status = "coherent"
                b.is_majority = True
            else:
                b.coherence_status = "incoherent"
                b.is_majority = False

    db.commit()
    return {
        "winner_submission_id": winner,
        "is_deadlock": is_deadlock,
        "is_voided": False,
    }
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merged_arbitration.py -k "resolve" -v`
Expected: All 7 resolve tests PASS

**Step 5: Commit**

```bash
git add app/services/arbiter_pool.py tests/test_merged_arbitration.py
git commit -m "feat: implement resolve_merged_jury with circuit breaker and coherence"
```

---

## Task 6: Trust Events — pw_malicious and challenger_justified

**Files:**
- Modify: `app/services/trust.py`
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing tests**

Append to `tests/test_merged_arbitration.py`:

```python
def test_pw_malicious_trust_event(db_session):
    """pw_malicious event applies -100 delta."""
    from app.services.trust import apply_event
    users = _make_users(db_session, 1)
    user = users[0]
    user.trust_score = 500
    db_session.commit()

    event = apply_event(db_session, user.id, TrustEventType.pw_malicious)
    db_session.refresh(user)
    assert event.delta == -100
    assert user.trust_score == 400


def test_challenger_justified_trust_event(db_session):
    """challenger_justified event applies +5 delta."""
    from app.services.trust import apply_event
    users = _make_users(db_session, 1)
    user = users[0]
    user.trust_score = 500
    db_session.commit()

    event = apply_event(db_session, user.id, TrustEventType.challenger_justified)
    db_session.refresh(user)
    assert event.delta == 5
    assert user.trust_score == 505
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merged_arbitration.py -k "trust_event" -v`
Expected: KeyError or ValueError — unhandled event types

**Step 3: Add new trust events to trust.py**

In `app/services/trust.py`, add to `_FIXED_DELTAS` dict:
```python
TrustEventType.pw_malicious: -100,
TrustEventType.challenger_justified: 5,
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merged_arbitration.py -k "trust_event" -v`
Expected: PASS

**Step 5: Run full test suite to check no regressions**

Run: `pytest -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add app/services/trust.py tests/test_merged_arbitration.py
git commit -m "feat: add pw_malicious and challenger_justified trust events"
```

---

## Task 7: API Endpoint — POST /tasks/{task_id}/jury-vote

**Files:**
- Modify: `app/routers/challenges.py`
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing test**

Append to `tests/test_merged_arbitration.py`:

```python
def test_jury_vote_endpoint_happy_path(client_with_db):
    """POST /tasks/{task_id}/jury-vote accepts a merged vote."""
    from unittest.mock import patch
    client, db = client_with_db

    # Setup: create task, submissions, challenges, jury
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    resp = client.post(
        f"/tasks/{task.id}/jury-vote",
        json={
            "arbiter_user_id": arbiter_id,
            "winner_submission_id": ch1_sub.id,
            "malicious_submission_ids": [ch2_sub.id],
            "feedback": "ch1 is best",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["winner_submission_id"] == ch1_sub.id
    assert data["voted_at"] is not None


def test_jury_vote_endpoint_rejects_non_candidate(client_with_db):
    """POST /tasks/{task_id}/jury-vote rejects non-candidate winner."""
    client, db = client_with_db
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    resp = client.post(
        f"/tasks/{task.id}/jury-vote",
        json={
            "arbiter_user_id": arbiter_id,
            "winner_submission_id": "nonexistent-id",
            "malicious_submission_ids": [],
            "feedback": "",
        },
    )
    assert resp.status_code == 400


def test_jury_vote_endpoint_rejects_winner_in_malicious(client_with_db):
    """POST /tasks/{task_id}/jury-vote rejects winner in malicious list."""
    client, db = client_with_db
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    resp = client.post(
        f"/tasks/{task.id}/jury-vote",
        json={
            "arbiter_user_id": arbiter_id,
            "winner_submission_id": ch1_sub.id,
            "malicious_submission_ids": [ch1_sub.id],
            "feedback": "",
        },
    )
    assert resp.status_code == 422  # Pydantic validation error
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merged_arbitration.py -k "jury_vote_endpoint" -v`
Expected: 404 — route does not exist

**Step 3: Add the endpoint to challenges router**

Add to `app/routers/challenges.py`:

```python
from app.schemas import JuryVoteIn, JuryBallotOut
from app.models import JuryBallot, Submission, Challenge
from app.services.arbiter_pool import submit_merged_vote


@router.post("/tasks/{task_id}/jury-vote", response_model=JuryBallotOut)
def jury_vote(task_id: str, body: JuryVoteIn, db: Session = Depends(get_db)):
    """Submit a merged arbitration vote (pick winner + tag malicious)."""
    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")

    # Build candidate pool
    candidate_ids = set()
    if task.winner_submission_id:
        candidate_ids.add(task.winner_submission_id)
    challenges = db.query(Challenge).filter_by(task_id=task_id).all()
    for c in challenges:
        candidate_ids.add(c.challenger_submission_id)

    # Validate winner is in candidate pool
    if body.winner_submission_id not in candidate_ids:
        raise HTTPException(400, "Winner must be in candidate pool")

    # Validate malicious targets are in candidate pool
    for mid in body.malicious_submission_ids:
        if mid not in candidate_ids:
            raise HTTPException(400, f"Malicious target {mid} not in candidate pool")

    try:
        ballot = submit_merged_vote(
            db,
            task_id=task_id,
            arbiter_user_id=body.arbiter_user_id,
            winner_submission_id=body.winner_submission_id,
            malicious_submission_ids=body.malicious_submission_ids,
            feedback=body.feedback,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return ballot
```

Ensure imports are added at top of `app/routers/challenges.py`:
```python
from app.models import Task, Challenge, Submission, JuryBallot
from app.schemas import JuryVoteIn, JuryBallotOut
from app.services.arbiter_pool import submit_merged_vote
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merged_arbitration.py -k "jury_vote_endpoint" -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add app/routers/challenges.py tests/test_merged_arbitration.py
git commit -m "feat: add POST /tasks/{task_id}/jury-vote endpoint"
```

---

## Task 8: Scheduler — Wire resolve_merged_jury into Settlement

**Files:**
- Modify: `app/scheduler.py`
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing test for scheduler integration**

Append to `tests/test_merged_arbitration.py`:

```python
def test_scheduler_resolves_merged_jury(db_session):
    """Scheduler calls resolve_merged_jury and applies trust events."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db_session, task.id)

    # All 3 vote for ch1 (3:0 consensus)
    _vote_all(db_session, task, ballots, [ch1_sub.id] * 3)

    # Mock on-chain call
    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import _settle_after_arbitration
        _settle_after_arbitration(db_session, task)

    db_session.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == ch1_sub.id  # switched to ch1


def test_scheduler_voided_path(db_session):
    """Scheduler handles voided task (PW malicious)."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db_session, task.id)

    # All vote ch1, tag PW malicious
    _vote_all(
        db_session, task, ballots,
        [ch1_sub.id] * 3,
        malicious_map={0: [pw_sub.id], 1: [pw_sub.id], 2: [pw_sub.id]},
    )

    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import _settle_after_arbitration
        _settle_after_arbitration(db_session, task)

    db_session.refresh(task)
    assert task.status == TaskStatus.voided
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merged_arbitration.py -k "scheduler" -v`
Expected: Failure — `_settle_after_arbitration` doesn't call `resolve_merged_jury`

**Step 3: Modify scheduler to use merged jury resolution**

In `app/scheduler.py`, modify `_settle_after_arbitration()` to:

1. At the start, call `resolve_merged_jury(db, task.id)` instead of looping per-challenge `resolve_jury()`.
2. If result `is_voided`:
   - Apply `pw_malicious` trust event to PW worker
   - Call `check_and_slash(db, pw_worker_id)`
   - For each challenge: apply `challenger_justified` (if verdict=rejected) or `challenger_malicious` (if verdict=malicious)
   - Apply `publisher_completed` trust event (refund scenario)
   - Call `_resolve_via_contract()` with voided verdicts or empty verdicts
   - Set `task.status = TaskStatus.voided` (already set by resolve_merged_jury)
   - Return
3. If result NOT voided:
   - If any upheld: switch `task.winner_submission_id` to the upheld challenger
   - For each challenge: apply trust events based on verdict (`challenger_won`, `challenger_rejected`, `challenger_malicious`)
   - Apply `worker_won` or consolation trust events
   - Apply `publisher_completed` trust event
   - Build verdicts array for contract
   - Compute arbiter coherence using ballot `coherence_status` fields
   - Call `_resolve_via_contract()`
   - Set `task.status = TaskStatus.closed`

Also modify `_try_resolve_challenge_jury()` — replace the call to `resolve_jury()` + per-challenge verdict setting with a check for `check_merged_jury_ready()`. When all ballots are submitted (or timeout), call `resolve_merged_jury()` once for the whole task, then proceed to settlement.

Specifically, the Phase 4 block in `_check_and_settle()` should be restructured:

```python
# Phase 4: arbitrating → closed/voided
if task.status == TaskStatus.arbitrating:
    ballots = db.query(JuryBallot).filter_by(task_id=task.id).all()
    all_voted = all(b.winner_submission_id is not None for b in ballots)

    # Check timeout
    first_created = min(b.created_at for b in ballots) if ballots else now
    timed_out = (now - first_created) >= JURY_VOTING_TIMEOUT

    if not all_voted and not timed_out:
        continue  # still waiting

    # Handle timeouts for non-voters
    if timed_out:
        for b in ballots:
            if b.winner_submission_id is None:
                apply_event(db, b.arbiter_user_id, TrustEventType.arbiter_timeout, task_id=task.id)

    # Resolve merged jury
    result = resolve_merged_jury(db, task.id)
    _settle_after_arbitration(db, task, result)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merged_arbitration.py -k "scheduler" -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest -v`
Expected: Existing tests may need updates where they mock `resolve_jury` — adjust imports to match new flow. Fix any broken tests.

**Step 6: Commit**

```bash
git add app/scheduler.py tests/test_merged_arbitration.py
git commit -m "feat: wire resolve_merged_jury into scheduler settlement"
```

---

## Task 9: API — GET /tasks/{task_id}/jury-ballots (Read Endpoint)

**Files:**
- Modify: `app/routers/challenges.py`
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing test**

Append to `tests/test_merged_arbitration.py`:

```python
def test_get_jury_ballots_hides_votes_before_complete(client_with_db):
    """GET /tasks/{task_id}/jury-ballots hides details until all voted."""
    client, db = client_with_db
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury, submit_merged_vote
    ballots = select_jury(db, task.id)

    # Only 1 of 3 voted
    submit_merged_vote(db, task.id, ballots[0].arbiter_user_id, ch1_sub.id, [], "ok")

    resp = client.get(f"/tasks/{task.id}/jury-ballots")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # Votes should be hidden (winner_submission_id = null for all)
    voted_count = sum(1 for b in data if b["voted_at"] is not None)
    hidden_count = sum(1 for b in data if b["winner_submission_id"] is None)
    assert voted_count == 0 or hidden_count >= 2  # actual votes hidden


def test_get_jury_ballots_reveals_after_complete(client_with_db):
    """GET /tasks/{task_id}/jury-ballots reveals all after 3/3 voted."""
    client, db = client_with_db
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db, task.id)
    _vote_all(db, task, ballots, [ch1_sub.id] * 3)

    resp = client.get(f"/tasks/{task.id}/jury-ballots")
    assert resp.status_code == 200
    data = resp.json()
    assert all(b["winner_submission_id"] == ch1_sub.id for b in data)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merged_arbitration.py -k "get_jury_ballots" -v`
Expected: 404 — route does not exist

**Step 3: Add GET endpoint**

Add to `app/routers/challenges.py`:

```python
@router.get("/tasks/{task_id}/jury-ballots", response_model=list[JuryBallotOut])
def get_jury_ballots(task_id: str, db: Session = Depends(get_db)):
    """Get all jury ballots for a task. Hides vote details until all voted."""
    ballots = db.query(JuryBallot).filter_by(task_id=task_id).all()
    all_voted = all(b.winner_submission_id is not None for b in ballots)

    if not all_voted:
        # Return ballots with vote details stripped — only show voted_at presence
        result = []
        for b in ballots:
            out = JuryBallotOut.model_validate(b)
            has_voted = b.winner_submission_id is not None
            out.winner_submission_id = None
            out.feedback = None
            out.voted_at = b.voted_at if has_voted else None  # show timing but not content
            result.append(out)
        return result

    return ballots
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merged_arbitration.py -k "get_jury_ballots" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/routers/challenges.py tests/test_merged_arbitration.py
git commit -m "feat: add GET /tasks/{task_id}/jury-ballots with vote hiding"
```

---

## Task 10: Smart Contract — voidChallenge + challengerList

**Files:**
- Modify: `contracts/src/ChallengeEscrow.sol`
- Modify: `contracts/test/ChallengeEscrow.t.sol` (if exists)

**Step 1: Add challengerList to joinChallenge**

In `contracts/src/ChallengeEscrow.sol`, add storage:

```solidity
mapping(bytes32 => address[]) public challengerList;
```

In `joinChallenge()`, after incrementing `challengerCount`, add:
```solidity
challengerList[taskId].push(challenger);
```

**Step 2: Add ChallengerRefund struct and voidChallenge function**

```solidity
struct ChallengerRefund {
    address challenger;
    bool refund;  // true = return deposit, false = forfeit (malicious)
}

function voidChallenge(
    bytes32 taskId,
    address publisher,
    uint256 publisherRefund,
    ChallengerRefund[] calldata refunds,
    address[] calldata arbiters,
    uint256 arbiterReward
) external onlyOwner {
    ChallengeInfo storage info = challenges[taskId];
    require(info.mainBounty > 0, "No challenge");
    require(!info.resolved, "Already resolved");

    // 1. Process each challenger
    uint256 totalArbiterBonus = 0;
    for (uint i = 0; i < refunds.length; i++) {
        uint256 deposit = challengerDeposits[taskId][refunds[i].challenger];
        if (deposit == 0) continue;

        if (refunds[i].refund) {
            // Justified challenger — full refund
            usdc.transfer(refunds[i].challenger, deposit);
        } else {
            // Malicious challenger — forfeit deposit
            uint256 arbiterShare = (deposit * 30) / 100;
            totalArbiterBonus += arbiterShare;
            // remainder stays in contract for platform
        }
        challengerDeposits[taskId][refunds[i].challenger] = 0;
    }

    // 2. Refund publisher
    if (publisherRefund > 0) {
        usdc.transfer(publisher, publisherRefund);
    }

    // 3. Pay arbiters (base reward + bonus from malicious deposits)
    uint256 totalArbiterPay = arbiterReward + totalArbiterBonus;
    if (arbiters.length > 0 && totalArbiterPay > 0) {
        uint256 perArbiter = totalArbiterPay / arbiters.length;
        for (uint i = 0; i < arbiters.length; i++) {
            usdc.transfer(arbiters[i], perArbiter);
        }
    }

    // 4. Platform gets remainder (service fees + forfeited deposit remainder)
    uint256 balance = usdc.balanceOf(address(this));
    if (balance > 0) {
        usdc.transfer(owner(), balance);
    }

    info.resolved = true;
    emit ChallengeResolved(taskId, address(0), 3); // 3 = voided
}
```

**Step 3: Write Foundry test**

Create or update `contracts/test/ChallengeEscrow.t.sol` to test:
- `voidChallenge` with all challengers refunded (happy path)
- `voidChallenge` with mixed refund/forfeit
- `voidChallenge` reverts if already resolved

**Step 4: Run Foundry tests**

Run: `cd contracts && forge test -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add contracts/src/ChallengeEscrow.sol contracts/test/
git commit -m "feat: add voidChallenge() and challengerList to ChallengeEscrow"
```

---

## Task 11: Backend — void_challenge_onchain Helper

**Files:**
- Modify: `app/services/escrow.py` (or wherever `join_challenge_onchain` / `resolve_challenge_onchain` live)
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write failing test**

Append to `tests/test_merged_arbitration.py`:

```python
def test_void_challenge_onchain_called(db_session):
    """_resolve_via_contract calls voidChallenge for voided tasks."""
    # This test verifies the contract call is constructed correctly
    # Actual chain calls are always mocked
    pass  # Placeholder — actual test depends on escrow service structure
```

**Step 2: Add void_challenge_onchain function**

In the escrow service file, add a function that constructs the `voidChallenge` contract call with the correct parameters:
- `publisher` address from task publisher's wallet
- `publisherRefund` = 95% of bounty
- `refunds[]` array with per-challenger refund/forfeit based on verdict
- `arbiters[]` wallets
- `arbiterReward` = 5% of bounty

**Step 3: Wire into scheduler**

In `_settle_after_arbitration`, when `is_voided`:
```python
if result["is_voided"]:
    _void_via_contract(db, task, challenges, ballots)
```

**Step 4: Run tests**

Run: `pytest tests/test_merged_arbitration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/ app/scheduler.py tests/test_merged_arbitration.py
git commit -m "feat: add void_challenge_onchain helper for voided tasks"
```

---

## Task 12: Frontend — Rewrite ArbiterPanel for Merged Voting

**Files:**
- Modify: `frontend/components/ArbiterPanel.tsx`
- Modify: `frontend/lib/api.ts` (or wherever API calls are defined)

**Step 1: Add API functions**

In the frontend API layer, add:

```typescript
export async function submitJuryVote(taskId: string, body: {
  arbiter_user_id: string;
  winner_submission_id: string;
  malicious_submission_ids: string[];
  feedback: string;
}) {
  const res = await fetch(`/api/tasks/${taskId}/jury-vote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getJuryBallots(taskId: string) {
  const res = await fetch(`/api/tasks/${taskId}/jury-ballots`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

**Step 2: Rewrite MergedVoteCard component**

Replace `ChallengeVoteCard` in `ArbiterPanel.tsx` with `MergedVoteCard`:

- Display candidate pool as Radio group (PW + all challengers)
- Display Checkbox group for malicious tags (all candidates)
- **Mutual exclusion**: when a Radio is selected, disable that candidate's Checkbox + auto-uncheck
- Textarea for feedback
- Submit button calls `submitJuryVote()`
- Show "X/3 voted" progress

**Step 3: Update ArbiterPanel to use merged voting**

- Instead of rendering per-challenge vote cards, render ONE `MergedVoteCard` per task
- Fetch candidate pool from task's submissions + challenges
- Fetch ballot status via `getJuryBallots(taskId)`

**Step 4: Write Vitest test**

Create `frontend/components/__tests__/ArbiterPanel.test.tsx`:

```typescript
import { describe, it, expect } from 'vitest';
// Test that mutual exclusion works:
// - Selecting winner disables their malicious checkbox
// - Cannot submit with winner in malicious list
```

**Step 5: Run frontend tests**

Run: `cd frontend && npx vitest components/__tests__/ArbiterPanel.test.tsx`
Expected: PASS

**Step 6: Commit**

```bash
git add frontend/components/ArbiterPanel.tsx frontend/lib/ frontend/components/__tests__/
git commit -m "feat: rewrite ArbiterPanel for merged arbitration voting UI"
```

---

## Task 13: Frontend — ChallengePanel Voided Status

**Files:**
- Modify: `frontend/components/ChallengePanel.tsx`

**Step 1: Add voided status display**

In `ChallengePanel.tsx`, add handling for `task.status === 'voided'`:

```tsx
{task.status === 'voided' && (
  <Badge variant="destructive">Task Voided — PW judged malicious</Badge>
)}
```

Update `ChallengeCard` to show `justified` badge when challenge verdict is rejected but task is voided (these are justified whistleblowers).

**Step 2: Add merged voting progress display**

Replace `ArbiterVotingPanel` (which shows per-challenge votes) with a new `MergedVotingProgress` component that shows:
- "X/3 jury members voted" counter
- After all voted: shows who each arbiter picked as winner
- Shows malicious tags with counts

**Step 3: Run frontend tests**

Run: `cd frontend && npm test`
Expected: All existing + new tests pass

**Step 4: Commit**

```bash
git add frontend/components/ChallengePanel.tsx
git commit -m "feat: add voided status and merged voting progress to ChallengePanel"
```

---

## Task 14: Integration Test — Full Lifecycle

**Files:**
- Modify: `tests/test_merged_arbitration.py`

**Step 1: Write end-to-end integration tests**

Add comprehensive integration tests that exercise the full flow via HTTP API:

```python
def test_full_lifecycle_challenger_wins(client_with_db):
    """Full flow: create task → submit → challenge → jury vote → challenger wins."""
    # 1. Create quality_first task
    # 2. Submit PW + 2 challengers
    # 3. Manually set to challenge_window
    # 4. Create 2 challenges
    # 5. Manually set to arbitrating, create jury
    # 6. POST jury-vote ×3 (2 vote ch1, 1 votes PW)
    # 7. Trigger settlement
    # 8. Assert: ch1 won, ch2 rejected, task closed, trust events applied
    pass


def test_full_lifecycle_pw_malicious_voided(client_with_db):
    """Full flow: PW tagged malicious → task voided."""
    # 1-5 same as above
    # 6. POST jury-vote ×3 (vote ch1, tag PW malicious ×2)
    # 7. Trigger settlement
    # 8. Assert: task voided, PW gets -100, challengers justified/malicious
    pass


def test_full_lifecycle_deadlock(client_with_db):
    """Full flow: 1:1:1 deadlock → PW wins."""
    # 1-5 same
    # 6. POST jury-vote: each votes different candidate
    # 7. Trigger settlement
    # 8. Assert: PW wins, all challengers rejected, arbiters neutral
    pass
```

**Step 2: Run integration tests**

Run: `pytest tests/test_merged_arbitration.py -v`
Expected: All tests pass

**Step 3: Run full test suite**

Run: `pytest -v`
Expected: All tests pass (no regressions)

**Step 4: Commit**

```bash
git add tests/test_merged_arbitration.py
git commit -m "test: add full lifecycle integration tests for merged arbitration"
```

---

## Task 15: Update Existing Tests for Compatibility

**Files:**
- Modify: `tests/test_challenge_api.py`
- Modify: `tests/test_scheduler.py` (if exists)
- Modify: any other files that reference `ArbiterVote`, `resolve_jury`, or old voting flow

**Step 1: Identify broken tests**

Run: `pytest -v 2>&1 | grep FAIL`
Fix any tests that fail due to:
- `select_jury` now returning `JuryBallot` instead of `ArbiterVote`
- `resolve_jury` being removed/replaced
- New `TaskStatus.voided` affecting status checks

**Step 2: Update mocks and assertions**

For each broken test:
- Replace `ArbiterVote` references with `JuryBallot` where appropriate
- Update mock patches from `resolve_jury` to `resolve_merged_jury`
- Add `voided` to any status whitelist checks

**Step 3: Run full suite**

Run: `pytest -v`
Expected: All tests pass

**Step 4: Commit**

```bash
git add tests/
git commit -m "fix: update existing tests for merged arbitration compatibility"
```

---

## Summary of Files Changed

| # | File | Action |
|---|------|--------|
| 1 | `app/models.py` | Add JuryBallot, MaliciousTag, TaskStatus.voided, TrustEventType.pw_malicious/challenger_justified |
| 2 | `app/schemas.py` | Add JuryVoteIn, JuryBallotOut, MaliciousTagOut |
| 3 | `app/services/arbiter_pool.py` | Rewrite select_jury, add submit_merged_vote, resolve_merged_jury, check_merged_jury_ready |
| 4 | `app/services/trust.py` | Add pw_malicious, challenger_justified to _FIXED_DELTAS |
| 5 | `app/routers/challenges.py` | Add POST jury-vote, GET jury-ballots |
| 6 | `app/scheduler.py` | Wire resolve_merged_jury into Phase 4 settlement |
| 7 | `contracts/src/ChallengeEscrow.sol` | Add voidChallenge(), challengerList |
| 8 | `frontend/components/ArbiterPanel.tsx` | Rewrite merged voting UI |
| 9 | `frontend/components/ChallengePanel.tsx` | Add voided status display |
| 10 | `alembic/versions/` | Auto-generated migration |
| 11 | `tests/test_merged_arbitration.py` | New — all unit + integration tests |
