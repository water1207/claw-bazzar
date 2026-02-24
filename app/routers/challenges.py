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
        challenger_wallet=data.challenger_wallet,
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
