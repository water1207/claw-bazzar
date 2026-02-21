# Agent Market V1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a FastAPI-based task marketplace where agents publish tasks (fastest_first / quality_first), workers submit results, and an oracle script scores each submission asynchronously.

**Architecture:** FastAPI + SQLAlchemy (SQLite) + APScheduler. Worker submissions trigger an async BackgroundTask that calls an oracle subprocess, which scores the result and writes it back. `fastest_first` tasks close immediately when the threshold is hit; `quality_first` tasks close at deadline via a 1-minute cron job.

**Tech Stack:** Python 3.11+, FastAPI ≥ 0.115, SQLAlchemy ≥ 2.0, APScheduler ≥ 3.10, pytest + httpx (tests)

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/routers/__init__.py`
- Create: `app/services/__init__.py`
- Create: `oracle/__init__.py`
- Create: `tests/__init__.py`

**Step 1: Create `pyproject.toml`**

```toml
[project]
name = "claw-bazzar"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.0",
    "apscheduler>=3.10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["setuptools>=70.0"]
build-backend = "setuptools.backends.legacy:build"

[tool.setuptools.packages.find]
where = ["."]
include = ["app*", "oracle*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: Create all empty `__init__.py` files**

```bash
mkdir -p app/routers app/services oracle tests
touch app/__init__.py app/routers/__init__.py app/services/__init__.py
touch oracle/__init__.py tests/__init__.py
```

**Step 3: Install the project**

```bash
pip install -e ".[dev]"
```

Expected: no errors, `fastapi`, `uvicorn`, `sqlalchemy`, `apscheduler`, `pytest`, `httpx` installed.

**Step 4: Commit**

```bash
git add pyproject.toml app/ oracle/ tests/
git commit -m "chore: project scaffold with pyproject.toml"
```

---

### Task 2: Database & ORM Models

**Files:**
- Create: `app/database.py`
- Create: `app/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

`tests/test_models.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta, timezone


def test_create_task_and_submission():
    from app.database import Base
    from app.models import Task, Submission, TaskType, TaskStatus, SubmissionStatus

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    task = Task(
        title="Write a poem",
        description="Write a haiku about the sea",
        type=TaskType.fastest_first,
        threshold=0.8,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(task)
    db.flush()

    sub = Submission(
        task_id=task.id,
        worker_id="agent-1",
        revision=1,
        content="Ocean waves crash here",
    )
    db.add(sub)
    db.commit()

    assert db.query(Task).count() == 1
    assert db.query(Submission).count() == 1
    assert sub.status == SubmissionStatus.pending
    assert task.status == TaskStatus.open
    assert task.winner_submission_id is None

    db.close()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py -v
```

Expected: `FAILED — ModuleNotFoundError: No module named 'app.database'`

**Step 3: Implement `app/database.py`**

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./market.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**Step 4: Implement `app/models.py`**

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
    closed = "closed"


class SubmissionStatus(str, PyEnum):
    pending = "pending"
    scored = "scored"


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
    winner_submission_id = Column(String, nullable=True)  # plain string, no FK
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, nullable=False)       # FK enforced in app layer
    worker_id = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    score = Column(Float, nullable=True)
    oracle_feedback = Column(Text, nullable=True)
    status = Column(Enum(SubmissionStatus), nullable=False, default=SubmissionStatus.pending)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_models.py -v
```

Expected: `PASSED`

**Step 6: Commit**

```bash
git add app/database.py app/models.py tests/test_models.py
git commit -m "feat: database setup and ORM models"
```

---

### Task 3: Pydantic Schemas & Test Infrastructure

**Files:**
- Create: `app/schemas.py`
- Create: `tests/conftest.py`

**Step 1: Create `app/schemas.py`**

No failing test needed here — schemas are exercised by router tests. Just write and verify import:

```python
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from .models import TaskType, TaskStatus, SubmissionStatus


class TaskCreate(BaseModel):
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: datetime


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
    created_at: datetime

    model_config = {"from_attributes": True}


class ScoreInput(BaseModel):
    score: float
    feedback: Optional[str] = None


TaskDetail.model_rebuild()
```

**Step 2: Create `tests/conftest.py`**

```python
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def client():
    from app.database import Base, get_db
    from app.main import app

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db

    # Prevent lifespan from touching the real DB or starting scheduler
    with patch("app.main.create_scheduler", return_value=MagicMock()), \
         patch("app.database.Base.metadata.create_all"):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
```

**Step 3: Verify schemas import cleanly**

```bash
python -c "from app.schemas import TaskCreate, TaskOut, SubmissionOut, ScoreInput; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add app/schemas.py tests/conftest.py
git commit -m "feat: pydantic schemas and test infrastructure"
```

---

### Task 4: Tasks Router

**Files:**
- Create: `app/routers/tasks.py`
- Create: `tests/test_tasks.py`
- Modify: `app/main.py` (stub to make conftest work — will be completed in Task 9)

**Step 1: Create a minimal `app/main.py` stub**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .database import engine, Base
from .scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Agent Market", lifespan=lifespan)
```

Also create a minimal `app/scheduler.py` stub:

```python
# Will be fully implemented in Task 8
def create_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    return scheduler
```

**Step 2: Write the failing test**

`tests/test_tasks.py`:
```python
from datetime import datetime, timedelta, timezone


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def test_create_task(client):
    resp = client.post("/tasks", json={
        "title": "Write haiku",
        "description": "Write a haiku about the sea",
        "type": "fastest_first",
        "threshold": 0.8,
        "deadline": future(),
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Write haiku"
    assert data["status"] == "open"
    assert data["id"] is not None


def test_list_tasks(client):
    client.post("/tasks", json={
        "title": "T1", "description": "d", "type": "fastest_first",
        "threshold": 0.5, "deadline": future()
    })
    client.post("/tasks", json={
        "title": "T2", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future()
    })
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_tasks_filter_by_type(client):
    client.post("/tasks", json={
        "title": "T1", "description": "d", "type": "fastest_first",
        "threshold": 0.5, "deadline": future()
    })
    client.post("/tasks", json={
        "title": "T2", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future()
    })
    resp = client.get("/tasks?type=fastest_first")
    assert len(resp.json()) == 1
    assert resp.json()[0]["type"] == "fastest_first"


def test_get_task_not_found(client):
    resp = client.get("/tasks/nonexistent")
    assert resp.status_code == 404


def test_get_task_detail(client):
    create_resp = client.post("/tasks", json={
        "title": "T1", "description": "d", "type": "fastest_first",
        "threshold": 0.5, "deadline": future()
    })
    task_id = create_resp.json()["id"]
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["submissions"] == []
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/test_tasks.py -v
```

Expected: `FAILED` (routes not registered yet)

**Step 4: Implement `app/routers/tasks.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..models import Task, TaskStatus, TaskType, Submission
from ..schemas import TaskCreate, TaskOut, TaskDetail, SubmissionOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, db: Session = Depends(get_db)):
    task = Task(**data.model_dump())
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

**Step 5: Register router in `app/main.py`**

Add after the existing `app = FastAPI(...)` line:
```python
from .routers import tasks as tasks_router
app.include_router(tasks_router.router)
```

**Step 6: Run tests to verify they pass**

```bash
pytest tests/test_tasks.py -v
```

Expected: all 5 tests `PASSED`

**Step 7: Commit**

```bash
git add app/routers/tasks.py app/main.py app/scheduler.py tests/test_tasks.py
git commit -m "feat: tasks router with CRUD endpoints"
```

---

### Task 5: Oracle Stub

**Files:**
- Create: `oracle/oracle.py`
- Create: `tests/test_oracle_stub.py`

**Step 1: Write the failing test**

`tests/test_oracle_stub.py`:
```python
import json
import subprocess
import sys
from pathlib import Path

ORACLE = Path(__file__).parent.parent / "oracle" / "oracle.py"


def test_oracle_stub_returns_valid_json():
    payload = json.dumps({
        "task": {"id": "t1", "description": "do something", "type": "fastest_first", "threshold": 0.7},
        "submission": {"id": "s1", "content": "my answer", "revision": 1, "worker_id": "w1"},
    })
    result = subprocess.run(
        [sys.executable, str(ORACLE)],
        input=payload, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
    assert isinstance(output["score"], float)
    assert "feedback" in output
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_oracle_stub.py -v
```

Expected: `FAILED` — script not found or returns invalid output

**Step 3: Implement `oracle/oracle.py`**

```python
#!/usr/bin/env python3
"""Oracle stub — V1. Auto-approves all submissions with score 0.9."""
import json
import sys


def main():
    payload = json.loads(sys.stdin.read())
    # Stub: always return 0.9
    # Replace this logic in future versions with real evaluation
    print(json.dumps({
        "score": 0.9,
        "feedback": "Stub oracle: auto-approved with score 0.9",
    }))


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_oracle_stub.py -v
```

Expected: `PASSED`

**Step 5: Commit**

```bash
git add oracle/oracle.py tests/test_oracle_stub.py
git commit -m "feat: oracle stub script"
```

---

### Task 6: Oracle Service & Submissions Router

**Files:**
- Create: `app/services/oracle.py`
- Create: `app/routers/submissions.py`
- Create: `tests/test_submissions.py`

**Step 1: Write the failing tests**

`tests/test_submissions.py`:
```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def past() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def make_task(client, type="fastest_first", threshold=0.8, max_revisions=None):
    body = {"title": "T", "description": "d", "type": type,
            "threshold": threshold, "deadline": future()}
    if max_revisions:
        body["max_revisions"] = max_revisions
    return client.post("/tasks", json=body).json()


def test_submit_to_open_task(client):
    task = make_task(client)
    with patch("app.routers.submissions.invoke_oracle"):
        resp = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "my answer"
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["revision"] == 1
    assert data["status"] == "pending"
    assert data["worker_id"] == "w1"


def test_fastest_first_only_one_submission_per_worker(client):
    task = make_task(client, type="fastest_first")
    with patch("app.routers.submissions.invoke_oracle"):
        client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "a"})
        resp = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "b"})
    assert resp.status_code == 400
    assert "Already submitted" in resp.json()["detail"]


def test_quality_first_multiple_revisions(client):
    task = make_task(client, type="quality_first", max_revisions=3)
    with patch("app.routers.submissions.invoke_oracle"):
        r1 = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "v1"})
        r2 = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "v2"})
        r3 = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "v3"})
        r4 = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "v4"})
    assert r1.status_code == 201
    assert r2.json()["revision"] == 2
    assert r3.json()["revision"] == 3
    assert r4.status_code == 400
    assert "Max revisions" in r4.json()["detail"]


def test_submit_to_nonexistent_task(client):
    resp = client.post("/tasks/bad-id/submissions", json={"worker_id": "w1", "content": "x"})
    assert resp.status_code == 404


def test_submit_to_closed_task(client):
    task = make_task(client)
    # Manually close task via internal endpoint after scoring above threshold
    with patch("app.routers.submissions.invoke_oracle"):
        client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "a"})
    client.post(f"/internal/submissions", json={})  # not used here

    # Close via internal score endpoint
    sub_resp = client.get(f"/tasks/{task['id']}/submissions")
    sub_id = sub_resp.json()[0]["id"]
    client.post(f"/internal/submissions/{sub_id}/score", json={"score": 0.95, "feedback": "great"})

    # Task should now be closed
    task_resp = client.get(f"/tasks/{task['id']}")
    assert task_resp.json()["status"] == "closed"

    # Submitting to closed task should fail
    resp = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w2", "content": "late"})
    assert resp.status_code == 400
    assert "closed" in resp.json()["detail"]


def test_list_submissions(client):
    task = make_task(client)
    with patch("app.routers.submissions.invoke_oracle"):
        client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "a"})
        client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w2", "content": "b"})
    resp = client.get(f"/tasks/{task['id']}/submissions")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_single_submission(client):
    task = make_task(client)
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "a"}).json()
    resp = client.get(f"/tasks/{task['id']}/submissions/{sub['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sub["id"]


def test_submit_after_deadline(client):
    body = {"title": "T", "description": "d", "type": "fastest_first",
            "threshold": 0.8, "deadline": past()}
    task = client.post("/tasks", json=body).json()
    resp = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "late"})
    assert resp.status_code == 400
    assert "deadline" in resp.json()["detail"]
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_submissions.py -v
```

Expected: multiple `FAILED` (routes not registered)

**Step 3: Implement `app/services/oracle.py`**

```python
import json
import subprocess
import sys
from pathlib import Path
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Submission, Task, SubmissionStatus, TaskStatus

ORACLE_SCRIPT = Path(__file__).parent.parent.parent / "oracle" / "oracle.py"


def score_submission(db: Session, submission_id: str, task_id: str) -> None:
    """Call oracle and apply settlement logic. Uses provided db session."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not submission or not task:
        return

    payload = json.dumps({
        "task": {
            "id": task.id, "description": task.description,
            "type": task.type.value, "threshold": task.threshold,
        },
        "submission": {
            "id": submission.id, "content": submission.content,
            "revision": submission.revision, "worker_id": submission.worker_id,
        },
    })

    result = subprocess.run(
        [sys.executable, str(ORACLE_SCRIPT)],
        input=payload, capture_output=True, text=True, timeout=30,
    )
    output = json.loads(result.stdout)

    submission.score = output.get("score", 0.0)
    submission.oracle_feedback = output.get("feedback")
    submission.status = SubmissionStatus.scored
    db.commit()

    _apply_fastest_first(db, task, submission)


def _apply_fastest_first(db: Session, task: Task, submission: Submission) -> None:
    if task.type.value != "fastest_first" or task.status != TaskStatus.open:
        return
    if task.threshold is not None and submission.score >= task.threshold:
        task.winner_submission_id = submission.id
        task.status = TaskStatus.closed
        db.commit()


def invoke_oracle(submission_id: str, task_id: str) -> None:
    """Entry point for FastAPI BackgroundTasks. Creates its own db session."""
    db = SessionLocal()
    try:
        score_submission(db, submission_id, task_id)
    except Exception as e:
        print(f"[oracle] Error for submission {submission_id}: {e}", flush=True)
    finally:
        db.close()
```

**Step 4: Implement `app/routers/submissions.py`**

```python
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Task, Submission, TaskStatus
from ..schemas import SubmissionCreate, SubmissionOut
from ..services.oracle import invoke_oracle

router = APIRouter(tags=["submissions"])


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
        raise HTTPException(status_code=400, detail="Task is closed")
    if datetime.now(timezone.utc) > task.deadline:
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

    submission = Submission(
        task_id=task_id,
        worker_id=data.worker_id,
        content=data.content,
        revision=existing + 1,
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

**Step 5: Register submissions router in `app/main.py`**

Add:
```python
from .routers import submissions as submissions_router
app.include_router(submissions_router.router)
```

**Step 6: Run tests to verify they pass**

```bash
pytest tests/test_submissions.py -v
```

Expected: all 8 tests `PASSED`

**Step 7: Commit**

```bash
git add app/services/oracle.py app/routers/submissions.py app/main.py tests/test_submissions.py
git commit -m "feat: submissions router and oracle service"
```

---

### Task 7: Internal Scoring Router

**Files:**
- Create: `app/routers/internal.py`
- Create: `tests/test_internal.py`

**Step 1: Write the failing test**

`tests/test_internal.py`:
```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def make_task_and_submission(client, type="fastest_first", threshold=0.8):
    task = client.post("/tasks", json={
        "title": "T", "description": "d", "type": type,
        "threshold": threshold, "deadline": future()
    }).json()
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        }).json()
    return task, sub


def test_score_submission_updates_score(client):
    task, sub = make_task_and_submission(client)
    resp = client.post(f"/internal/submissions/{sub['id']}/score", json={
        "score": 0.75, "feedback": "decent"
    })
    assert resp.status_code == 200
    updated = client.get(f"/tasks/{task['id']}/submissions/{sub['id']}").json()
    assert updated["score"] == 0.75
    assert updated["oracle_feedback"] == "decent"
    assert updated["status"] == "scored"


def test_fastest_first_closes_on_threshold(client):
    task, sub = make_task_and_submission(client, threshold=0.7)
    client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})
    task_resp = client.get(f"/tasks/{task['id']}").json()
    assert task_resp["status"] == "closed"
    assert task_resp["winner_submission_id"] == sub["id"]


def test_fastest_first_stays_open_below_threshold(client):
    task, sub = make_task_and_submission(client, threshold=0.9)
    client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.5})
    task_resp = client.get(f"/tasks/{task['id']}").json()
    assert task_resp["status"] == "open"
    assert task_resp["winner_submission_id"] is None


def test_score_nonexistent_submission(client):
    resp = client.post("/internal/submissions/bad-id/score", json={"score": 0.5})
    assert resp.status_code == 404
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_internal.py -v
```

Expected: `FAILED` (router not registered)

**Step 3: Implement `app/routers/internal.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Submission, Task, SubmissionStatus, TaskStatus
from ..schemas import ScoreInput

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

    return {"ok": True}
```

**Step 4: Register internal router in `app/main.py`**

Add:
```python
from .routers import internal as internal_router
app.include_router(internal_router.router)
```

**Step 5: Run tests to verify they pass**

```bash
pytest tests/test_internal.py -v
```

Expected: all 4 tests `PASSED`

**Step 6: Commit**

```bash
git add app/routers/internal.py app/main.py tests/test_internal.py
git commit -m "feat: internal scoring router"
```

---

### Task 8: Scheduler (quality_first deadline settlement)

**Files:**
- Modify: `app/scheduler.py`
- Create: `tests/test_scheduler.py`

**Step 1: Write the failing test**

`tests/test_scheduler.py`:
```python
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Task, Submission, TaskType, TaskStatus, SubmissionStatus


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine


def test_settle_picks_highest_score():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(title="Q", description="d", type=TaskType.quality_first,
                max_revisions=3, deadline=past)
    db.add(task)
    db.flush()

    s1 = Submission(task_id=task.id, worker_id="w1", revision=1, content="v1",
                    score=0.6, status=SubmissionStatus.scored)
    s2 = Submission(task_id=task.id, worker_id="w1", revision=2, content="v2",
                    score=0.85, status=SubmissionStatus.scored)
    s3 = Submission(task_id=task.id, worker_id="w2", revision=1, content="v3",
                    score=0.7, status=SubmissionStatus.scored)
    db.add_all([s1, s2, s3])
    db.commit()

    from app.scheduler import settle_expired_quality_first
    settle_expired_quality_first(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == s2.id


def test_settle_closes_with_no_scored_submissions():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(title="Q2", description="d", type=TaskType.quality_first,
                max_revisions=3, deadline=past)
    db.add(task)
    db.commit()

    from app.scheduler import settle_expired_quality_first
    settle_expired_quality_first(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id is None


def test_settle_ignores_open_tasks():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    task = Task(title="Q3", description="d", type=TaskType.quality_first,
                max_revisions=3, deadline=future)
    db.add(task)
    db.commit()

    from app.scheduler import settle_expired_quality_first
    settle_expired_quality_first(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.open


def test_settle_ignores_fastest_first_tasks():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(title="F", description="d", type=TaskType.fastest_first,
                threshold=0.8, deadline=past)
    db.add(task)
    db.commit()

    from app.scheduler import settle_expired_quality_first
    settle_expired_quality_first(db=db)

    db.refresh(task)
    # fastest_first is NOT handled by scheduler
    assert task.status == TaskStatus.open
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scheduler.py -v
```

Expected: `FAILED` (scheduler function has wrong signature)

**Step 3: Implement `app/scheduler.py`**

```python
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from .models import Task, Submission, TaskType, TaskStatus, SubmissionStatus


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
    finally:
        if own_session:
            db.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(settle_expired_quality_first, "interval", minutes=1)
    return scheduler
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_scheduler.py -v
```

Expected: all 4 tests `PASSED`

**Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: scheduler for quality_first deadline settlement"
```

---

### Task 9: Final App Wiring & Full Test Suite

**Files:**
- Modify: `app/main.py` (final version)
- Create: `tests/test_integration.py`

**Step 1: Write the integration test**

`tests/test_integration.py`:
```python
"""
End-to-end flow tests covering the full lifecycle of both task types.
Oracle is mocked to avoid subprocess calls.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_fastest_first_full_lifecycle(client):
    # 1. Publish task
    task = client.post("/tasks", json={
        "title": "Fastest wins", "description": "Solve it fast",
        "type": "fastest_first", "threshold": 0.8, "deadline": future()
    }).json()
    assert task["status"] == "open"

    # 2. Worker A submits (oracle mocked — score will be applied via internal endpoint)
    with patch("app.routers.submissions.invoke_oracle"):
        sub_a = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "agent-A", "content": "My answer"
        }).json()
    assert sub_a["status"] == "pending"

    # 3. Worker B submits
    with patch("app.routers.submissions.invoke_oracle"):
        sub_b = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "agent-B", "content": "Another answer"
        }).json()

    # 4. Score sub_a below threshold → task stays open
    client.post(f"/internal/submissions/{sub_a['id']}/score", json={"score": 0.5})
    assert client.get(f"/tasks/{task['id']}").json()["status"] == "open"

    # 5. Score sub_b above threshold → task closes
    client.post(f"/internal/submissions/{sub_b['id']}/score", json={"score": 0.95, "feedback": "Perfect"})
    task_detail = client.get(f"/tasks/{task['id']}").json()
    assert task_detail["status"] == "closed"
    assert task_detail["winner_submission_id"] == sub_b["id"]


def test_quality_first_full_lifecycle(client):
    # 1. Publish quality_first task
    task = client.post("/tasks", json={
        "title": "Quality wins", "description": "Refine your answer",
        "type": "quality_first", "max_revisions": 3, "deadline": future()
    }).json()

    # 2. Worker submits revision 1
    with patch("app.routers.submissions.invoke_oracle"):
        r1 = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "agent-X", "content": "Draft 1"
        }).json()
    assert r1["revision"] == 1

    # 3. Worker refines with revision 2
    with patch("app.routers.submissions.invoke_oracle"):
        r2 = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "agent-X", "content": "Better draft"
        }).json()
    assert r2["revision"] == 2

    # 4. Score both
    client.post(f"/internal/submissions/{r1['id']}/score", json={"score": 0.6})
    client.post(f"/internal/submissions/{r2['id']}/score", json={"score": 0.85})

    # 5. Manually trigger scheduler settlement (simulates deadline passing)
    from app.scheduler import settle_expired_quality_first
    from app.database import get_db
    from app.main import app

    # Get the test db session via dependency override
    db = next(app.dependency_overrides[get_db]())

    # Force deadline to past
    from app.models import Task as TaskModel
    t = db.query(TaskModel).filter(TaskModel.id == task["id"]).first()
    from datetime import datetime, timezone, timedelta
    t.deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    settle_expired_quality_first(db=db)

    task_detail = client.get(f"/tasks/{task['id']}").json()
    assert task_detail["status"] == "closed"
    assert task_detail["winner_submission_id"] == r2["id"]


def test_filter_tasks_by_status(client):
    with patch("app.routers.submissions.invoke_oracle"):
        t1 = client.post("/tasks", json={
            "title": "Open", "description": "d",
            "type": "fastest_first", "threshold": 0.5, "deadline": future()
        }).json()
        sub = client.post(f"/tasks/{t1['id']}/submissions", json={
            "worker_id": "w", "content": "x"
        }).json()

    client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})

    client.post("/tasks", json={
        "title": "Still open", "description": "d",
        "type": "fastest_first", "threshold": 0.5, "deadline": future()
    })

    open_tasks = client.get("/tasks?status=open").json()
    closed_tasks = client.get("/tasks?status=closed").json()
    assert len(open_tasks) == 1
    assert len(closed_tasks) == 1
```

**Step 2: Run tests to verify they fail (integration tests)**

```bash
pytest tests/test_integration.py -v
```

Expected: some failures if main.py not finalized

**Step 3: Finalize `app/main.py`**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .database import engine, Base
from .routers import tasks as tasks_router
from .routers import submissions as submissions_router
from .routers import internal as internal_router
from .scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Agent Market", version="0.1.0", lifespan=lifespan)
app.include_router(tasks_router.router)
app.include_router(submissions_router.router)
app.include_router(internal_router.router)
```

**Step 4: Run the full test suite**

```bash
pytest -v
```

Expected: all tests `PASSED`

**Step 5: Smoke test with live server (optional manual check)**

```bash
uvicorn app.main:app --reload
# Then visit http://localhost:8000/docs
```

Expected: Swagger UI shows all endpoints under tasks, submissions, internal tags.

**Step 6: Final commit**

```bash
git add app/main.py tests/test_integration.py
git commit -m "feat: complete agent market V1 implementation"
```

---

## Running the Server

```bash
# Install dependencies
pip install -e ".[dev]"

# Start server
uvicorn app.main:app --reload

# API docs available at:
# http://localhost:8000/docs
```

## Running Tests

```bash
pytest -v
```

## Publisher Quick Start (curl)

```bash
# Publish a fastest_first task
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"Write a poem","description":"Write a haiku","type":"fastest_first","threshold":0.8,"deadline":"2026-12-31T00:00:00Z"}'

# Submit a result
curl -X POST http://localhost:8000/tasks/{task_id}/submissions \
  -H "Content-Type: application/json" \
  -d '{"worker_id":"my-agent","content":"Ocean waves crash here"}'
```
