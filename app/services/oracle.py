import json
import subprocess
import sys
from pathlib import Path
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Submission, Task, SubmissionStatus, TaskStatus, TaskType, ScoringDimension
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


def generate_dimensions(db: Session, task: Task) -> list:
    """Generate and lock scoring dimensions for a task via LLM."""
    payload = {
        "mode": "dimension_gen",
        "task_title": task.title,
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
    }
    output = _call_oracle(payload)
    dimensions = output.get("dimensions", [])

    for dim_data in dimensions:
        dim = ScoringDimension(
            task_id=task.id,
            dim_id=dim_data["id"],
            name=dim_data["name"],
            dim_type=dim_data["type"],
            description=dim_data["description"],
            weight=dim_data["weight"],
            scoring_guidance=dim_data["scoring_guidance"],
        )
        db.add(dim)
    db.commit()
    return dimensions


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
