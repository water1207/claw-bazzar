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
