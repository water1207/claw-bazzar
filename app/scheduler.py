from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from .models import Task, Submission, TaskType, TaskStatus


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
