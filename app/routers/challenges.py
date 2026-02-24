from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Task, Submission, Challenge, TaskStatus
from ..schemas import ChallengeCreate, ChallengeOut
from ..services.escrow import check_usdc_balance, join_challenge_onchain

SERVICE_FEE = 0.01  # 0.01 USDC

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

    # --- Escrow integration (only when permit params provided) ---
    deposit_tx_hash = None
    if data.challenger_wallet and data.permit_v is not None:
        deposit_amount = task.submission_deposit or round(task.bounty * 0.10, 6)
        required = deposit_amount + SERVICE_FEE

        # 1. Balance check
        try:
            balance = check_usdc_balance(data.challenger_wallet)
        except Exception:
            balance = 0.0
        if balance < required:
            raise HTTPException(status_code=400, detail=f"USDC余额不足 (需要 {required}, 余额 {balance})")

        # 2. Rate limit: same wallet, 1 challenge per minute
        recent = db.query(Challenge).filter(
            Challenge.challenger_wallet == data.challenger_wallet,
            Challenge.created_at > datetime.now(timezone.utc) - timedelta(minutes=1),
        ).first()
        if recent:
            raise HTTPException(status_code=429, detail="每分钟最多提交一次挑战")

        # 3. Relayer: call joinChallenge on-chain
        try:
            deposit_tx_hash = join_challenge_onchain(
                task_id,
                data.challenger_wallet,
                data.permit_deadline,
                data.permit_v,
                data.permit_r,
                data.permit_s,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"链上交易失败: {e}")

    challenge = Challenge(
        task_id=task_id,
        challenger_submission_id=data.challenger_submission_id,
        target_submission_id=task.winner_submission_id,
        reason=data.reason,
        challenger_wallet=data.challenger_wallet,
        deposit_tx_hash=deposit_tx_hash,
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
