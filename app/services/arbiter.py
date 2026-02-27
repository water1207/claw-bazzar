import json
import subprocess
import sys
from pathlib import Path
from sqlalchemy.orm import Session
from ..models import Challenge, Task, Submission, ChallengeVerdict, ChallengeStatus

ARBITER_SCRIPT = Path(__file__).parent.parent.parent / "oracle" / "arbiter.py"


def run_arbitration(db: Session, task_id: str) -> None:
    """Call arbiter for all pending challenges on a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    winner_sub = db.query(Submission).filter(
        Submission.id == task.winner_submission_id
    ).first()
    if not winner_sub:
        return

    challenges = db.query(Challenge).filter(
        Challenge.task_id == task_id,
        Challenge.status == ChallengeStatus.pending,
    ).all()
    if not challenges:
        return

    challenge_payloads = []
    for c in challenges:
        challenger_sub = db.query(Submission).filter(
            Submission.id == c.challenger_submission_id
        ).first()
        challenge_payloads.append({
            "id": c.id,
            "reason": c.reason,
            "challenger_submission": {
                "id": challenger_sub.id,
                "content": challenger_sub.content,
                "score": challenger_sub.score,
            } if challenger_sub else {},
        })

    payload = json.dumps({
        "task": {"id": task.id, "description": task.description},
        "winner_submission": {
            "id": winner_sub.id,
            "content": winner_sub.content,
            "score": winner_sub.score,
        },
        "challenges": challenge_payloads,
    })

    result = subprocess.run(
        [sys.executable, str(ARBITER_SCRIPT)],
        input=payload, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    output = json.loads(result.stdout)

    verdict_map = {v["challenge_id"]: v for v in output.get("verdicts", [])}
    for c in challenges:
        v = verdict_map.get(c.id)
        if v:
            c.verdict = ChallengeVerdict(v["verdict"])
            c.arbiter_score = v.get("score", 0)
            c.arbiter_feedback = v.get("feedback")
            c.status = ChallengeStatus.judged

    db.commit()
