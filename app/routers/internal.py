from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Submission, Task, SubmissionStatus, TaskStatus, PayoutStatus
from ..schemas import ScoreInput
from ..services.payout import pay_winner
from ..services.arbiter import run_arbitration

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


@router.post("/tasks/{task_id}/payout")
def retry_payout(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.winner_submission_id:
        raise HTTPException(status_code=400, detail="Task has no winner")
    if task.payout_status == PayoutStatus.paid:
        raise HTTPException(status_code=400, detail="Task already paid out")
    pay_winner(db, task.id)
    return {"ok": True}


@router.post("/tasks/{task_id}/arbitrate")
def trigger_arbitration(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.arbitrating:
        raise HTTPException(status_code=400, detail="Task is not in arbitrating state")
    run_arbitration(db, task_id)
    return {"ok": True}
