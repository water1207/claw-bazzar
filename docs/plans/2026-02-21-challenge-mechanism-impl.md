# V7 Challenge Mechanism Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 quality_first 模式实现挑战仲裁机制：deadline 到期 → Oracle 统一评分 → 公示暂定 winner → 落选者可挑战 → Arbiter 仲裁 → 结算。

**Architecture:** 新增 Challenge 模型和 Arbiter 服务，扩展 Task/Submission/User 模型，改造 Scheduler 为四阶段生命周期引擎。fastest_first 完全不动。Oracle 和 Arbiter 均使用 Stub。

> **押金机制说明（Stub）：** 押金仅做数据库记账（`deposit` / `deposit_returned` 字段），不涉及任何链上收款或退款操作。`deposit_returned` 字段仅记录"应退金额"，实际 USDC 转账留待后续版本实现。

**Tech Stack:** Python / FastAPI / SQLAlchemy / APScheduler / pytest

---

### Task 1: 扩展模型枚举和字段

**Files:**
- Modify: `app/models.py`
- Test: `tests/test_challenge_model.py` (Create)

**Step 1: Write the failing test**

创建 `tests/test_challenge_model.py`：

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, User, Challenge,
    TaskType, TaskStatus, SubmissionStatus, PayoutStatus,
    ChallengeVerdict, ChallengeStatus, UserRole,
)
from datetime import datetime, timedelta, timezone


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_task_status_has_new_values():
    assert TaskStatus.scoring == "scoring"
    assert TaskStatus.challenge_window == "challenge_window"
    assert TaskStatus.arbitrating == "arbitrating"


def test_challenge_verdict_enum():
    assert ChallengeVerdict.upheld == "upheld"
    assert ChallengeVerdict.rejected == "rejected"
    assert ChallengeVerdict.malicious == "malicious"


def test_challenge_status_enum():
    assert ChallengeStatus.pending == "pending"
    assert ChallengeStatus.judged == "judged"


def test_task_new_fields():
    db = make_db()
    task = Task(
        title="T", description="d", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        submission_deposit=1.0, challenge_duration=7200,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    assert task.submission_deposit == 1.0
    assert task.challenge_duration == 7200
    assert task.challenge_window_end is None


def test_submission_deposit_fields():
    db = make_db()
    task = Task(title="T", description="d", type=TaskType.quality_first,
                deadline=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(task)
    db.flush()
    sub = Submission(task_id=task.id, worker_id="w1", content="c", deposit=0.5)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    assert sub.deposit == 0.5
    assert sub.deposit_returned is None


def test_user_credit_score_default():
    db = make_db()
    user = User(nickname="test", wallet="0x123", role=UserRole.worker)
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.credit_score == 100.0


def test_challenge_create():
    db = make_db()
    task = Task(title="T", description="d", type=TaskType.quality_first,
                deadline=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(task)
    db.flush()
    s1 = Submission(task_id=task.id, worker_id="w1", content="a")
    s2 = Submission(task_id=task.id, worker_id="w2", content="b")
    db.add_all([s1, s2])
    db.flush()

    challenge = Challenge(
        task_id=task.id,
        challenger_submission_id=s2.id,
        target_submission_id=s1.id,
        reason="My submission is better because...",
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    assert challenge.status == ChallengeStatus.pending
    assert challenge.verdict is None
    assert challenge.arbiter_score is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_challenge_model.py -v`
Expected: ImportError — `Challenge`, `ChallengeVerdict`, `ChallengeStatus` not found, `TaskStatus` missing new values

**Step 3: Write minimal implementation**

修改 `app/models.py`，添加新枚举、新字段、新模型：

```python
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, Enum
from .database import Base


class TaskType(str, PyEnum):
    fastest_first = "fastest_first"
    quality_first = "quality_first"


class TaskStatus(str, PyEnum):
    open = "open"
    scoring = "scoring"
    challenge_window = "challenge_window"
    arbitrating = "arbitrating"
    closed = "closed"


class SubmissionStatus(str, PyEnum):
    pending = "pending"
    scored = "scored"


class UserRole(str, PyEnum):
    publisher = "publisher"
    worker = "worker"
    both = "both"


class PayoutStatus(str, PyEnum):
    pending = "pending"
    paid = "paid"
    failed = "failed"


class ChallengeVerdict(str, PyEnum):
    upheld = "upheld"
    rejected = "rejected"
    malicious = "malicious"


class ChallengeStatus(str, PyEnum):
    pending = "pending"
    judged = "judged"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    type = Column(Enum(TaskType), nullable=False)
    threshold = Column(Float, nullable=True)       # fastest_first only
    max_revisions = Column(Integer, nullable=True)  # quality_first only
    deadline = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.open)
    winner_submission_id = Column(String, nullable=True)
    publisher_id = Column(String, nullable=True)
    bounty = Column(Float, nullable=True)
    payment_tx_hash = Column(String, nullable=True)
    payout_status = Column(Enum(PayoutStatus), nullable=False, default=PayoutStatus.pending)
    payout_tx_hash = Column(String, nullable=True)
    payout_amount = Column(Float, nullable=True)
    submission_deposit = Column(Float, nullable=True)
    challenge_duration = Column(Integer, nullable=True)
    challenge_window_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    nickname = Column(String, unique=True, nullable=False)
    wallet = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    credit_score = Column(Float, nullable=False, default=100.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, nullable=False)
    worker_id = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    score = Column(Float, nullable=True)
    oracle_feedback = Column(Text, nullable=True)
    status = Column(Enum(SubmissionStatus), nullable=False, default=SubmissionStatus.pending)
    deposit = Column(Float, nullable=True)
    deposit_returned = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, nullable=False)
    challenger_submission_id = Column(String, nullable=False)
    target_submission_id = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    verdict = Column(Enum(ChallengeVerdict), nullable=True)
    arbiter_feedback = Column(Text, nullable=True)
    arbiter_score = Column(Float, nullable=True)
    status = Column(Enum(ChallengeStatus), nullable=False, default=ChallengeStatus.pending)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_challenge_model.py -v`
Expected: All 8 tests PASS

**Step 5: Run all existing tests to confirm no regressions**

Run: `pytest -v`
Expected: All existing 53 tests still PASS (new TaskStatus values are backward-compatible via SQLAlchemy Enum)

**Step 6: Commit**

```bash
git add app/models.py tests/test_challenge_model.py
git commit -m "feat: add Challenge model, extend Task/Submission/User for V7"
```

---

### Task 2: 扩展 Pydantic schemas

**Files:**
- Modify: `app/schemas.py`

**Step 1: Update schemas**

> **重要：** 必须保留现有的 `model_validator`（`fastest_first` 任务必须填写 `threshold`）。在更新 `TaskCreate` 时，保留以下代码，并确保 `from pydantic import BaseModel, model_validator` 导入不丢失：
> ```python
> from pydantic import BaseModel, model_validator
> # ...
> class TaskCreate(BaseModel):
>     # ... fields ...
>     @model_validator(mode="after")
>     def check_fastest_first_threshold(self) -> "TaskCreate":
>         if self.type == TaskType.fastest_first and self.threshold is None:
>             raise ValueError("fastest_first tasks require a threshold")
>         return self
> ```

在 `app/schemas.py` 中添加 Challenge 相关 schemas，并更新 TaskCreate/TaskOut/SubmissionOut：

```python
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, model_validator
from .models import (
    TaskType, TaskStatus, SubmissionStatus, UserRole, PayoutStatus,
    ChallengeVerdict, ChallengeStatus,
)


class UserCreate(BaseModel):
    nickname: str
    wallet: str
    role: UserRole


class UserOut(BaseModel):
    id: str
    nickname: str
    wallet: str
    role: UserRole
    credit_score: float = 100.0
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: datetime
    publisher_id: str
    bounty: float
    submission_deposit: Optional[float] = None
    challenge_duration: Optional[int] = None

    @model_validator(mode="after")
    def check_fastest_first_threshold(self) -> "TaskCreate":
        if self.type == TaskType.fastest_first and self.threshold is None:
            raise ValueError("fastest_first tasks require a threshold")
        return self


class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: datetime
    status: TaskStatus
    winner_submission_id: Optional[str] = None
    publisher_id: Optional[str] = None
    bounty: Optional[float] = None
    payment_tx_hash: Optional[str] = None
    payout_status: PayoutStatus = PayoutStatus.pending
    payout_tx_hash: Optional[str] = None
    payout_amount: Optional[float] = None
    submission_deposit: Optional[float] = None
    challenge_duration: Optional[int] = None
    challenge_window_end: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskDetail(TaskOut):
    submissions: List["SubmissionOut"] = []


class SubmissionCreate(BaseModel):
    worker_id: str
    content: str


class SubmissionOut(BaseModel):
    id: str
    task_id: str
    worker_id: str
    revision: int
    content: str
    score: Optional[float] = None
    oracle_feedback: Optional[str] = None
    status: SubmissionStatus
    deposit: Optional[float] = None
    deposit_returned: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChallengeCreate(BaseModel):
    challenger_submission_id: str
    reason: str


class ChallengeOut(BaseModel):
    id: str
    task_id: str
    challenger_submission_id: str
    target_submission_id: str
    reason: str
    verdict: Optional[ChallengeVerdict] = None
    arbiter_feedback: Optional[str] = None
    arbiter_score: Optional[float] = None
    status: ChallengeStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class ScoreInput(BaseModel):
    score: float
    feedback: Optional[str] = None


TaskDetail.model_rebuild()
```

**Step 2: Run all tests**

Run: `pytest -v`
Expected: All tests PASS (schema changes are additive, existing fields unchanged)

**Step 3: Commit**

```bash
git add app/schemas.py
git commit -m "feat: add Challenge schemas, extend TaskCreate/TaskOut/SubmissionOut"
```

---

### Task 3: 提交时记录押金

**Files:**
- Modify: `app/routers/submissions.py`
- Test: `tests/test_deposit.py` (Create)

**Step 1: Write the failing test**

创建 `tests/test_deposit.py`：

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def make_quality_task(client, bounty=10.0, submission_deposit=1.0):
    body = {
        "title": "Q", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future(),
        "publisher_id": "pub", "bounty": bounty,
        "submission_deposit": submission_deposit,
    }
    with PAYMENT_MOCK:
        return client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()


def test_submission_records_deposit(client):
    task = make_quality_task(client, bounty=10.0, submission_deposit=1.0)
    with patch("app.routers.submissions.invoke_oracle"):
        resp = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["deposit"] == 1.0
    assert data["deposit_returned"] is None


def test_submission_deposit_defaults_to_bounty_10_percent(client):
    """When submission_deposit is not set, default to bounty * 0.10."""
    body = {
        "title": "Q2", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future(),
        "publisher_id": "pub", "bounty": 20.0,
    }
    with PAYMENT_MOCK:
        task = client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()
    with patch("app.routers.submissions.invoke_oracle"):
        resp = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        })
    assert resp.status_code == 201
    assert resp.json()["deposit"] == 2.0  # 20.0 * 0.10


def test_fastest_first_no_deposit(client):
    """fastest_first tasks don't require deposit."""
    body = {
        "title": "F", "description": "d", "type": "fastest_first",
        "threshold": 0.8, "deadline": future(),
        "publisher_id": "pub", "bounty": 10.0,
    }
    with PAYMENT_MOCK:
        task = client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()
    with patch("app.routers.submissions.invoke_oracle"):
        resp = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        })
    assert resp.status_code == 201
    assert resp.json()["deposit"] is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_deposit.py -v`
Expected: FAIL — deposit not set on submissions

**Step 3: Modify submission creation to record deposit**

修改 `app/routers/submissions.py`，在创建 Submission 时设置 deposit：

```python
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Task, Submission, TaskStatus, TaskType
from ..schemas import SubmissionCreate, SubmissionOut
from ..services.oracle import invoke_oracle

router = APIRouter(tags=["submissions"])

DEFAULT_DEPOSIT_RATE = 0.10


@router.post("/tasks/{task_id}/submissions", response_model=SubmissionOut, status_code=201)
def create_submission(
    task_id: str,
    data: SubmissionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.open:
        raise HTTPException(status_code=400, detail="Task is not open")
    deadline = task.deadline if task.deadline.tzinfo else task.deadline.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > deadline:
        raise HTTPException(status_code=400, detail="Task deadline has passed")

    existing = db.query(Submission).filter(
        Submission.task_id == task_id,
        Submission.worker_id == data.worker_id,
    ).count()

    if task.type.value == "fastest_first" and existing >= 1:
        raise HTTPException(status_code=400, detail="Already submitted for this fastest_first task")

    if task.type.value == "quality_first" and task.max_revisions and existing >= task.max_revisions:
        raise HTTPException(
            status_code=400, detail=f"Max revisions ({task.max_revisions}) reached"
        )

    # Calculate deposit for quality_first tasks
    deposit = None
    if task.type == TaskType.quality_first and task.bounty:
        deposit = task.submission_deposit if task.submission_deposit is not None else round(task.bounty * DEFAULT_DEPOSIT_RATE, 6)

    submission = Submission(
        task_id=task_id,
        worker_id=data.worker_id,
        content=data.content,
        revision=existing + 1,
        deposit=deposit,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    background_tasks.add_task(invoke_oracle, submission.id, task_id)
    return submission


@router.get("/tasks/{task_id}/submissions", response_model=List[SubmissionOut])
def list_submissions(task_id: str, db: Session = Depends(get_db)):
    if not db.query(Task).filter(Task.id == task_id).first():
        raise HTTPException(status_code=404, detail="Task not found")
    return db.query(Submission).filter(Submission.task_id == task_id).all()


@router.get("/tasks/{task_id}/submissions/{sub_id}", response_model=SubmissionOut)
def get_submission(task_id: str, sub_id: str, db: Session = Depends(get_db)):
    sub = db.query(Submission).filter(
        Submission.id == sub_id, Submission.task_id == task_id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return sub
```

**Step 4: Run tests**

Run: `pytest tests/test_deposit.py tests/test_submissions.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/routers/submissions.py tests/test_deposit.py
git commit -m "feat: record deposit on quality_first submissions"
```

---

### Task 4: Arbiter stub 脚本 + 服务封装

**Files:**
- Create: `oracle/arbiter.py`
- Create: `app/services/arbiter.py`
- Test: `tests/test_arbiter_stub.py` (Create)

**Step 1: Write the failing test**

创建 `tests/test_arbiter_stub.py`：

```python
import json
import subprocess
import sys
from pathlib import Path

ARBITER_SCRIPT = Path(__file__).parent.parent / "oracle" / "arbiter.py"


def test_arbiter_stub_rejects_all():
    payload = json.dumps({
        "task": {"id": "t1", "description": "test"},
        "winner_submission": {"id": "s1", "content": "winner content", "score": 0.9},
        "challenges": [
            {
                "id": "c1",
                "reason": "I am better",
                "challenger_submission": {"id": "s2", "content": "challenger content", "score": 0.85},
            },
            {
                "id": "c2",
                "reason": "Me too",
                "challenger_submission": {"id": "s3", "content": "another", "score": 0.7},
            },
        ],
    })
    result = subprocess.run(
        [sys.executable, str(ARBITER_SCRIPT)],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output["verdicts"]) == 2
    for v in output["verdicts"]:
        assert v["verdict"] == "rejected"
        assert v["score"] == 0
        assert "Stub arbiter" in v["feedback"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_arbiter_stub.py -v`
Expected: FAIL — file not found

**Step 3: Create arbiter stub**

创建 `oracle/arbiter.py`：

```python
#!/usr/bin/env python3
"""Arbiter stub — V1. Rejects all challenges."""
import json
import sys


def main():
    payload = json.loads(sys.stdin.read())
    challenges = payload.get("challenges", [])
    verdicts = []
    for c in challenges:
        verdicts.append({
            "challenge_id": c["id"],
            "verdict": "rejected",
            "score": 0,
            "feedback": "Stub arbiter: challenge rejected",
        })
    print(json.dumps({"verdicts": verdicts}))


if __name__ == "__main__":
    main()
```

**Step 4: Run test**

Run: `pytest tests/test_arbiter_stub.py -v`
Expected: PASS

**Step 5: Create arbiter service**

创建 `app/services/arbiter.py`：

```python
import json
import subprocess
import sys
from pathlib import Path
from sqlalchemy.orm import Session
from ..models import Challenge, Task, Submission, ChallengeVerdict, ChallengeStatus

ARBITER_SCRIPT = Path(__file__).parent.parent.parent / "oracle" / "arbiter.py"


def run_arbitration(db: Session, task_id: str) -> None:
    """Call arbiter for all pending challenges on a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    winner_sub = db.query(Submission).filter(
        Submission.id == task.winner_submission_id
    ).first()
    if not winner_sub:
        return

    challenges = db.query(Challenge).filter(
        Challenge.task_id == task_id,
        Challenge.status == ChallengeStatus.pending,
    ).all()
    if not challenges:
        return

    challenge_payloads = []
    for c in challenges:
        challenger_sub = db.query(Submission).filter(
            Submission.id == c.challenger_submission_id
        ).first()
        challenge_payloads.append({
            "id": c.id,
            "reason": c.reason,
            "challenger_submission": {
                "id": challenger_sub.id,
                "content": challenger_sub.content,
                "score": challenger_sub.score,
            } if challenger_sub else {},
        })

    payload = json.dumps({
        "task": {"id": task.id, "description": task.description},
        "winner_submission": {
            "id": winner_sub.id,
            "content": winner_sub.content,
            "score": winner_sub.score,
        },
        "challenges": challenge_payloads,
    })

    result = subprocess.run(
        [sys.executable, str(ARBITER_SCRIPT)],
        input=payload, capture_output=True, text=True, timeout=60,
    )
    output = json.loads(result.stdout)

    verdict_map = {v["challenge_id"]: v for v in output.get("verdicts", [])}
    for c in challenges:
        v = verdict_map.get(c.id)
        if v:
            c.verdict = ChallengeVerdict(v["verdict"])
            c.arbiter_score = v.get("score", 0)
            c.arbiter_feedback = v.get("feedback")
            c.status = ChallengeStatus.judged

    db.commit()
```

**Step 6: Commit**

```bash
git add oracle/arbiter.py app/services/arbiter.py tests/test_arbiter_stub.py
git commit -m "feat: add arbiter stub script and service"
```

---

### Task 5: Challenge API（挑战路由）

**Files:**
- Create: `app/routers/challenges.py`
- Modify: `app/main.py`
- Test: `tests/test_challenge_api.py` (Create)

**Step 1: Write the failing tests**

创建 `tests/test_challenge_api.py`：

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app.models import TaskStatus

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def make_quality_task(client, bounty=10.0):
    body = {
        "title": "Q", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future(),
        "publisher_id": "pub", "bounty": bounty,
        "challenge_duration": 7200,
    }
    with PAYMENT_MOCK:
        return client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()


def submit(client, task_id, worker_id, content="answer"):
    with patch("app.routers.submissions.invoke_oracle"):
        return client.post(
            f"/tasks/{task_id}/submissions",
            json={"worker_id": worker_id, "content": content},
        ).json()


def setup_challenge_window(client, task_id, winner_sub_id):
    """Manually set task to challenge_window state via direct DB manipulation."""
    from app.database import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())
    from app.models import Task
    task = db.query(Task).filter(Task.id == task_id).first()
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = winner_sub_id
    task.challenge_window_end = datetime.now(timezone.utc) + timedelta(hours=2)
    db.commit()


def test_create_challenge(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1", "winner content")
    s2 = submit(client, task["id"], "w2", "challenger content")

    # Score submissions via internal endpoint
    client.post(f"/internal/submissions/{s1['id']}/score", json={"score": 0.9})
    client.post(f"/internal/submissions/{s2['id']}/score", json={"score": 0.7})

    setup_challenge_window(client, task["id"], s1["id"])

    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "My solution handles edge cases better",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["challenger_submission_id"] == s2["id"]
    assert data["target_submission_id"] == s1["id"]
    assert data["status"] == "pending"
    assert data["verdict"] is None


def test_challenge_rejected_when_not_in_window(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    # Task is still 'open', not 'challenge_window'
    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "test",
    })
    assert resp.status_code == 400
    assert "challenge_window" in resp.json()["detail"]


def test_challenge_rejected_winner_cannot_challenge_self(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s1["id"],
        "reason": "challenging myself",
    })
    assert resp.status_code == 400
    assert "winner" in resp.json()["detail"].lower()


def test_challenge_rejected_submission_not_in_task(client):
    task1 = make_quality_task(client)
    task2 = make_quality_task(client)
    s1 = submit(client, task1["id"], "w1")
    s2 = submit(client, task2["id"], "w2")

    setup_challenge_window(client, task1["id"], s1["id"])

    resp = client.post(f"/tasks/{task1['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "wrong task",
    })
    assert resp.status_code == 400
    assert "not belong" in resp.json()["detail"].lower() or "not found" in resp.json()["detail"].lower()


def test_challenge_rejected_duplicate(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "first attempt",
    })
    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "second attempt",
    })
    assert resp.status_code == 400
    assert "already" in resp.json()["detail"].lower()


def test_list_challenges(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    s3 = submit(client, task["id"], "w3")

    setup_challenge_window(client, task["id"], s1["id"])

    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"], "reason": "r1"})
    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s3["id"], "reason": "r2"})

    resp = client.get(f"/tasks/{task['id']}/challenges")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_single_challenge(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    created = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"], "reason": "test"}).json()

    resp = client.get(f"/tasks/{task['id']}/challenges/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_challenge_api.py -v`
Expected: 404 — `/tasks/.../challenges` routes don't exist

**Step 3: Create challenge router**

创建 `app/routers/challenges.py`：

```python
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Task, Submission, Challenge, TaskStatus
from ..schemas import ChallengeCreate, ChallengeOut

router = APIRouter(tags=["challenges"])


@router.post("/tasks/{task_id}/challenges", response_model=ChallengeOut, status_code=201)
def create_challenge(
    task_id: str,
    data: ChallengeCreate,
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.challenge_window:
        raise HTTPException(status_code=400, detail="Task is not in challenge_window state")

    if task.challenge_window_end:
        end = task.challenge_window_end if task.challenge_window_end.tzinfo else task.challenge_window_end.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > end:
            raise HTTPException(status_code=400, detail="Challenge window has closed")

    # Verify challenger submission belongs to this task
    challenger_sub = db.query(Submission).filter(
        Submission.id == data.challenger_submission_id,
        Submission.task_id == task_id,
    ).first()
    if not challenger_sub:
        raise HTTPException(status_code=400, detail="Challenger submission not found in this task")

    # Cannot challenge yourself
    if data.challenger_submission_id == task.winner_submission_id:
        raise HTTPException(status_code=400, detail="Winner cannot challenge themselves")

    # Check for duplicate challenge by same worker
    existing = db.query(Challenge).filter(
        Challenge.task_id == task_id,
        Challenge.challenger_submission_id == data.challenger_submission_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already submitted a challenge for this task")

    challenge = Challenge(
        task_id=task_id,
        challenger_submission_id=data.challenger_submission_id,
        target_submission_id=task.winner_submission_id,
        reason=data.reason,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge


@router.get("/tasks/{task_id}/challenges", response_model=List[ChallengeOut])
def list_challenges(task_id: str, db: Session = Depends(get_db)):
    if not db.query(Task).filter(Task.id == task_id).first():
        raise HTTPException(status_code=404, detail="Task not found")
    return db.query(Challenge).filter(Challenge.task_id == task_id).all()


@router.get("/tasks/{task_id}/challenges/{challenge_id}", response_model=ChallengeOut)
def get_challenge(task_id: str, challenge_id: str, db: Session = Depends(get_db)):
    challenge = db.query(Challenge).filter(
        Challenge.id == challenge_id, Challenge.task_id == task_id
    ).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return challenge
```

**Step 4: Register router in main.py**

修改 `app/main.py`，添加：

```python
from .routers import challenges as challenges_router
```

并在 `app.include_router` 区域添加：

```python
app.include_router(challenges_router.router)
```

**Step 5: Run tests**

Run: `pytest tests/test_challenge_api.py -v`
Expected: All 7 tests PASS

Run: `pytest -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add app/routers/challenges.py app/main.py tests/test_challenge_api.py
git commit -m "feat: add challenge API endpoints with validation"
```

---

### Task 6: Scheduler 四阶段生命周期

**Files:**
- Modify: `app/scheduler.py`
- Test: `tests/test_quality_lifecycle.py` (Create)

**Step 1: Write the failing tests**

创建 `tests/test_quality_lifecycle.py`：

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, Challenge, User,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus, ChallengeVerdict,
    UserRole,
)


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_expired_quality_task(db, bounty=10.0):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(
        title="Q", description="d", type=TaskType.quality_first,
        max_revisions=3, deadline=past, bounty=bounty,
        submission_deposit=1.0, challenge_duration=7200,
    )
    db.add(task)
    db.flush()
    return task


def add_scored_submission(db, task_id, worker_id, score, content="c"):
    sub = Submission(
        task_id=task_id, worker_id=worker_id, revision=1,
        content=content, score=score, status=SubmissionStatus.scored,
        deposit=1.0,
    )
    db.add(sub)
    db.flush()
    return sub


# --- Phase 1: open → scoring ---

def test_phase1_open_to_scoring():
    db = make_db()
    task = make_expired_quality_task(db)
    add_scored_submission(db, task.id, "w1", 0.9)
    db.commit()

    from app.scheduler import quality_first_lifecycle
    quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.scoring


# --- Phase 2: scoring → challenge_window ---

def test_phase2_scoring_to_challenge_window():
    db = make_db()
    task = make_expired_quality_task(db)
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    s2 = add_scored_submission(db, task.id, "w2", 0.7)
    task.status = TaskStatus.scoring
    db.commit()

    from app.scheduler import quality_first_lifecycle
    quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.challenge_window
    assert task.winner_submission_id == s1.id
    assert task.challenge_window_end is not None


def test_phase2_no_submissions_closes():
    db = make_db()
    task = make_expired_quality_task(db)
    task.status = TaskStatus.scoring
    db.commit()

    from app.scheduler import quality_first_lifecycle
    quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id is None


# --- Phase 3: challenge_window → closed (no challenges) ---

def test_phase3_no_challenges_closes():
    db = make_db()
    task = make_expired_quality_task(db)
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = s1.id
    task.challenge_window_end = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    with patch("app.scheduler.pay_winner") as mock_pay:
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)
        mock_pay.assert_called_once_with(db, task.id)

    db.refresh(task)
    assert task.status == TaskStatus.closed


def test_phase3_with_challenges_goes_to_arbitrating():
    db = make_db()
    task = make_expired_quality_task(db)
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    s2 = add_scored_submission(db, task.id, "w2", 0.7)
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = s1.id
    task.challenge_window_end = datetime.now(timezone.utc) - timedelta(minutes=1)

    challenge = Challenge(
        task_id=task.id, challenger_submission_id=s2.id,
        target_submission_id=s1.id, reason="I am better",
    )
    db.add(challenge)
    db.commit()

    with patch("app.scheduler.run_arbitration") as mock_arb:
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)
        mock_arb.assert_called_once_with(db, task.id)

    db.refresh(task)
    assert task.status == TaskStatus.arbitrating


# --- Phase 3: deposit refund for non-challengers ---

def test_phase3_no_challenge_refunds_all_deposits():
    db = make_db()
    task = make_expired_quality_task(db)
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    s2 = add_scored_submission(db, task.id, "w2", 0.7)
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = s1.id
    task.challenge_window_end = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    with patch("app.scheduler.pay_winner"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(s1)
    db.refresh(s2)
    assert s1.deposit_returned == s1.deposit
    assert s2.deposit_returned == s2.deposit
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_quality_lifecycle.py -v`
Expected: ImportError — `quality_first_lifecycle` not found

**Step 3: Rewrite scheduler**

修改 `app/scheduler.py`：

```python
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from .models import (
    Task, Submission, Challenge,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus,
)
from .services.payout import pay_winner
from .services.arbiter import run_arbitration


def _refund_all_deposits(db: Session, task_id: str) -> None:
    """Refund all deposits for a task (no challenges scenario)."""
    submissions = db.query(Submission).filter(
        Submission.task_id == task_id,
        Submission.deposit.isnot(None),
    ).all()
    for sub in submissions:
        if sub.deposit_returned is None:
            sub.deposit_returned = sub.deposit


def quality_first_lifecycle(db: Optional[Session] = None) -> None:
    """Push quality_first tasks through their 4-phase lifecycle."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Phase 1: open → scoring (deadline expired)
        expired_open = (
            db.query(Task)
            .filter(
                Task.type == TaskType.quality_first,
                Task.status == TaskStatus.open,
                Task.deadline <= now,
            )
            .all()
        )
        for task in expired_open:
            task.status = TaskStatus.scoring
        if expired_open:
            db.commit()

        # Phase 2: scoring → challenge_window (all submissions scored)
        scoring_tasks = (
            db.query(Task)
            .filter(Task.type == TaskType.quality_first, Task.status == TaskStatus.scoring)
            .all()
        )
        for task in scoring_tasks:
            pending_count = db.query(Submission).filter(
                Submission.task_id == task.id,
                Submission.status == SubmissionStatus.pending,
            ).count()
            if pending_count > 0:
                continue  # Still waiting for Oracle

            best = (
                db.query(Submission)
                .filter(Submission.task_id == task.id, Submission.score.isnot(None))
                .order_by(Submission.score.desc())
                .first()
            )
            if best:
                task.winner_submission_id = best.id
                duration = task.challenge_duration or 7200
                task.challenge_window_end = now + timedelta(seconds=duration)
                task.status = TaskStatus.challenge_window
            else:
                task.status = TaskStatus.closed
        if scoring_tasks:
            db.commit()

        # Phase 3: challenge_window → arbitrating or closed
        expired_window = (
            db.query(Task)
            .filter(
                Task.type == TaskType.quality_first,
                Task.status == TaskStatus.challenge_window,
                Task.challenge_window_end <= now,
            )
            .all()
        )
        for task in expired_window:
            challenge_count = db.query(Challenge).filter(
                Challenge.task_id == task.id
            ).count()
            if challenge_count == 0:
                _refund_all_deposits(db, task.id)
                task.status = TaskStatus.closed
                db.commit()
                pay_winner(db, task.id)
            else:
                task.status = TaskStatus.arbitrating
                db.commit()
                run_arbitration(db, task.id)

        # Phase 4: arbitrating → closed (all challenges judged)
        arbitrating_tasks = (
            db.query(Task)
            .filter(Task.type == TaskType.quality_first, Task.status == TaskStatus.arbitrating)
            .all()
        )
        for task in arbitrating_tasks:
            pending_challenges = db.query(Challenge).filter(
                Challenge.task_id == task.id,
                Challenge.status == ChallengeStatus.pending,
            ).count()
            if pending_challenges > 0:
                continue

            _settle_after_arbitration(db, task)

    finally:
        if own_session:
            db.close()


def _settle_after_arbitration(db: Session, task: Task) -> None:
    """Settle a task after all challenges are judged."""
    from .models import ChallengeVerdict, User
    challenges = db.query(Challenge).filter(Challenge.task_id == task.id).all()

    # Process deposits and credit scores
    for c in challenges:
        challenger_sub = db.query(Submission).filter(
            Submission.id == c.challenger_submission_id
        ).first()
        # Find the worker user for credit score updates
        worker = db.query(User).filter(
            User.id == challenger_sub.worker_id
        ).first() if challenger_sub else None

        if c.verdict == ChallengeVerdict.upheld:
            if challenger_sub and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = challenger_sub.deposit
            if worker:
                worker.credit_score = round(worker.credit_score + 5, 2)

        elif c.verdict == ChallengeVerdict.rejected:
            if challenger_sub and challenger_sub.deposit is not None and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = round(challenger_sub.deposit * 0.70, 6)
            # credit_score unchanged

        elif c.verdict == ChallengeVerdict.malicious:
            if challenger_sub and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = 0
            if worker:
                worker.credit_score = round(worker.credit_score - 20, 2)

    # Determine final winner
    upheld = [c for c in challenges if c.verdict == ChallengeVerdict.upheld]
    if upheld:
        best = max(upheld, key=lambda c: c.arbiter_score or 0)
        task.winner_submission_id = best.challenger_submission_id

    # Refund non-challenger deposits
    all_subs = db.query(Submission).filter(
        Submission.task_id == task.id,
        Submission.deposit.isnot(None),
        Submission.deposit_returned.is_(None),
    ).all()
    for sub in all_subs:
        sub.deposit_returned = sub.deposit

    task.status = TaskStatus.closed
    db.commit()
    pay_winner(db, task.id)


def settle_expired_quality_first(db: Optional[Session] = None) -> None:
    """Legacy wrapper — now calls quality_first_lifecycle."""
    quality_first_lifecycle(db=db)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(quality_first_lifecycle, "interval", minutes=1)
    return scheduler
```

**Step 4: Run tests**

Run: `pytest tests/test_quality_lifecycle.py -v`
Expected: All 6 tests PASS

Run: `pytest tests/test_scheduler.py -v`
Expected: All 5 existing scheduler tests PASS (backward compatible via `settle_expired_quality_first` wrapper — note: some tests may need small updates since tasks now go to `scoring` instead of directly `closed`; see Step 5)

**Step 5: Fix existing scheduler tests if needed**

The existing `test_settle_picks_highest_score` expects `open → closed` directly. Now the flow is `open → scoring → challenge_window → closed`. Update existing scheduler tests to account for multi-phase lifecycle by calling `quality_first_lifecycle` multiple times or by setting initial status to later phases.

修改 `tests/test_scheduler.py` 中需要调整的测试。将已评分的任务设置初始状态为 `scoring`（模拟 Phase 1 已完成），或多次调用 lifecycle 函数。最简单的方式：将 `settle_expired_quality_first` 调用替换为多次 `quality_first_lifecycle` 调用。

**Step 6: Run all tests**

Run: `pytest -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add app/scheduler.py tests/test_quality_lifecycle.py tests/test_scheduler.py
git commit -m "feat: implement 4-phase quality_first lifecycle in scheduler"
```

---

### Task 7: 仲裁结算逻辑测试

**Files:**
- Test: `tests/test_arbitration.py` (Create)

**Step 1: Write the tests**

创建 `tests/test_arbitration.py`：

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, Challenge, User,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus, ChallengeVerdict,
    UserRole, PayoutStatus,
)


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def setup_arbitrating_task(db):
    """Create a task in arbitrating state with 2 submissions and 1 challenge."""
    user_w1 = User(nickname="w1", wallet="0xaaa", role=UserRole.worker)
    user_w2 = User(nickname="w2", wallet="0xbbb", role=UserRole.worker)
    db.add_all([user_w1, user_w2])
    db.flush()

    task = Task(
        title="Q", description="d", type=TaskType.quality_first,
        max_revisions=3, deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        bounty=10.0, submission_deposit=1.0, challenge_duration=7200,
        status=TaskStatus.arbitrating,
    )
    db.add(task)
    db.flush()

    s1 = Submission(
        task_id=task.id, worker_id=user_w1.id, revision=1,
        content="winner", score=0.9, status=SubmissionStatus.scored, deposit=1.0,
    )
    s2 = Submission(
        task_id=task.id, worker_id=user_w2.id, revision=1,
        content="challenger", score=0.7, status=SubmissionStatus.scored, deposit=1.0,
    )
    db.add_all([s1, s2])
    db.flush()
    task.winner_submission_id = s1.id

    challenge = Challenge(
        task_id=task.id, challenger_submission_id=s2.id,
        target_submission_id=s1.id, reason="I am better",
    )
    db.add(challenge)
    db.commit()
    return task, s1, s2, challenge, user_w1, user_w2


def test_settle_upheld_changes_winner():
    db = make_db()
    task, s1, s2, challenge, w1, w2 = setup_arbitrating_task(db)

    # Manually judge the challenge as upheld
    challenge.verdict = ChallengeVerdict.upheld
    challenge.arbiter_score = 0.95
    challenge.status = ChallengeStatus.judged
    db.commit()

    with patch("app.scheduler.pay_winner") as mock_pay:
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)
        mock_pay.assert_called_once()

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == s2.id  # Challenger took over

    db.refresh(s2)
    assert s2.deposit_returned == s2.deposit  # Full refund

    db.refresh(w2)
    assert w2.credit_score == 105.0  # +5


def test_settle_rejected_deducts_deposit():
    db = make_db()
    task, s1, s2, challenge, w1, w2 = setup_arbitrating_task(db)

    challenge.verdict = ChallengeVerdict.rejected
    challenge.status = ChallengeStatus.judged
    db.commit()

    with patch("app.scheduler.pay_winner"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == s1.id  # Original winner stays

    db.refresh(s2)
    assert s2.deposit_returned == 0.70  # 70% returned

    db.refresh(w2)
    assert w2.credit_score == 100.0  # unchanged


def test_settle_malicious_confiscates_deposit_and_credit():
    db = make_db()
    task, s1, s2, challenge, w1, w2 = setup_arbitrating_task(db)

    challenge.verdict = ChallengeVerdict.malicious
    challenge.status = ChallengeStatus.judged
    db.commit()

    with patch("app.scheduler.pay_winner"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == s1.id  # Original winner stays

    db.refresh(s2)
    assert s2.deposit_returned == 0  # Confiscated

    db.refresh(w2)
    assert w2.credit_score == 80.0  # -20


def test_settle_multiple_upheld_picks_highest():
    db = make_db()
    user_w1 = User(nickname="w1", wallet="0xaaa", role=UserRole.worker)
    user_w2 = User(nickname="w2", wallet="0xbbb", role=UserRole.worker)
    user_w3 = User(nickname="w3", wallet="0xccc", role=UserRole.worker)
    db.add_all([user_w1, user_w2, user_w3])
    db.flush()

    task = Task(
        title="Q", description="d", type=TaskType.quality_first,
        max_revisions=3, deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        bounty=10.0, submission_deposit=1.0,
        status=TaskStatus.arbitrating,
    )
    db.add(task)
    db.flush()

    s1 = Submission(task_id=task.id, worker_id=user_w1.id, revision=1,
                    content="a", score=0.9, status=SubmissionStatus.scored, deposit=1.0)
    s2 = Submission(task_id=task.id, worker_id=user_w2.id, revision=1,
                    content="b", score=0.7, status=SubmissionStatus.scored, deposit=1.0)
    s3 = Submission(task_id=task.id, worker_id=user_w3.id, revision=1,
                    content="c", score=0.8, status=SubmissionStatus.scored, deposit=1.0)
    db.add_all([s1, s2, s3])
    db.flush()
    task.winner_submission_id = s1.id

    c1 = Challenge(task_id=task.id, challenger_submission_id=s2.id,
                   target_submission_id=s1.id, reason="r1",
                   verdict=ChallengeVerdict.upheld, arbiter_score=0.88,
                   status=ChallengeStatus.judged)
    c2 = Challenge(task_id=task.id, challenger_submission_id=s3.id,
                   target_submission_id=s1.id, reason="r2",
                   verdict=ChallengeVerdict.upheld, arbiter_score=0.95,
                   status=ChallengeStatus.judged)
    db.add_all([c1, c2])
    db.commit()

    with patch("app.scheduler.pay_winner"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.winner_submission_id == s3.id  # w3 had higher arbiter_score


def test_non_challengers_get_full_refund():
    db = make_db()
    task, s1, s2, challenge, w1, w2 = setup_arbitrating_task(db)

    # Add a third non-challenging worker
    user_w3 = User(nickname="w3", wallet="0xccc", role=UserRole.worker)
    db.add(user_w3)
    db.flush()
    s3 = Submission(task_id=task.id, worker_id=user_w3.id, revision=1,
                    content="passive", score=0.5, status=SubmissionStatus.scored, deposit=1.0)
    db.add(s3)

    challenge.verdict = ChallengeVerdict.rejected
    challenge.status = ChallengeStatus.judged
    db.commit()

    with patch("app.scheduler.pay_winner"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(s1)
    db.refresh(s3)
    assert s1.deposit_returned == s1.deposit  # Winner: full refund
    assert s3.deposit_returned == s3.deposit  # Non-challenger: full refund
```

**Step 2: Run tests**

Run: `pytest tests/test_arbitration.py -v`
Expected: All 5 tests PASS

**Step 3: Commit**

```bash
git add tests/test_arbitration.py
git commit -m "test: add arbitration settlement tests"
```

---

### Task 8: 内部仲裁端点 + 集成测试

**Files:**
- Modify: `app/routers/internal.py`
- Test: `tests/test_challenge_integration.py` (Create)

**Step 1: Write the failing test**

创建 `tests/test_challenge_integration.py`：

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app.models import TaskStatus

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_manual_arbitrate_endpoint(client):
    """Test POST /internal/tasks/{id}/arbitrate triggers arbiter."""
    # Create task
    with PAYMENT_MOCK:
        task = client.post("/tasks", json={
            "title": "Q", "description": "d", "type": "quality_first",
            "max_revisions": 3, "deadline": future(),
            "publisher_id": "pub", "bounty": 10.0,
            "challenge_duration": 7200,
        }, headers=PAYMENT_HEADERS).json()

    # Submit
    with patch("app.routers.submissions.invoke_oracle"):
        s1 = client.post(f"/tasks/{task['id']}/submissions",
                         json={"worker_id": "w1", "content": "a"}).json()
        s2 = client.post(f"/tasks/{task['id']}/submissions",
                         json={"worker_id": "w2", "content": "b"}).json()

    # Score
    client.post(f"/internal/submissions/{s1['id']}/score", json={"score": 0.9})
    client.post(f"/internal/submissions/{s2['id']}/score", json={"score": 0.7})

    # Manually set to challenge_window
    from app.database import get_db
    from app.main import app
    from app.models import Task
    db = next(app.dependency_overrides[get_db]())
    t = db.query(Task).filter(Task.id == task["id"]).first()
    t.status = TaskStatus.challenge_window
    t.winner_submission_id = s1["id"]
    t.challenge_window_end = datetime.now(timezone.utc) + timedelta(hours=2)
    db.commit()

    # Create challenge
    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "I am better",
    })
    assert resp.status_code == 201

    # Set to arbitrating
    t.status = TaskStatus.arbitrating
    db.commit()

    # Trigger manual arbitration
    resp = client.post(f"/internal/tasks/{task['id']}/arbitrate")
    assert resp.status_code == 200

    # Check challenge is judged (stub always rejects)
    challenges = client.get(f"/tasks/{task['id']}/challenges").json()
    assert len(challenges) == 1
    assert challenges[0]["status"] == "judged"
    assert challenges[0]["verdict"] == "rejected"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_challenge_integration.py -v`
Expected: 404 or 405 — `/internal/tasks/.../arbitrate` doesn't exist

**Step 3: Add arbitrate endpoint to internal router**

修改 `app/routers/internal.py`，添加：

```python
from ..services.arbiter import run_arbitration

@router.post("/tasks/{task_id}/arbitrate")
def trigger_arbitration(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.arbitrating:
        raise HTTPException(status_code=400, detail="Task is not in arbitrating state")
    run_arbitration(db, task_id)
    return {"ok": True}
```

需要在文件顶部导入中添加 `TaskStatus`（已有）和 `run_arbitration`。

**Step 4: Run tests**

Run: `pytest tests/test_challenge_integration.py -v`
Expected: PASS

Run: `pytest -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add app/routers/internal.py tests/test_challenge_integration.py
git commit -m "feat: add manual arbitration endpoint + integration test"
```

---

### Task 9: 修复现有 scheduler 测试兼容性

**Files:**
- Modify: `tests/test_scheduler.py`

**Step 1: Update existing scheduler tests**

现有 scheduler 测试期望 `open → closed` 一步到位。现在 quality_first 走四阶段流程。有两种修复方式：

1. 对于需要完整生命周期的测试：多次调用 `quality_first_lifecycle`
2. 对于只测某一阶段的测试：设置初始状态为该阶段的前一状态

修改 `tests/test_scheduler.py`：

- `test_settle_picks_highest_score`：设置初始 task.status 为 `scoring`，使其在一次 lifecycle 调用后进入 `challenge_window`，再设置 `challenge_window_end` 为过去时间后再调用一次进入 `closed`
- `test_settle_closes_with_no_scored_submissions`：设置为 `scoring`，调用一次 lifecycle 应直接 `closed`
- `test_settle_triggers_payout`：类似调整

**Step 2: Run tests**

Run: `pytest tests/test_scheduler.py -v`
Expected: All 5 tests PASS

Run: `pytest -v`
Expected: ALL tests PASS

**Step 3: Commit**

```bash
git add tests/test_scheduler.py
git commit -m "fix: update scheduler tests for 4-phase lifecycle"
```

---

### Task 10: 全量测试 + 最终验证

**Step 1: Run all backend tests**

Run: `pytest -v`
Expected: All tests PASS (original 53 + new tests)

**Step 2: Run frontend tests**

Run: `cd frontend && npm test`
Expected: All 19 tests PASS (frontend unchanged)

**Step 3: Start dev server and smoke test**

Run: `uvicorn app.main:app --reload --port 8000`
Verify: `http://localhost:8000/docs` shows new endpoints

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: V7 challenge mechanism for quality_first complete"
```
