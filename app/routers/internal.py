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
