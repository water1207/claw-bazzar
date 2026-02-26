from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Task, Submission, User, TaskStatus, TaskType
from ..schemas import SubmissionCreate, SubmissionOut
from ..services.oracle import invoke_oracle
from ..services.trust import check_permissions

router = APIRouter(tags=["submissions"])


def _maybe_hide_score(submission: Submission, task: Task, db: Session = None) -> Submission:
    """Null out score for quality_first tasks that haven't reached challenge_window yet."""
    if task.type == TaskType.quality_first and task.status in (
        TaskStatus.open, TaskStatus.scoring
    ):
        if db:
            db.expunge(submission)
        submission.score = None
    return submission



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
    deadline = task.deadline if task.deadline.tzinfo else task.deadline.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > deadline:
        raise HTTPException(status_code=400, detail="Task deadline has passed")

    # Trust-based permission checks
    worker = db.query(User).filter_by(id=data.worker_id).first()
    if worker:
        perms = check_permissions(worker)
        if not perms["can_accept_tasks"]:
            raise HTTPException(status_code=403, detail="Your trust level does not allow accepting tasks")
        if perms["max_task_amount"] and task.bounty and task.bounty > perms["max_task_amount"]:
            raise HTTPException(status_code=403, detail=f"Your trust level limits tasks to {perms['max_task_amount']} USDC")

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
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    subs = db.query(Submission).filter(Submission.task_id == task_id).all()
    return [_maybe_hide_score(s, task, db) for s in subs]


@router.get("/tasks/{task_id}/submissions/{sub_id}", response_model=SubmissionOut)
def get_submission(task_id: str, sub_id: str, db: Session = Depends(get_db)):
    sub = db.query(Submission).filter(
        Submission.id == sub_id, Submission.task_id == task_id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    task = db.query(Task).filter(Task.id == task_id).first()
    return _maybe_hide_score(sub, task, db)
