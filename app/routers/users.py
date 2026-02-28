from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, Submission, Task, TaskStatus, PayoutStatus, SubmissionStatus
from ..schemas import UserCreate, UserOut, UserStats

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserOut)
def get_user_by_nickname(nickname: str = Query(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.nickname == nickname).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


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


@router.get("/{user_id}/stats", response_model=UserStats)
def get_user_stats(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Tasks participated (distinct task_id from submissions)
    tasks_participated = (
        db.query(func.count(func.distinct(Submission.task_id)))
        .filter(Submission.worker_id == user_id)
        .scalar()
    ) or 0

    # Submissions by this user
    sub_ids = [
        s.id for s in db.query(Submission.id).filter(Submission.worker_id == user_id).all()
    ]

    # Tasks won
    tasks_won = 0
    total_earned = 0.0
    if sub_ids:
        won_tasks = (
            db.query(Task)
            .filter(
                Task.winner_submission_id.in_(sub_ids),
                Task.status == TaskStatus.closed,
            )
            .all()
        )
        tasks_won = len(won_tasks)
        total_earned = sum(t.payout_amount or 0 for t in won_tasks if t.payout_status == PayoutStatus.paid)

    win_rate = tasks_won / tasks_participated if tasks_participated > 0 else 0.0

    # Malicious submissions (policy_violation)
    malicious_count = (
        db.query(func.count(Submission.id))
        .filter(
            Submission.worker_id == user_id,
            Submission.status == SubmissionStatus.policy_violation,
        )
        .scalar()
    ) or 0

    # Submissions in last 30 days
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    submissions_last_30d = (
        db.query(func.count(Submission.id))
        .filter(
            Submission.worker_id == user_id,
            Submission.created_at >= thirty_days_ago,
        )
        .scalar()
    ) or 0

    return UserStats(
        tasks_participated=tasks_participated,
        tasks_won=tasks_won,
        win_rate=round(win_rate, 4),
        total_earned=round(total_earned, 6),
        malicious_count=malicious_count,
        submissions_last_30d=submissions_last_30d,
        registered_at=user.created_at,
    )
