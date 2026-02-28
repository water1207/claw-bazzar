import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..models import Task, TaskStatus, TaskType, Submission, ScoringDimension, User
from ..schemas import TaskCreate, TaskOut, TaskDetail, SubmissionOut, ScoringDimensionPublic
from ..services.oracle import generate_dimensions
from ..services.x402 import build_payment_requirements, verify_payment

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, request: Request, db: Session = Depends(get_db)):
    payment_header = request.headers.get("x-payment")
    if not payment_header:
        return JSONResponse(
            status_code=402,
            content=build_payment_requirements(data.bounty),
        )
    result = verify_payment(payment_header, data.bounty)
    if not result["valid"]:
        reqs = build_payment_requirements(data.bounty)
        reqs["error"] = result.get("reason", "payment verification failed")
        return JSONResponse(status_code=402, content=reqs)
    tx_hash = result.get("tx_hash")

    task_data = data.model_dump()
    task_data['acceptance_criteria'] = json.dumps(data.acceptance_criteria, ensure_ascii=False)
    task = Task(**task_data, payment_tx_hash=tx_hash)
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        generate_dimensions(db, task)
    except Exception as e:
        print(f"[tasks] dimension generation failed: {e}", flush=True)

    dims = db.query(ScoringDimension).filter(ScoringDimension.task_id == task.id).all()
    result_out = TaskOut.model_validate(task)
    result_out.scoring_dimensions = [
        ScoringDimensionPublic(name=d.name, description=d.description) for d in dims
    ]
    if task.publisher_id:
        pub_user = db.query(User).filter(User.id == task.publisher_id).first()
        if pub_user:
            result_out.publisher_nickname = pub_user.nickname
    return result_out


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
    tasks = q.order_by(Task.created_at.desc()).all()
    # Resolve publisher nicknames
    pub_ids = {t.publisher_id for t in tasks if t.publisher_id}
    nickname_map: dict[str, str] = {}
    if pub_ids:
        users = db.query(User.id, User.nickname).filter(User.id.in_(pub_ids)).all()
        nickname_map = {u.id: u.nickname for u in users}
    results = []
    for t in tasks:
        out = TaskOut.model_validate(t)
        if t.publisher_id:
            out.publisher_nickname = nickname_map.get(t.publisher_id)
        results.append(out)
    return results


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    subs = db.query(Submission).filter(Submission.task_id == task_id).all()
    dims = db.query(ScoringDimension).filter(ScoringDimension.task_id == task_id).all()
    result = TaskDetail.model_validate(task)
    result.scoring_dimensions = [
        ScoringDimensionPublic(name=d.name, description=d.description) for d in dims
    ]
    if task.publisher_id:
        pub_user = db.query(User).filter(User.id == task.publisher_id).first()
        if pub_user:
            result.publisher_nickname = pub_user.nickname

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
