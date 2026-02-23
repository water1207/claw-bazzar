from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..models import Task, TaskStatus, TaskType, Submission
from ..schemas import TaskCreate, TaskOut, TaskDetail, SubmissionOut
from ..services.x402 import build_payment_requirements, verify_payment

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, request: Request, db: Session = Depends(get_db)):
    tx_hash = None
    if data.bounty and data.bounty > 0:
        payment_header = request.headers.get("x-payment")
        if not payment_header:
            return JSONResponse(
                status_code=402,
                content=build_payment_requirements(data.bounty),
            )
        result = verify_payment(payment_header, data.bounty)
        if not result["valid"]:
            return JSONResponse(
                status_code=402,
                content=build_payment_requirements(data.bounty),
            )
        tx_hash = result.get("tx_hash")
    task = Task(**data.model_dump(), payment_tx_hash=tx_hash)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=List[TaskOut])
def list_tasks(
    status: Optional[TaskStatus] = None,
    type: Optional[TaskType] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Task)
    if status:
        q = q.filter(Task.status == status)
    if type:
        q = q.filter(Task.type == type)
    return q.order_by(Task.created_at.desc()).all()


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    subs = db.query(Submission).filter(Submission.task_id == task_id).all()
    result = TaskDetail.model_validate(task)

    hide_content = task.status in (
        TaskStatus.challenge_window,
        TaskStatus.arbitrating,
    )
    sub_outs = []
    for s in subs:
        out = SubmissionOut.model_validate(s)
        if hide_content and s.id != task.winner_submission_id:
            out.content = "[hidden]"
        sub_outs.append(out)
    result.submissions = sub_outs
    return result
