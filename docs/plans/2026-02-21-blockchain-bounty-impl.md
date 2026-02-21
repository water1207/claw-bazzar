# Blockchain Bounty System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add user registration (nickname + wallet), x402 bounty collection on task creation (USDC on Base Sepolia), and automatic payout to winners (80% bounty via web3.py USDC transfer).

**Architecture:** Users register with nickname + EVM wallet. `POST /tasks` requires an x402 payment header; the server verifies via facilitator, then creates the task. When a winner is determined (fastest_first threshold or quality_first deadline), the platform signs a USDC transfer for 80% of the bounty to the winner's wallet. All blockchain interactions are mocked in tests.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy (SQLite), web3.py ≥ 7.0, fastapi-x402, pytest + httpx

---

### Task 1: Add New Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Update `pyproject.toml` dependencies**

Add `web3` and `fastapi-x402` to the main dependencies:

```toml
[project]
name = "claw-bazzar"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.0",
    "apscheduler>=3.10.0",
    "web3>=7.0.0",
    "fastapi-x402>=0.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["setuptools>=70.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["app*", "oracle*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: Install updated dependencies**

```bash
pip install -e ".[dev]"
```

Expected: no errors, `web3` and `fastapi-x402` installed.

**Step 3: Verify imports**

```bash
python -c "import web3; from fastapi_x402 import init_x402, pay; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add web3 and fastapi-x402 dependencies"
```

---

### Task 2: User Model & Registration Router

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Create: `app/routers/users.py`
- Create: `tests/test_users.py`

**Step 1: Write the failing test**

`tests/test_users.py`:
```python
def test_register_user(client):
    resp = client.post("/users", json={
        "nickname": "alice",
        "wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "role": "publisher",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["nickname"] == "alice"
    assert data["wallet"] == "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"
    assert data["role"] == "publisher"
    assert data["id"] is not None


def test_register_duplicate_nickname(client):
    client.post("/users", json={
        "nickname": "bob", "wallet": "0xaaa", "role": "worker"
    })
    resp = client.post("/users", json={
        "nickname": "bob", "wallet": "0xbbb", "role": "worker"
    })
    assert resp.status_code == 400
    assert "nickname" in resp.json()["detail"].lower()


def test_get_user(client):
    create = client.post("/users", json={
        "nickname": "carol", "wallet": "0xccc", "role": "both"
    }).json()
    resp = client.get(f"/users/{create['id']}")
    assert resp.status_code == 200
    assert resp.json()["nickname"] == "carol"


def test_get_user_not_found(client):
    resp = client.get("/users/nonexistent")
    assert resp.status_code == 404
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_users.py -v
```

Expected: `FAILED`

**Step 3: Add `UserRole` enum and `User` model to `app/models.py`**

Add after the existing `SubmissionStatus` enum:

```python
class UserRole(str, PyEnum):
    publisher = "publisher"
    worker = "worker"
    both = "both"
```

Add after the `Submission` class:

```python
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    nickname = Column(String, nullable=False, unique=True)
    wallet = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
```

**Step 4: Add schemas to `app/schemas.py`**

Add at the end (before `TaskDetail.model_rebuild()`):

```python
from .models import UserRole


class UserCreate(BaseModel):
    nickname: str
    wallet: str
    role: UserRole


class UserOut(BaseModel):
    id: str
    nickname: str
    wallet: str
    role: UserRole
    created_at: datetime

    model_config = {"from_attributes": True}
```

**Step 5: Create `app/routers/users.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..schemas import UserCreate, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserOut, status_code=201)
def register_user(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.nickname == data.nickname).first()
    if existing:
        raise HTTPException(status_code=400, detail="Nickname already taken")
    user = User(**data.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
```

**Step 6: Register users router in `app/main.py`**

Add import and registration:
```python
from .routers import users as users_router
app.include_router(users_router.router)
```

**Step 7: Run tests to verify they pass**

```bash
pytest tests/test_users.py -v
```

Expected: all 4 tests `PASSED`

**Step 8: Run full test suite to check no regressions**

```bash
pytest -v
```

Expected: all tests `PASSED` (26 existing + 4 new = 30)

**Step 9: Commit**

```bash
git add app/models.py app/schemas.py app/routers/users.py app/main.py tests/test_users.py
git commit -m "feat: user registration with nickname and wallet"
```

---

### Task 3: Add Bounty & Payout Fields to Task Model

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Create: `tests/test_bounty_model.py`

**Step 1: Write the failing test**

`tests/test_bounty_model.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta, timezone


def test_task_has_bounty_and_payout_fields():
    from app.database import Base
    from app.models import Task, TaskType, PayoutStatus

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    task = Task(
        title="Bounty task",
        description="A task with bounty",
        type=TaskType.fastest_first,
        threshold=0.8,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        publisher_id="pub-1",
        bounty=5.0,
    )
    db.add(task)
    db.commit()

    assert task.bounty == 5.0
    assert task.publisher_id == "pub-1"
    assert task.payout_status == PayoutStatus.pending
    assert task.payout_tx_hash is None
    assert task.payout_amount is None
    assert task.payment_tx_hash is None

    db.close()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_bounty_model.py -v
```

Expected: `FAILED`

**Step 3: Add `PayoutStatus` enum and new fields to `app/models.py`**

Add enum after `SubmissionStatus`:

```python
class PayoutStatus(str, PyEnum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
```

Add new columns to the `Task` class (after `winner_submission_id`):

```python
    publisher_id = Column(String, nullable=True)          # FK → User.id (app-enforced)
    bounty = Column(Float, nullable=True)                 # USDC amount
    payment_tx_hash = Column(String, nullable=True)       # x402 incoming payment tx
    payout_status = Column(Enum(PayoutStatus), nullable=False, default=PayoutStatus.pending)
    payout_tx_hash = Column(String, nullable=True)        # outgoing payout tx
    payout_amount = Column(Float, nullable=True)          # actual amount paid to winner
```

**Step 4: Update schemas in `app/schemas.py`**

Update `TaskCreate` — add `bounty` and `publisher_id`:

```python
class TaskCreate(BaseModel):
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: datetime
    publisher_id: str
    bounty: float
```

Update `TaskOut` — add new fields:

```python
from .models import TaskType, TaskStatus, SubmissionStatus, PayoutStatus

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
    payout_status: PayoutStatus
    payout_tx_hash: Optional[str] = None
    payout_amount: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_bounty_model.py -v
```

Expected: `PASSED`

**Step 6: Fix existing tests**

The existing tests in `tests/test_tasks.py`, `tests/test_submissions.py`, `tests/test_internal.py`, and `tests/test_integration.py` create tasks without `publisher_id` and `bounty`. Update them to include these fields.

In each test helper that creates tasks, add `"publisher_id": "test-pub"` and `"bounty": 1.0` to the JSON body. For example, in `tests/test_tasks.py`, update the `future()` test calls:

```python
def test_create_task(client):
    resp = client.post("/tasks", json={
        "title": "Write haiku",
        "description": "Write a haiku about the sea",
        "type": "fastest_first",
        "threshold": 0.8,
        "deadline": future(),
        "publisher_id": "test-pub",
        "bounty": 5.0,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Write haiku"
    assert data["status"] == "open"
    assert data["bounty"] == 5.0
    assert data["payout_status"] == "pending"
```

Apply the same pattern to all task creation calls in:
- `tests/test_tasks.py` — all 5 tests
- `tests/test_submissions.py` — the `make_task()` helper
- `tests/test_internal.py` — the `make_task_and_submission()` helper
- `tests/test_integration.py` — all task creation calls

**Step 7: Run full test suite**

```bash
pytest -v
```

Expected: all tests `PASSED`

**Step 8: Commit**

```bash
git add app/models.py app/schemas.py tests/test_bounty_model.py tests/test_tasks.py tests/test_submissions.py tests/test_internal.py tests/test_integration.py
git commit -m "feat: add bounty and payout fields to task model"
```

---

### Task 4: x402 Payment Service

**Files:**
- Create: `app/services/x402.py`
- Create: `tests/test_x402_service.py`

**Step 1: Write the failing test**

`tests/test_x402_service.py`:
```python
import pytest
from unittest.mock import patch, MagicMock


def test_build_payment_requirements():
    from app.services.x402 import build_payment_requirements

    req = build_payment_requirements(bounty=5.0)
    assert req["amount"] == "5.0"
    assert req["network"] is not None
    assert req["asset"] is not None
    assert req["pay_to"] is not None


def test_verify_payment_valid():
    from app.services.x402 import verify_payment

    with patch("app.services.x402._facilitator_verify") as mock_verify:
        mock_verify.return_value = {"valid": True, "tx_hash": "0xabc123"}
        result = verify_payment("valid-payment-header", bounty=5.0)
    assert result["valid"] is True
    assert result["tx_hash"] == "0xabc123"


def test_verify_payment_invalid():
    from app.services.x402 import verify_payment

    with patch("app.services.x402._facilitator_verify") as mock_verify:
        mock_verify.return_value = {"valid": False, "tx_hash": None}
        result = verify_payment("bad-payment-header", bounty=5.0)
    assert result["valid"] is False


def test_verify_payment_missing_header():
    from app.services.x402 import verify_payment

    result = verify_payment(None, bounty=5.0)
    assert result["valid"] is False
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_x402_service.py -v
```

Expected: `FAILED — ModuleNotFoundError`

**Step 3: Implement `app/services/x402.py`**

```python
import os
import httpx

FACILITATOR_URL = os.environ.get("FACILITATOR_URL", "https://x402.org/facilitator")
PLATFORM_WALLET = os.environ.get("PLATFORM_WALLET", "0x0000000000000000000000000000000000000000")
X402_NETWORK = os.environ.get("X402_NETWORK", "base-sepolia")
USDC_CONTRACT = os.environ.get("USDC_CONTRACT", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")


def build_payment_requirements(bounty: float) -> dict:
    """Build x402 payment requirements for a given bounty amount."""
    return {
        "amount": str(bounty),
        "network": X402_NETWORK,
        "asset": USDC_CONTRACT,
        "pay_to": PLATFORM_WALLET,
    }


def _facilitator_verify(payment_header: str, requirements: dict) -> dict:
    """Call the x402 facilitator to verify a payment. Separated for easy mocking."""
    try:
        resp = httpx.post(
            f"{FACILITATOR_URL}/verify",
            json={"payment": payment_header, "requirements": requirements},
            timeout=30,
        )
        data = resp.json()
        return {"valid": data.get("valid", False), "tx_hash": data.get("tx_hash")}
    except Exception:
        return {"valid": False, "tx_hash": None}


def verify_payment(payment_header: str | None, bounty: float) -> dict:
    """Verify an x402 payment header for a given bounty amount.
    Returns {"valid": bool, "tx_hash": str | None}.
    """
    if not payment_header:
        return {"valid": False, "tx_hash": None}

    requirements = build_payment_requirements(bounty)
    return _facilitator_verify(payment_header, requirements)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_x402_service.py -v
```

Expected: all 4 tests `PASSED`

**Step 5: Commit**

```bash
git add app/services/x402.py tests/test_x402_service.py
git commit -m "feat: x402 payment verification service"
```

---

### Task 5: Integrate x402 Into Tasks Router

**Files:**
- Modify: `app/routers/tasks.py`
- Modify: `tests/test_tasks.py`

**Step 1: Write the failing test**

Add to `tests/test_tasks.py`:

```python
from unittest.mock import patch


def test_create_task_returns_402_without_payment(client):
    resp = client.post("/tasks", json={
        "title": "Paid task", "description": "d", "type": "fastest_first",
        "threshold": 0.8, "deadline": future(),
        "publisher_id": "test-pub", "bounty": 5.0,
    })
    assert resp.status_code == 402
    data = resp.json()
    assert data["amount"] == "5.0"
    assert "pay_to" in data


def test_create_task_with_valid_payment(client):
    with patch("app.routers.tasks.verify_payment") as mock_verify:
        mock_verify.return_value = {"valid": True, "tx_hash": "0xabc123"}
        resp = client.post("/tasks", json={
            "title": "Paid task", "description": "d", "type": "fastest_first",
            "threshold": 0.8, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 5.0,
        }, headers={"X-PAYMENT": "valid-payment"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["bounty"] == 5.0
    assert data["payment_tx_hash"] == "0xabc123"


def test_create_task_with_invalid_payment(client):
    with patch("app.routers.tasks.verify_payment") as mock_verify:
        mock_verify.return_value = {"valid": False, "tx_hash": None}
        resp = client.post("/tasks", json={
            "title": "Paid task", "description": "d", "type": "fastest_first",
            "threshold": 0.8, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 5.0,
        }, headers={"X-PAYMENT": "bad-payment"})
    assert resp.status_code == 402
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tasks.py::test_create_task_returns_402_without_payment tests/test_tasks.py::test_create_task_with_valid_payment tests/test_tasks.py::test_create_task_with_invalid_payment -v
```

Expected: `FAILED`

**Step 3: Update `app/routers/tasks.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..models import Task, TaskStatus, TaskType, Submission
from ..schemas import TaskCreate, TaskOut, TaskDetail, SubmissionOut
from ..services.x402 import build_payment_requirements, verify_payment

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, request: Request, db: Session = Depends(get_db)):
    payment_header = request.headers.get("x-payment")

    if not payment_header:
        requirements = build_payment_requirements(data.bounty)
        return JSONResponse(status_code=402, content=requirements)

    result = verify_payment(payment_header, data.bounty)
    if not result["valid"]:
        requirements = build_payment_requirements(data.bounty)
        return JSONResponse(status_code=402, content=requirements)

    task = Task(**data.model_dump(), payment_tx_hash=result.get("tx_hash"))
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=List[TaskOut])
def list_tasks(
    status: Optional[TaskStatus] = None,
    type: Optional[TaskType] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    if type:
        q = q.filter(Task.type == type)
    return q.order_by(Task.created_at.desc()).all()


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    subs = db.query(Submission).filter(Submission.task_id == task_id).all()
    result = TaskDetail.model_validate(task)
    result.submissions = [SubmissionOut.model_validate(s) for s in subs]
    return result
```

**Step 4: Update existing tests to include X-PAYMENT header**

All existing tests that create tasks (in `test_tasks.py`, `test_submissions.py`, `test_internal.py`, `test_integration.py`) must now either:
- Include the `X-PAYMENT` header, OR
- Mock `verify_payment` to return valid

The simplest approach: add a helper and mock `verify_payment` in each test that creates tasks. Update `tests/conftest.py` to add a fixture:

```python
@pytest.fixture(autouse=True)
def mock_x402(client):
    """Auto-mock x402 payment verification for all tests."""
    with patch("app.routers.tasks.verify_payment", return_value={"valid": True, "tx_hash": "0xtest"}):
        yield
```

Wait — this won't work with `autouse` because of fixture ordering. Instead, update the `client` fixture or add the mock to each test file's task-creation helper.

The cleanest approach: create a helper in `tests/conftest.py`:

```python
@pytest.fixture
def paid_client(client):
    """Client that auto-passes x402 payment verification."""
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xtest"}):
        yield client
```

Then update existing tests:
- Tests that don't need payment testing: use `paid_client` instead of `client`
- Tests that test payment flow: keep using `client` with explicit mocking

For simplicity, update existing test files to mock `verify_payment` in task-creation helpers. For each file:

In `tests/test_submissions.py`, update `make_task()`:
```python
def make_task(client, type="fastest_first", threshold=0.8, max_revisions=None):
    body = {"title": "T", "description": "d", "type": type,
            "threshold": threshold, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0}
    if max_revisions:
        body["max_revisions"] = max_revisions
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xtest"}):
        return client.post("/tasks", json=body,
                          headers={"X-PAYMENT": "test"}).json()
```

Apply the same pattern in `tests/test_internal.py` `make_task_and_submission()`, and in all task creation calls in `tests/test_integration.py`.

In `tests/test_tasks.py`, update the existing `test_create_task`, `test_list_tasks`, `test_list_tasks_filter_by_type`, and `test_get_task_detail` to mock payment:

```python
from unittest.mock import patch

def _create_task(client, **overrides):
    body = {"title": "T", "description": "d", "type": "fastest_first",
            "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0, **overrides}
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xtest"}):
        return client.post("/tasks", json=body, headers={"X-PAYMENT": "test"})
```

**Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests `PASSED`

**Step 6: Commit**

```bash
git add app/routers/tasks.py tests/test_tasks.py tests/test_submissions.py tests/test_internal.py tests/test_integration.py tests/conftest.py
git commit -m "feat: integrate x402 payment into task creation"
```

---

### Task 6: Payout Service (web3.py USDC Transfer)

**Files:**
- Create: `app/services/payout.py`
- Create: `tests/test_payout_service.py`

**Step 1: Write the failing test**

`tests/test_payout_service.py`:
```python
import os
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta, timezone


def make_db():
    from app.database import Base
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def test_pay_winner_calculates_80_percent():
    from app.models import Task, Submission, User, TaskType, TaskStatus, SubmissionStatus, PayoutStatus
    Session = make_db()
    db = Session()

    user = User(nickname="winner1", wallet="0xWINNER", role="worker")
    db.add(user)
    db.flush()

    task = Task(
        title="T", description="d", type=TaskType.fastest_first,
        threshold=0.8, deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        status=TaskStatus.closed, publisher_id="pub-1", bounty=10.0,
        winner_submission_id="sub-1",
    )
    db.add(task)
    db.flush()

    sub = Submission(
        id="sub-1", task_id=task.id, worker_id=user.id,
        revision=1, content="answer", score=0.9, status=SubmissionStatus.scored,
    )
    db.add(sub)
    db.commit()

    with patch("app.services.payout._send_usdc_transfer") as mock_send:
        mock_send.return_value = "0xPAYOUT_TX"
        from app.services.payout import pay_winner
        pay_winner(db, task.id)

    db.refresh(task)
    assert task.payout_status == PayoutStatus.paid
    assert task.payout_tx_hash == "0xPAYOUT_TX"
    assert task.payout_amount == 8.0  # 10.0 * 0.80
    mock_send.assert_called_once_with("0xWINNER", 8.0)
    db.close()


def test_pay_winner_handles_transfer_failure():
    from app.models import Task, Submission, User, TaskType, TaskStatus, SubmissionStatus, PayoutStatus
    Session = make_db()
    db = Session()

    user = User(nickname="winner2", wallet="0xWINNER2", role="worker")
    db.add(user)
    db.flush()

    task = Task(
        title="T", description="d", type=TaskType.fastest_first,
        threshold=0.8, deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        status=TaskStatus.closed, publisher_id="pub-1", bounty=5.0,
        winner_submission_id="sub-2",
    )
    db.add(task)
    db.flush()

    sub = Submission(
        id="sub-2", task_id=task.id, worker_id=user.id,
        revision=1, content="answer", score=0.9, status=SubmissionStatus.scored,
    )
    db.add(sub)
    db.commit()

    with patch("app.services.payout._send_usdc_transfer") as mock_send:
        mock_send.side_effect = Exception("RPC error")
        from app.services.payout import pay_winner
        pay_winner(db, task.id)

    db.refresh(task)
    assert task.payout_status == PayoutStatus.failed
    assert task.payout_tx_hash is None
    db.close()


def test_pay_winner_skips_if_no_winner():
    from app.models import Task, TaskType, TaskStatus, PayoutStatus
    Session = make_db()
    db = Session()

    task = Task(
        title="T", description="d", type=TaskType.fastest_first,
        threshold=0.8, deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        status=TaskStatus.closed, publisher_id="pub-1", bounty=5.0,
        winner_submission_id=None,
    )
    db.add(task)
    db.commit()

    from app.services.payout import pay_winner
    pay_winner(db, task.id)

    db.refresh(task)
    assert task.payout_status == PayoutStatus.pending  # unchanged
    db.close()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_payout_service.py -v
```

Expected: `FAILED — ModuleNotFoundError`

**Step 3: Implement `app/services/payout.py`**

```python
import os
from web3 import Web3
from sqlalchemy.orm import Session
from ..models import Task, Submission, User, PayoutStatus

PLATFORM_PRIVATE_KEY = os.environ.get("PLATFORM_PRIVATE_KEY", "")
PLATFORM_WALLET = os.environ.get("PLATFORM_WALLET", "")
RPC_URL = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
USDC_CONTRACT = os.environ.get("USDC_CONTRACT", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
PLATFORM_FEE_RATE = float(os.environ.get("PLATFORM_FEE_RATE", "0.20"))

# Minimal ERC-20 ABI for transfer
ERC20_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    }
]


def _send_usdc_transfer(to_address: str, amount: float) -> str:
    """Send USDC transfer on-chain. Returns tx hash. Separated for mocking."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT), abi=ERC20_TRANSFER_ABI
    )
    # USDC has 6 decimals
    amount_wei = int(amount * 10**6)
    account = w3.eth.account.from_key(PLATFORM_PRIVATE_KEY)
    tx = contract.functions.transfer(
        Web3.to_checksum_address(to_address), amount_wei
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    return tx_hash.hex()


def pay_winner(db: Session, task_id: str) -> None:
    """Pay the winner of a task. Call after task is closed and winner is set."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not task.winner_submission_id or not task.bounty:
        return

    submission = db.query(Submission).filter(
        Submission.id == task.winner_submission_id
    ).first()
    if not submission:
        return

    winner = db.query(User).filter(User.id == submission.worker_id).first()
    if not winner:
        return

    payout_amount = round(task.bounty * (1 - PLATFORM_FEE_RATE), 6)

    try:
        tx_hash = _send_usdc_transfer(winner.wallet, payout_amount)
        task.payout_status = PayoutStatus.paid
        task.payout_tx_hash = tx_hash
        task.payout_amount = payout_amount
    except Exception as e:
        task.payout_status = PayoutStatus.failed
        print(f"[payout] Failed for task {task_id}: {e}", flush=True)

    db.commit()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_payout_service.py -v
```

Expected: all 3 tests `PASSED`

**Step 5: Commit**

```bash
git add app/services/payout.py tests/test_payout_service.py
git commit -m "feat: payout service with web3.py USDC transfer"
```

---

### Task 7: Wire Payout Into Settlement Logic

**Files:**
- Modify: `app/routers/internal.py`
- Modify: `app/scheduler.py`
- Modify: `app/services/oracle.py`
- Modify: `tests/test_internal.py`
- Modify: `tests/test_scheduler.py`

**Step 1: Write/update failing tests**

Add to `tests/test_internal.py`:

```python
def test_fastest_first_triggers_payout_on_close(client):
    task, sub = make_task_and_submission(client, threshold=0.7)
    with patch("app.routers.internal.pay_winner") as mock_payout:
        client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})
        mock_payout.assert_called_once()


def test_below_threshold_no_payout(client):
    task, sub = make_task_and_submission(client, threshold=0.9)
    with patch("app.routers.internal.pay_winner") as mock_payout:
        client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.5})
        mock_payout.assert_not_called()
```

Add to `tests/test_scheduler.py`:

```python
def test_settle_triggers_payout():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(title="Q", description="d", type=TaskType.quality_first,
                max_revisions=3, deadline=past, publisher_id="pub-1", bounty=10.0)
    db.add(task)
    db.flush()

    s1 = Submission(task_id=task.id, worker_id="w1", revision=1, content="v1",
                    score=0.85, status=SubmissionStatus.scored)
    db.add(s1)
    db.commit()

    with patch("app.scheduler.pay_winner") as mock_payout:
        from app.scheduler import settle_expired_quality_first
        settle_expired_quality_first(db=db)
        mock_payout.assert_called_once_with(db, task.id)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_internal.py::test_fastest_first_triggers_payout_on_close tests/test_scheduler.py::test_settle_triggers_payout -v
```

Expected: `FAILED`

**Step 3: Update `app/routers/internal.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Submission, Task, SubmissionStatus, TaskStatus
from ..schemas import ScoreInput
from ..services.payout import pay_winner

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/submissions/{sub_id}/score")
def score_submission(sub_id: str, data: ScoreInput, db: Session = Depends(get_db)):
    sub = db.query(Submission).filter(Submission.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    sub.score = data.score
    sub.oracle_feedback = data.feedback
    sub.status = SubmissionStatus.scored
    db.commit()

    task = db.query(Task).filter(Task.id == sub.task_id).first()
    if task and task.type.value == "fastest_first" and task.status == TaskStatus.open:
        if task.threshold is not None and data.score >= task.threshold:
            task.winner_submission_id = sub.id
            task.status = TaskStatus.closed
            db.commit()
            pay_winner(db, task.id)

    return {"ok": True}
```

**Step 4: Update `app/scheduler.py`**

Add payout call after settling each task:

```python
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from .models import Task, Submission, TaskType, TaskStatus
from .services.payout import pay_winner


def settle_expired_quality_first(db: Optional[Session] = None) -> None:
    """Close quality_first tasks whose deadline has passed and pick the winner."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expired = (
            db.query(Task)
            .filter(
                Task.type == TaskType.quality_first,
                Task.status == TaskStatus.open,
                Task.deadline <= now,
            )
            .all()
        )
        for task in expired:
            best = (
                db.query(Submission)
                .filter(
                    Submission.task_id == task.id,
                    Submission.score.isnot(None),
                )
                .order_by(Submission.score.desc())
                .first()
            )
            if best:
                task.winner_submission_id = best.id
            task.status = TaskStatus.closed
        db.commit()

        for task in expired:
            if task.winner_submission_id:
                pay_winner(db, task.id)
    finally:
        if own_session:
            db.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(settle_expired_quality_first, "interval", minutes=1)
    return scheduler
```

**Step 5: Update `app/services/oracle.py`**

Add payout call after fastest_first settlement in `_apply_fastest_first`:

```python
from .payout import pay_winner
```

Update `_apply_fastest_first`:

```python
def _apply_fastest_first(db: Session, task: Task, submission: Submission) -> None:
    if task.type.value != "fastest_first" or task.status != TaskStatus.open:
        return
    if task.threshold is not None and submission.score >= task.threshold:
        task.winner_submission_id = submission.id
        task.status = TaskStatus.closed
        db.commit()
        pay_winner(db, task.id)
```

**Step 6: Run tests to verify they pass**

```bash
pytest tests/test_internal.py tests/test_scheduler.py -v
```

Expected: all tests `PASSED`

**Step 7: Run full suite**

```bash
pytest -v
```

Expected: all tests `PASSED`

**Step 8: Commit**

```bash
git add app/routers/internal.py app/scheduler.py app/services/oracle.py tests/test_internal.py tests/test_scheduler.py
git commit -m "feat: wire payout into scoring and settlement logic"
```

---

### Task 8: Payout Retry Endpoint

**Files:**
- Modify: `app/routers/internal.py`
- Create: `tests/test_payout_retry.py`

**Step 1: Write the failing test**

`tests/test_payout_retry.py`:
```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def test_retry_payout_for_failed_task(client):
    # Create task and close it manually
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xtest"}):
        task = client.post("/tasks", json={
            "title": "T", "description": "d", "type": "fastest_first",
            "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 10.0,
        }, headers={"X-PAYMENT": "test"}).json()

    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        }).json()

    # Score above threshold to close task — mock payout to fail
    with patch("app.routers.internal.pay_winner") as mock_pay:
        mock_pay.return_value = None  # payout handled separately
        client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})

    # Manually set payout_status to failed via DB
    from app.database import get_db
    from app.main import app
    from app.models import Task as TaskModel, PayoutStatus
    db = next(app.dependency_overrides[get_db]())
    t = db.query(TaskModel).filter(TaskModel.id == task["id"]).first()
    t.payout_status = PayoutStatus.failed
    db.commit()

    # Retry payout
    with patch("app.routers.internal.pay_winner") as mock_retry:
        resp = client.post(f"/internal/tasks/{task['id']}/payout")
    assert resp.status_code == 200
    mock_retry.assert_called_once()


def test_retry_payout_not_found(client):
    resp = client.post("/internal/tasks/nonexistent/payout")
    assert resp.status_code == 404
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_payout_retry.py -v
```

Expected: `FAILED`

**Step 3: Add retry endpoint to `app/routers/internal.py`**

Add after the existing `score_submission` endpoint:

```python
@router.post("/tasks/{task_id}/payout")
def retry_payout(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.winner_submission_id:
        raise HTTPException(status_code=400, detail="Task has no winner")
    pay_winner(db, task.id)
    return {"ok": True}
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_payout_retry.py -v
```

Expected: all 2 tests `PASSED`

**Step 5: Commit**

```bash
git add app/routers/internal.py tests/test_payout_retry.py
git commit -m "feat: payout retry endpoint"
```

---

### Task 9: Full Integration Tests

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Write integration tests**

Add to `tests/test_integration.py`:

```python
def test_bounty_lifecycle_fastest_first(client):
    """Full flow: register → publish (with payment) → submit → score → payout."""
    # 1. Register publisher and worker
    pub = client.post("/users", json={
        "nickname": "pub-int", "wallet": "0xPUB", "role": "publisher"
    }).json()
    worker = client.post("/users", json={
        "nickname": "worker-int", "wallet": "0xWORKER", "role": "worker"
    }).json()

    # 2. Publish task with bounty (mock x402 payment)
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xPAYMENT"}):
        task = client.post("/tasks", json={
            "title": "Bounty task", "description": "Do it",
            "type": "fastest_first", "threshold": 0.7,
            "deadline": future(), "publisher_id": pub["id"], "bounty": 10.0,
        }, headers={"X-PAYMENT": "valid"}).json()

    assert task["bounty"] == 10.0
    assert task["payment_tx_hash"] == "0xPAYMENT"
    assert task["payout_status"] == "pending"

    # 3. Worker submits
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": worker["id"], "content": "my answer"
        }).json()

    # 4. Score above threshold → triggers payout
    with patch("app.services.payout._send_usdc_transfer", return_value="0xPAYOUT") as mock_tx:
        client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})
        mock_tx.assert_called_once_with("0xWORKER", 8.0)  # 10.0 * 0.80

    # 5. Verify final state
    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["status"] == "closed"
    assert detail["winner_submission_id"] == sub["id"]
    assert detail["payout_status"] == "paid"
    assert detail["payout_amount"] == 8.0
    assert detail["payout_tx_hash"] == "0xPAYOUT"


def test_bounty_lifecycle_quality_first(client):
    """Full flow: quality_first with deadline settlement and payout."""
    pub = client.post("/users", json={
        "nickname": "pub-q", "wallet": "0xPUBQ", "role": "publisher"
    }).json()
    worker = client.post("/users", json={
        "nickname": "worker-q", "wallet": "0xWORKERQ", "role": "worker"
    }).json()

    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xPAY"}):
        task = client.post("/tasks", json={
            "title": "Quality bounty", "description": "Refine",
            "type": "quality_first", "max_revisions": 3,
            "deadline": future(), "publisher_id": pub["id"], "bounty": 20.0,
        }, headers={"X-PAYMENT": "valid"}).json()

    with patch("app.routers.submissions.invoke_oracle"):
        r1 = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": worker["id"], "content": "draft 1"
        }).json()
        r2 = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": worker["id"], "content": "draft 2"
        }).json()

    client.post(f"/internal/submissions/{r1['id']}/score", json={"score": 0.5})
    client.post(f"/internal/submissions/{r2['id']}/score", json={"score": 0.9})

    # Force deadline to past and settle
    from app.database import get_db
    from app.main import app
    from app.models import Task as TaskModel
    db = next(app.dependency_overrides[get_db]())
    t = db.query(TaskModel).filter(TaskModel.id == task["id"]).first()
    t.deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    with patch("app.services.payout._send_usdc_transfer", return_value="0xQPAYOUT") as mock_tx:
        from app.scheduler import settle_expired_quality_first
        settle_expired_quality_first(db=db)
        mock_tx.assert_called_once_with("0xWORKERQ", 16.0)  # 20.0 * 0.80

    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["status"] == "closed"
    assert detail["payout_status"] == "paid"
    assert detail["payout_amount"] == 16.0
```

**Step 2: Run integration tests**

```bash
pytest tests/test_integration.py -v
```

Expected: all tests `PASSED`

**Step 3: Run the full test suite**

```bash
pytest -v
```

Expected: all tests `PASSED`

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: blockchain bounty integration tests"
```

---

## Running the Server

```bash
# Set environment variables
export PLATFORM_WALLET=0x...
export PLATFORM_PRIVATE_KEY=0x...
export BASE_SEPOLIA_RPC_URL=https://sepolia.base.org
export USDC_CONTRACT=0x036CbD53842c5426634e7929541eC2318f3dCF7e
export PLATFORM_FEE_RATE=0.20
export X402_NETWORK=base-sepolia

# Install and run
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Running Tests

```bash
pytest -v
```
