# Quality-First Scoring Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign quality_first submission flow: submissions receive oracle revision suggestions instead of scores; batch scoring happens after deadline; scores are hidden until challenge_window; frontend shows countdowns, task ID, and revision suggestions.

**Architecture:** Oracle gains a `mode` field (`feedback` vs `score`). The service layer splits into `give_feedback()` (called on submission) and `batch_score_submissions()` (called by scheduler after deadline). API router filters out scores for quality_first tasks in open/scoring states. Frontend adds countdown hooks and displays oracle suggestions.

**Tech Stack:** Python/FastAPI, SQLAlchemy, APScheduler, Next.js 16, React, SWR, TypeScript

---

### Task 1: Oracle stub — add feedback mode

**Files:**
- Modify: `oracle/oracle.py`
- Modify: `tests/test_oracle_stub.py`

**Step 1: Write failing test for feedback mode**

Add to `tests/test_oracle_stub.py`:

```python
def test_oracle_stub_feedback_mode():
    payload = json.dumps({
        "mode": "feedback",
        "task": {"id": "t1", "description": "do something", "type": "quality_first", "threshold": None},
        "submission": {"id": "s1", "content": "my answer", "revision": 1, "worker_id": "w1"},
    })
    result = subprocess.run(
        [sys.executable, str(ORACLE)],
        input=payload, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "suggestions" in output
    assert isinstance(output["suggestions"], list)
    assert len(output["suggestions"]) == 3
    assert "score" not in output


def test_oracle_stub_score_mode_explicit():
    payload = json.dumps({
        "mode": "score",
        "task": {"id": "t1", "description": "do something", "type": "quality_first", "threshold": None},
        "submission": {"id": "s1", "content": "my answer", "revision": 1, "worker_id": "w1"},
    })
    result = subprocess.run(
        [sys.executable, str(ORACLE)],
        input=payload, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
    assert 0.5 <= output["score"] <= 1.0
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_oracle_stub.py -v
```
Expected: `test_oracle_stub_feedback_mode` FAILS, `test_oracle_stub_score_mode_explicit` FAILS (no mode handling yet)

**Step 3: Implement feedback mode in oracle**

Replace `oracle/oracle.py` entirely:

```python
#!/usr/bin/env python3
"""Oracle stub — V1. Supports feedback and score modes."""
import json
import random
import sys

FEEDBACK_SUGGESTIONS = [
    "建议加强代码注释，提高可读性",
    "考虑增加边界条件的处理逻辑",
    "可以优化算法时间复杂度",
    "建议补充单元测试覆盖",
    "接口设计可以更简洁明了",
    "错误处理逻辑需要完善",
    "变量命名建议更具描述性",
    "可以抽取公共逻辑为独立函数",
    "建议增加输入参数校验",
    "文档注释缺失，建议补全",
]


def main():
    payload = json.loads(sys.stdin.read())
    mode = payload.get("mode", "score")

    if mode == "feedback":
        suggestions = random.sample(FEEDBACK_SUGGESTIONS, 3)
        print(json.dumps({"suggestions": suggestions}))
    else:
        score = round(random.uniform(0.5, 1.0), 2)
        print(json.dumps({
            "score": score,
            "feedback": f"Stub oracle: random score {score}",
        }))


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_oracle_stub.py -v
```
Expected: all 3 oracle stub tests PASS

**Step 5: Commit**

```bash
git add oracle/oracle.py tests/test_oracle_stub.py
git commit -m "feat: oracle stub supports feedback and score modes"
```

---

### Task 2: Service layer — give_feedback and batch_score_submissions

**Files:**
- Modify: `app/services/oracle.py`
- Create: `tests/test_oracle_service.py`

**Step 1: Write failing tests**

Create `tests/test_oracle_service.py`:

```python
import json
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, TaskType, TaskStatus, SubmissionStatus


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_quality_task(db):
    from datetime import datetime, timezone, timedelta
    task = Task(
        title="Q", description="desc", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        bounty=1.0, max_revisions=3,
    )
    db.add(task)
    db.flush()
    return task


def make_pending_submission(db, task_id, worker_id="w1"):
    sub = Submission(
        task_id=task_id, worker_id=worker_id, revision=1,
        content="my answer", status=SubmissionStatus.pending,
    )
    db.add(sub)
    db.flush()
    return sub


FAKE_FEEDBACK = json.dumps({"suggestions": ["建议A", "建议B", "建议C"]})
FAKE_SCORE = json.dumps({"score": 0.75, "feedback": "good"})


def test_give_feedback_stores_suggestions_and_keeps_pending():
    db = make_db()
    task = make_quality_task(db)
    sub = make_pending_submission(db, task.id)
    db.commit()

    mock_result = type("R", (), {"stdout": FAKE_FEEDBACK, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        from app.services.oracle import give_feedback
        give_feedback(db, sub.id, task.id)

    db.refresh(sub)
    assert sub.status == SubmissionStatus.pending  # stays pending
    assert sub.score is None                        # no score yet
    suggestions = json.loads(sub.oracle_feedback)
    assert len(suggestions) == 3
    assert suggestions[0] == "建议A"


def test_batch_score_submissions_scores_all_pending():
    db = make_db()
    task = make_quality_task(db)
    s1 = make_pending_submission(db, task.id, "w1")
    s2 = make_pending_submission(db, task.id, "w2")
    db.commit()

    mock_result = type("R", (), {"stdout": FAKE_SCORE, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        from app.services.oracle import batch_score_submissions
        batch_score_submissions(db, task.id)

    db.refresh(s1)
    db.refresh(s2)
    assert s1.status == SubmissionStatus.scored
    assert s1.score == 0.75
    assert s2.status == SubmissionStatus.scored
    assert s2.score == 0.75


def test_batch_score_skips_already_scored():
    db = make_db()
    task = make_quality_task(db)
    s1 = make_pending_submission(db, task.id, "w1")
    s1.status = SubmissionStatus.scored
    s1.score = 0.9
    db.commit()

    mock_result = type("R", (), {"stdout": FAKE_SCORE, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result) as mock_run:
        from app.services.oracle import batch_score_submissions
        batch_score_submissions(db, task.id)

    mock_run.assert_not_called()  # already scored, oracle not called
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_oracle_service.py -v
```
Expected: all 3 FAIL with `ImportError` or `AttributeError`

**Step 3: Implement give_feedback and batch_score_submissions**

Replace `app/services/oracle.py`:

```python
import json
import subprocess
import sys
from pathlib import Path
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Submission, Task, SubmissionStatus, TaskStatus, TaskType
from .payout import pay_winner

ORACLE_SCRIPT = Path(__file__).parent.parent.parent / "oracle" / "oracle.py"


def _call_oracle(payload: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(ORACLE_SCRIPT)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    return json.loads(result.stdout)


def _build_payload(task: Task, submission: Submission, mode: str) -> dict:
    return {
        "mode": mode,
        "task": {
            "id": task.id, "description": task.description,
            "type": task.type.value, "threshold": task.threshold,
        },
        "submission": {
            "id": submission.id, "content": submission.content,
            "revision": submission.revision, "worker_id": submission.worker_id,
        },
    }


def give_feedback(db: Session, submission_id: str, task_id: str) -> None:
    """Call oracle in feedback mode. Stores 3 suggestions, keeps status pending."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not submission or not task:
        return
    output = _call_oracle(_build_payload(task, submission, "feedback"))
    submission.oracle_feedback = json.dumps(output.get("suggestions", []))
    db.commit()


def batch_score_submissions(db: Session, task_id: str) -> None:
    """Score all pending submissions for a task. Called by scheduler after deadline."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return
    pending = db.query(Submission).filter(
        Submission.task_id == task_id,
        Submission.status == SubmissionStatus.pending,
    ).all()
    for submission in pending:
        output = _call_oracle(_build_payload(task, submission, "score"))
        submission.score = output.get("score", 0.0)
        submission.oracle_feedback = output.get("feedback", submission.oracle_feedback)
        submission.status = SubmissionStatus.scored
    db.commit()


def score_submission(db: Session, submission_id: str, task_id: str) -> None:
    """Score a single submission (fastest_first path). Uses provided db session."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not submission or not task:
        return
    output = _call_oracle(_build_payload(task, submission, "score"))
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
        pay_winner(db, task.id)


def invoke_oracle(submission_id: str, task_id: str) -> None:
    """Entry point for FastAPI BackgroundTasks. Creates its own db session."""
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task and task.type == TaskType.quality_first:
            give_feedback(db, submission_id, task_id)
        else:
            score_submission(db, submission_id, task_id)
    except Exception as e:
        print(f"[oracle] Error for submission {submission_id}: {e}", flush=True)
    finally:
        db.close()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_oracle_service.py tests/test_oracle_stub.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_service.py
git commit -m "feat: add give_feedback and batch_score_submissions to oracle service"
```

---

### Task 3: Scheduler — call batch_score_submissions after open→scoring

**Files:**
- Modify: `app/scheduler.py`
- Modify: `tests/test_quality_lifecycle.py`

**Step 1: Write failing test**

Add to `tests/test_quality_lifecycle.py`:

```python
def test_phase1_triggers_batch_scoring():
    """After open→scoring transition, pending submissions get scored."""
    db = make_db()
    task = make_expired_quality_task(db)
    # Add pending submission (no score yet)
    sub = Submission(
        task_id=task.id, worker_id="w1", revision=1,
        content="answer", status=SubmissionStatus.pending,
    )
    db.add(sub)
    db.commit()

    fake_score = json.dumps({"score": 0.88, "feedback": "ok"})
    mock_result = type("R", (), {"stdout": fake_score, "returncode": 0})()

    import json as json_mod
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    db.refresh(sub)
    assert task.status == TaskStatus.scoring
    assert sub.status == SubmissionStatus.scored
    assert sub.score == 0.88
```

Add the import at top of `tests/test_quality_lifecycle.py`:
```python
import json
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_quality_lifecycle.py::test_phase1_triggers_batch_scoring -v
```
Expected: FAIL — submission still `pending` after lifecycle

**Step 3: Update scheduler to call batch_score_submissions**

In `app/scheduler.py`, add import and call after Phase 1 commit:

```python
from .services.oracle import batch_score_submissions
```

In `quality_first_lifecycle()`, after the `if expired_open: db.commit()` block:

```python
        if expired_open:
            db.commit()
            for task in expired_open:
                try:
                    batch_score_submissions(db, task.id)
                except Exception as e:
                    print(f"[scheduler] batch_score error for {task.id}: {e}", flush=True)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_quality_lifecycle.py -v
```
Expected: all lifecycle tests PASS

**Step 5: Commit**

```bash
git add app/scheduler.py tests/test_quality_lifecycle.py
git commit -m "feat: scheduler calls batch_score_submissions after open→scoring transition"
```

---

### Task 4: API — hide scores for quality_first open/scoring tasks

**Files:**
- Modify: `app/routers/submissions.py`
- Modify: `tests/test_submissions.py`

**Step 1: Write failing tests**

Add to `tests/test_submissions.py`:

```python
def make_quality_task(client):
    body = {"title": "T", "description": "d", "type": "quality_first",
            "max_revisions": 3, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0}
    with PAYMENT_MOCK:
        return client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()


def test_quality_first_score_hidden_when_open(client):
    task = make_quality_task(client)
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions",
                          json={"worker_id": "w1", "content": "a"}).json()

    # Manually set score in DB to simulate oracle having run
    from app.database import get_db
    db = next(client.app.dependency_overrides[get_db]())
    from app.models import Submission
    s = db.query(Submission).filter(Submission.id == sub["id"]).first()
    s.score = 0.88
    db.commit()

    resp = client.get(f"/tasks/{task['id']}/submissions/{sub['id']}")
    assert resp.status_code == 200
    assert resp.json()["score"] is None  # hidden because task is open


def test_fastest_first_score_always_visible(client):
    task = make_task(client, type="fastest_first")
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions",
                          json={"worker_id": "w1", "content": "a"}).json()

    from app.database import get_db
    db = next(client.app.dependency_overrides[get_db]())
    from app.models import Submission
    s = db.query(Submission).filter(Submission.id == sub["id"]).first()
    s.score = 0.88
    db.commit()

    resp = client.get(f"/tasks/{task['id']}/submissions/{sub['id']}")
    assert resp.status_code == 200
    assert resp.json()["score"] == 0.88  # always visible for fastest_first
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_submissions.py::test_quality_first_score_hidden_when_open tests/test_submissions.py::test_fastest_first_score_always_visible -v
```
Expected: `test_quality_first_score_hidden_when_open` FAIL (score not hidden)

**Step 3: Add score-hiding to submission router**

In `app/routers/submissions.py`, add a helper and apply it in both GET endpoints:

```python
from ..models import Task, Submission, TaskStatus, TaskType

def _maybe_hide_score(submission: Submission, task: Task) -> Submission:
    """Null out score for quality_first tasks that haven't reached challenge_window yet."""
    if task.type == TaskType.quality_first and task.status in (
        TaskStatus.open, TaskStatus.scoring
    ):
        submission.score = None
    return submission
```

Update the list endpoint:
```python
@router.get("/tasks/{task_id}/submissions", response_model=List[SubmissionOut])
def list_submissions(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    submissions = db.query(Submission).filter(Submission.task_id == task_id).all()
    return [_maybe_hide_score(s, task) for s in submissions]
```

Update the single GET endpoint:
```python
@router.get("/tasks/{task_id}/submissions/{sub_id}", response_model=SubmissionOut)
def get_submission(task_id: str, sub_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    sub = db.query(Submission).filter(
        Submission.id == sub_id, Submission.task_id == task_id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return _maybe_hide_score(sub, task)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_submissions.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add app/routers/submissions.py tests/test_submissions.py
git commit -m "feat: hide scores for quality_first tasks in open/scoring status"
```

---

### Task 5: Frontend defaults and task ID display

**Files:**
- Modify: `frontend/components/DevPanel.tsx`

**Step 1: Update default values**

In `DevPanel.tsx`, change two `useState` defaults:

```tsx
// Line ~118
const [deadlineDuration, setDeadlineDuration] = useState('5')
const [deadlineUnit, setDeadlineUnit] = useState<'minutes' | 'hours' | 'days'>('minutes')

// Line ~120
const [bounty, setBounty] = useState('0.01')
```

**Step 2: Add task ID display in published task card**

Find the published task info block (around line 580–610). After the status line, add:

```tsx
<p className="text-muted-foreground">
  Task ID:{' '}
  <span
    className="font-mono text-white break-all cursor-pointer hover:text-blue-400"
    title="Click to copy"
    onClick={() => navigator.clipboard.writeText(publishedTask.id)}
  >
    {publishedTask.id}
  </span>
</p>
```

**Step 3: Run frontend lint**

```bash
cd frontend && npm run lint
```
Expected: no errors

**Step 4: Commit**

```bash
git add frontend/components/DevPanel.tsx
git commit -m "feat: set bounty/deadline defaults, show task ID in published task card"
```

---

### Task 6: Frontend — deadline and challenge window countdowns

**Files:**
- Modify: `frontend/components/DevPanel.tsx`

**Step 1: Add countdown hook**

Add `useCountdown` hook near the top of `DevPanel.tsx` (before the `WalletCard` component):

```tsx
function useCountdown(target: string | null | undefined): string {
  const [display, setDisplay] = useState('')

  useEffect(() => {
    if (!target) return
    const update = () => {
      const diff = new Date(target).getTime() - Date.now()
      if (diff <= 0) {
        setDisplay('已截止')
        return
      }
      const h = Math.floor(diff / 3_600_000)
      const m = Math.floor((diff % 3_600_000) / 60_000)
      const s = Math.floor((diff % 60_000) / 1_000)
      if (h > 0) setDisplay(`${h}小时${m}分钟后到期`)
      else if (m > 0) setDisplay(`${m}分${s}秒后到期`)
      else setDisplay(`${s}秒后到期`)
    }
    update()
    const id = setInterval(update, 1000)
    return () => clearInterval(id)
  }, [target])

  return display
}
```

**Step 2: Use countdown in published task card**

Inside `DevPanel`, add:
```tsx
const deadlineCountdown = useCountdown(publishedTask?.deadline)
const challengeCountdown = useCountdown(publishedTask?.challenge_window_end)
```

In the published task card, replace the static deadline display with:
```tsx
<p className="text-muted-foreground">
  Deadline: <span className="text-white">{deadlineCountdown || '—'}</span>
</p>
{publishedTask.status === 'challenge_window' && publishedTask.challenge_window_end && (
  <p className="text-muted-foreground">
    挑战期剩余: <span className="text-yellow-400">{challengeCountdown}</span>
  </p>
)}
```

**Step 3: Run frontend lint**

```bash
cd frontend && npm run lint
```
Expected: no errors

**Step 4: Commit**

```bash
git add frontend/components/DevPanel.tsx
git commit -m "feat: add deadline and challenge window countdowns"
```

---

### Task 7: Frontend — display revision suggestions

**Files:**
- Modify: `frontend/components/DevPanel.tsx`

**Step 1: Update submission result display**

In the `polledSub` card (around line 685–714), replace the `oracle_feedback` paragraph:

```tsx
{polledSub.oracle_feedback && (() => {
  let suggestions: string[] = []
  try { suggestions = JSON.parse(polledSub.oracle_feedback) } catch { /* plain string */ }
  return suggestions.length > 0 ? (
    <div>
      <p className="text-muted-foreground mb-1">修订建议：</p>
      <ul className="list-disc list-inside space-y-0.5">
        {suggestions.map((s, i) => (
          <li key={i} className="text-white">{s}</li>
        ))}
      </ul>
    </div>
  ) : (
    <p className="text-muted-foreground">
      Feedback: <span className="text-white">{polledSub.oracle_feedback}</span>
    </p>
  )
})()}
```

Also update the status display to differentiate quality_first pending (waiting for feedback) from scored:

```tsx
{polledSub.status === 'pending' ? (
  <>
    <span className="inline-block w-3 h-3 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
    <span className="text-yellow-400 font-medium">等待反馈…</span>
  </>
) : (
  <span className="text-green-400 font-medium">已评分</span>
)}
```

**Step 2: Run frontend lint and tests**

```bash
cd frontend && npm run lint && npm test
```
Expected: no errors, all 18 tests PASS

**Step 3: Commit**

```bash
git add frontend/components/DevPanel.tsx
git commit -m "feat: display oracle revision suggestions as bullet list"
```

---

### Task 8: Full integration check

**Step 1: Run all backend tests**

```bash
pytest -v
```
Expected: all 53+ tests PASS

**Step 2: Run all frontend tests**

```bash
cd frontend && npm test
```
Expected: all 18 tests PASS

**Step 3: Start both servers and do manual smoke test**

```bash
# Terminal 1
uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

Manual checks:
- Open http://localhost:3000
- Publish a quality_first task with 5min deadline → task ID shows, deadline countdown ticks
- Submit as Bob → wait a few seconds → 3 revision suggestions appear, no score visible
- Wait for deadline → scheduler runs → score appears
- Publish a fastest_first task → submit → score shows immediately

**Step 4: Commit if any cleanup needed, then push**

```bash
git push origin agent-teams-test
```
