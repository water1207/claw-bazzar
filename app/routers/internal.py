from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import (
    Submission, Task, Challenge, User,
    SubmissionStatus, TaskStatus, PayoutStatus, ChallengeStatus,
)
from ..schemas import ScoreInput, ManualJudgeInput, ChallengeOut
from ..services.payout import pay_winner
from ..services.arbiter import run_arbitration
from ..services.oracle import get_oracle_logs

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


@router.post("/challenges/{challenge_id}/judge", response_model=ChallengeOut)
def judge_challenge(challenge_id: str, data: ManualJudgeInput, db: Session = Depends(get_db)):
    challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    task = db.query(Task).filter(Task.id == challenge.task_id).first()
    if not task or task.status != TaskStatus.arbitrating:
        raise HTTPException(status_code=400, detail="Task is not in arbitrating state")

    if challenge.status == ChallengeStatus.judged:
        raise HTTPException(status_code=400, detail="Challenge already judged")

    challenge.verdict = data.verdict
    challenge.arbiter_score = data.score
    challenge.arbiter_feedback = data.feedback
    challenge.status = ChallengeStatus.judged
    db.commit()
    db.refresh(challenge)
    return challenge


@router.get("/oracle-logs")
def oracle_logs(
    task_count: int = Query(default=5, ge=1, le=50, description="Return logs for the N most recent tasks"),
    limit: int = Query(default=200, ge=1, le=500, description="Max log entries to return"),
    db: Session = Depends(get_db),
):
    all_logs = get_oracle_logs(limit=limit)

    # Filter to the N most recent distinct tasks
    seen_tasks: list[str] = []
    for log in all_logs:
        tid = log.get("task_id", "")
        if tid and tid not in seen_tasks:
            seen_tasks.append(tid)
    recent_task_ids = set(seen_tasks[:task_count])
    logs = [l for l in all_logs if l.get("task_id", "") in recent_task_ids]

    # Resolve worker nicknames
    worker_ids = {log["worker_id"] for log in logs if log.get("worker_id")}
    nickname_map: dict[str, str] = {}
    if worker_ids:
        users = db.query(User.id, User.nickname).filter(User.id.in_(worker_ids)).all()
        nickname_map = {u.id: u.nickname for u in users}
    for log in logs:
        log["worker_nickname"] = nickname_map.get(log.get("worker_id", ""), "")
    return logs
