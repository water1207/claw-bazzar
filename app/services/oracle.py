import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from ..database import SessionLocal
from ..models import Submission, Task, SubmissionStatus, TaskStatus, TaskType, ScoringDimension
from .payout import pay_winner

ORACLE_SCRIPT = Path(__file__).parent.parent.parent / "oracle" / "oracle.py"

# In-memory oracle call logs
_oracle_logs: list[dict] = []
MAX_LOGS = 200
_oracle_logs_lock = threading.Lock()


def get_oracle_logs(limit: int = 50) -> list[dict]:
    """Return recent oracle logs, newest first."""
    with _oracle_logs_lock:
        return list(reversed(_oracle_logs))[:limit]


PENALTY_THRESHOLD = 60

FIXED_DIM_NAMES = {
    "substantiveness": "实质性",
    "credibility": "可信度",
    "completeness": "完整性",
}


def compute_penalized_total(
    dim_scores: dict[str, dict],
    dims: list[dict],
) -> dict:
    """Compute non-linear penalized total score.

    Args:
        dim_scores: {dim_id: {"score": int, "band": str, ...}}
        dims: [{"dim_id": str, "dim_type": str, "weight": float}]

    Returns:
        {"weighted_base", "penalty", "penalty_reasons", "final_score", "risk_flags"}
    """
    weighted_base = 0.0
    penalty = 1.0
    penalty_reasons = []
    risk_flags = []

    for dim in dims:
        dim_id = dim["dim_id"]
        weight = dim["weight"]
        score_entry = dim_scores.get(dim_id, {})
        score = score_entry.get("score", 0)
        weighted_base += score * weight

        if dim["dim_type"] == "fixed" and score < PENALTY_THRESHOLD:
            penalty *= score / PENALTY_THRESHOLD
            name = FIXED_DIM_NAMES.get(dim_id, dim_id)
            penalty_reasons.append(f"关键维度「{name}」低于预期")
            risk_flags.append(f"{name}偏低")

    final_score = round(weighted_base * penalty, 2)
    weighted_base = round(weighted_base, 2)
    penalty = round(penalty, 4)

    return {
        "weighted_base": weighted_base,
        "penalty": penalty,
        "penalty_reasons": penalty_reasons,
        "final_score": final_score,
        "risk_flags": risk_flags,
    }


def _call_oracle(payload: dict, meta: dict | None = None) -> dict:
    """Call oracle subprocess. meta provides context for logging:
    task_id, task_title, submission_id, worker_id."""
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(ORACLE_SCRIPT)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=120,
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    if result.returncode != 0:
        print(f"[oracle] subprocess error: {result.stderr}", flush=True)
    output = json.loads(result.stdout)

    # Extract and log token usage
    token_usage = output.pop("_token_usage", None)
    if token_usage:
        m = meta or {}
        log_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": payload.get("mode", "unknown"),
            "task_id": m.get("task_id", ""),
            "task_title": m.get("task_title", ""),
            "submission_id": m.get("submission_id", ""),
            "worker_id": m.get("worker_id", ""),
            "model": os.environ.get("ORACLE_LLM_MODEL", ""),
            "prompt_tokens": token_usage.get("prompt_tokens", 0),
            "completion_tokens": token_usage.get("completion_tokens", 0),
            "total_tokens": token_usage.get("total_tokens", 0),
            "duration_ms": duration_ms,
        }
        with _oracle_logs_lock:
            _oracle_logs.append(log_entry)
            if len(_oracle_logs) > MAX_LOGS:
                _oracle_logs[:] = _oracle_logs[-MAX_LOGS:]

    return output


def _build_payload(task: Task, submission: Submission, mode: str) -> dict:
    return {
        "mode": mode,
        "task": {
            "id": task.id, "description": task.description,
            "type": task.type.value, "threshold": task.threshold,
        },
        "submission": {
            "id": submission.id, "content": submission.content,
            "revision": submission.revision, "worker_id": submission.worker_id,
        },
    }


def generate_dimensions(db: Session, task: Task) -> list:
    """Generate and lock scoring dimensions for a task via LLM."""
    payload = {
        "mode": "dimension_gen",
        "task_title": task.title,
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
    }
    meta = {"task_id": task.id, "task_title": task.title}
    output = _call_oracle(payload, meta=meta)
    dimensions = output.get("dimensions", [])

    for dim_data in dimensions:
        dim = ScoringDimension(
            task_id=task.id,
            dim_id=dim_data["id"],
            name=dim_data["name"],
            dim_type=dim_data["type"],
            description=dim_data["description"],
            weight=dim_data["weight"],
            scoring_guidance=dim_data["scoring_guidance"],
        )
        db.add(dim)
    db.commit()
    return dimensions


def give_feedback(db: Session, submission_id: str, task_id: str) -> None:
    """quality_first submission: gate_check → score_individual (if pass)."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not submission or not task:
        return

    # Step 1: Gate Check
    sub_meta = {"task_id": task.id, "task_title": task.title,
                "submission_id": submission.id, "worker_id": submission.worker_id}
    gate_payload = {
        "mode": "gate_check",
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
        "submission_payload": submission.content,
    }
    gate_result = _call_oracle(gate_payload, meta=sub_meta)

    if not gate_result.get("overall_passed", False):
        submission.oracle_feedback = json.dumps({
            "type": "gate_check",
            **gate_result,
        })
        submission.status = SubmissionStatus.gate_failed
        db.commit()
        return

    # Gate passed — commit immediately so status never stays stuck at pending
    submission.oracle_feedback = json.dumps({
        "type": "gate_check",
        **gate_result,
    })
    submission.status = SubmissionStatus.gate_passed
    db.commit()

    # Step 2: Individual scoring (score hidden, revision suggestions returned)
    dimensions = db.query(ScoringDimension).filter(
        ScoringDimension.task_id == task_id
    ).all()
    dims_data = [
        {"id": d.dim_id, "name": d.name, "description": d.description,
         "weight": d.weight, "scoring_guidance": d.scoring_guidance}
        for d in dimensions
    ]

    score_payload = {
        "mode": "score_individual",
        "task_title": task.title,
        "task_description": task.description,
        "dimensions": dims_data,
        "submission_payload": submission.content,
    }
    score_result = _call_oracle(score_payload, meta=sub_meta)

    submission.oracle_feedback = json.dumps({
        "type": "individual_scoring",
        **score_result,
    })
    db.commit()


def score_submission(db: Session, submission_id: str, task_id: str) -> None:
    """Score a single submission (fastest_first path): gate_check + score_individual + penalized_total."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not submission or not task:
        return

    sub_meta = {"task_id": task.id, "task_title": task.title,
                "submission_id": submission.id, "worker_id": submission.worker_id}

    # Step 1: Gate Check
    gate_payload = {
        "mode": "gate_check",
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
        "submission_payload": submission.content,
    }
    gate_result = _call_oracle(gate_payload, meta=sub_meta)

    if not gate_result.get("overall_passed", False):
        submission.oracle_feedback = json.dumps({
            "type": "scoring",
            "gate_check": gate_result,
            "passed": False,
        })
        submission.score = 0.0
        submission.status = SubmissionStatus.scored
        db.commit()
        return

    # Step 2: Score Individual (band-first + evidence)
    dimensions = db.query(ScoringDimension).filter(
        ScoringDimension.task_id == task_id
    ).all()

    if not dimensions:
        # V1 fallback — no dimensions available
        output = _call_oracle(_build_payload(task, submission, "score"), meta=sub_meta)
        submission.score = output.get("score", 0.0)
        submission.oracle_feedback = json.dumps({
            "type": "scoring",
            "passed": submission.score >= (task.threshold or 0),
            **output,
        })
        submission.status = SubmissionStatus.scored
        db.commit()
        if submission.score >= (task.threshold or 0):
            _apply_fastest_first(db, task, submission)
        return

    dims_data = [
        {"id": d.dim_id, "name": d.name, "description": d.description,
         "weight": d.weight, "scoring_guidance": d.scoring_guidance}
        for d in dimensions
    ]
    score_payload = {
        "mode": "score_individual",
        "task_title": task.title,
        "task_description": task.description,
        "dimensions": dims_data,
        "submission_payload": submission.content,
    }
    score_result = _call_oracle(score_payload, meta=sub_meta)

    # Step 3: Compute penalized_total
    dim_scores = score_result.get("dimension_scores", {})
    dims_for_penalty = [
        {"dim_id": d.dim_id, "dim_type": d.dim_type, "weight": d.weight}
        for d in dimensions
    ]
    penalty_result = compute_penalized_total(dim_scores, dims_for_penalty)

    final_score = penalty_result["final_score"]
    passed = final_score >= PENALTY_THRESHOLD

    submission.oracle_feedback = json.dumps({
        "type": "scoring",
        "dimension_scores": dim_scores,
        "overall_band": score_result.get("overall_band", ""),
        "revision_suggestions": score_result.get("revision_suggestions", []),
        "weighted_base": penalty_result["weighted_base"],
        "penalty": penalty_result["penalty"],
        "penalty_reasons": penalty_result["penalty_reasons"],
        "final_score": final_score,
        "risk_flags": penalty_result["risk_flags"],
        "passed": passed,
    })
    submission.score = final_score / 100.0
    submission.status = SubmissionStatus.scored
    db.commit()

    if passed:
        _apply_fastest_first(db, task, submission)


def _get_individual_weighted_total(submission: Submission, dimensions: list) -> float:
    """Calculate weighted total from individual scoring stored in oracle_feedback."""
    if not submission.oracle_feedback:
        return 0.0
    try:
        feedback = json.loads(submission.oracle_feedback)
        if feedback.get("type") != "individual_scoring":
            return 0.0
        dim_scores = feedback.get("dimension_scores", {})
        total = 0.0
        for dim in dimensions:
            score_entry = dim_scores.get(dim.dim_id, {})
            total += score_entry.get("score", 0) * dim.weight
        return total
    except (json.JSONDecodeError, KeyError):
        return 0.0


BAND_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


def _get_individual_ir(submission: Submission) -> dict:
    """Extract individual scoring IR (band + evidence per dimension) from oracle_feedback."""
    if not submission.oracle_feedback:
        return {}
    try:
        feedback = json.loads(submission.oracle_feedback)
        if feedback.get("type") != "individual_scoring":
            return {}
        dim_scores = feedback.get("dimension_scores", {})
        return {
            dim_id: {"band": v.get("band", "?"), "evidence": v.get("evidence", "")}
            for dim_id, v in dim_scores.items()
        }
    except (json.JSONDecodeError, KeyError):
        return {}


def _passes_threshold_filter(submission: Submission, fixed_dim_ids: set) -> bool:
    """Check if all fixed dimensions have band >= C (i.e., not D or E)."""
    if not submission.oracle_feedback:
        return False
    try:
        feedback = json.loads(submission.oracle_feedback)
        dim_scores = feedback.get("dimension_scores", {})
        for dim_id in fixed_dim_ids:
            entry = dim_scores.get(dim_id, {})
            band = entry.get("band", "E")
            if BAND_ORDER.get(band, 4) > BAND_ORDER["C"]:  # D or E
                return False
        return True
    except (json.JSONDecodeError, KeyError):
        return False


def batch_score_submissions(db: Session, task_id: str) -> None:
    """Score all gate_passed submissions after deadline: threshold filter + horizontal comparison."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    passed = db.query(Submission).filter(
        Submission.task_id == task_id,
        Submission.status == SubmissionStatus.gate_passed,
    ).all()

    # Backward compat with V1 tests
    if not passed:
        passed = db.query(Submission).filter(
            Submission.task_id == task_id,
            Submission.status == SubmissionStatus.pending,
        ).all()

    if not passed:
        return

    dimensions = db.query(ScoringDimension).filter(
        ScoringDimension.task_id == task_id
    ).all()

    task_meta = {"task_id": task.id, "task_title": task.title}

    # V1 fallback: no dimensions
    if not dimensions:
        for submission in passed:
            m = {**task_meta, "submission_id": submission.id, "worker_id": submission.worker_id}
            output = _call_oracle(_build_payload(task, submission, "score"), meta=m)
            submission.score = output.get("score", 0.0)
            submission.oracle_feedback = output.get("feedback", submission.oracle_feedback)
            submission.status = SubmissionStatus.scored
        db.commit()
        return

    dims_data = [
        {"id": d.dim_id, "name": d.name, "description": d.description,
         "weight": d.weight, "scoring_guidance": d.scoring_guidance}
        for d in dimensions
    ]
    fixed_dim_ids = {d.dim_id for d in dimensions if d.dim_type == "fixed"}

    # Step 1: Threshold filter — any fixed dim band < C → below_threshold
    eligible = []
    below_threshold = []
    for sub in passed:
        if _passes_threshold_filter(sub, fixed_dim_ids):
            eligible.append(sub)
        else:
            below_threshold.append(sub)

    # Mark below_threshold subs as scored with their penalized individual score
    for sub in below_threshold:
        try:
            feedback = json.loads(sub.oracle_feedback)
            dim_scores_for_penalty = feedback.get("dimension_scores", {})
        except (json.JSONDecodeError, KeyError):
            dim_scores_for_penalty = {}
        dims_for_penalty = [{"dim_id": d.dim_id, "dim_type": d.dim_type, "weight": d.weight} for d in dimensions]
        penalty_result = compute_penalized_total(dim_scores_for_penalty, dims_for_penalty)
        sub.score = penalty_result["final_score"] / 100.0
        sub.status = SubmissionStatus.scored

    if not eligible:
        db.commit()
        return

    # Step 2: Sort by penalized_total from individual scores, take top 3
    def _get_penalized_total(sub):
        try:
            feedback = json.loads(sub.oracle_feedback)
            dim_scores = feedback.get("dimension_scores", {})
        except (json.JSONDecodeError, KeyError):
            dim_scores = {}
        dims_for_penalty = [{"dim_id": d.dim_id, "dim_type": d.dim_type, "weight": d.weight} for d in dimensions]
        return compute_penalized_total(dim_scores, dims_for_penalty)["final_score"]

    eligible.sort(key=_get_penalized_total, reverse=True)
    top_subs = eligible[:3]

    # Anonymize
    label_map = {}
    anonymized = []
    for i, sub in enumerate(top_subs):
        label = f"Submission_{chr(65 + i)}"
        label_map[label] = sub
        anonymized.append({"label": label, "payload": sub.content})

    # Build individual IR for dimension_score reference
    individual_ir_map = {}
    for anon in anonymized:
        sub = label_map[anon["label"]]
        ir = _get_individual_ir(sub)
        for dim_data in dims_data:
            dim_id = dim_data["id"]
            if dim_id not in individual_ir_map:
                individual_ir_map[dim_id] = {}
            individual_ir_map[dim_id][anon["label"]] = ir.get(dim_id, {"band": "?", "evidence": ""})

    # Step 3: Horizontal scoring per dimension
    all_scores = {}
    for dim_data in dims_data:
        dim_payload = {
            "mode": "dimension_score",
            "task_title": task.title,
            "task_description": task.description,
            "dimension": dim_data,
            "individual_ir": individual_ir_map.get(dim_data["id"], {}),
            "submissions": anonymized,
        }
        result = _call_oracle(dim_payload, meta=task_meta)
        all_scores[dim_data["id"]] = result

    # Step 4: Compute ranking with penalized_total
    ranking = []
    for anon in anonymized:
        label = anon["label"]
        dim_scores_for_ranking = {}
        breakdown = {}
        for dim_data in dims_data:
            dim_id = dim_data["id"]
            scores_list = all_scores[dim_id].get("scores", [])
            entry = next((s for s in scores_list if s["submission"] == label), None)
            if entry:
                breakdown[dim_id] = {
                    "raw_score": entry["raw_score"],
                    "final_score": entry["final_score"],
                    "evidence": entry.get("evidence", ""),
                }
                dim_scores_for_ranking[dim_id] = {"score": entry["final_score"]}

        dims_for_penalty = [{"dim_id": d.dim_id, "dim_type": d.dim_type, "weight": d.weight} for d in dimensions]
        penalty_result = compute_penalized_total(dim_scores_for_ranking, dims_for_penalty)

        ranking.append({
            "label": label,
            "dimension_breakdown": breakdown,
            **penalty_result,
        })

    ranking.sort(key=lambda x: x["final_score"], reverse=True)

    # Write back to submissions
    for rank_idx, entry in enumerate(ranking):
        sub = label_map[entry["label"]]
        sub.oracle_feedback = json.dumps({
            "type": "scoring",
            "dimension_scores": entry["dimension_breakdown"],
            "weighted_base": entry["weighted_base"],
            "penalty": entry["penalty"],
            "penalty_reasons": entry["penalty_reasons"],
            "final_score": entry["final_score"],
            "risk_flags": entry["risk_flags"],
            "rank": rank_idx + 1,
        })
        sub.score = entry["final_score"] / 100.0
        sub.status = SubmissionStatus.scored

    # Mark remaining eligible subs (outside top 3) as scored
    for sub in eligible:
        if sub not in [label_map[a["label"]] for a in anonymized]:
            sub.status = SubmissionStatus.scored
            if not sub.score:
                sub.score = _get_individual_weighted_total(sub, dimensions) / 100.0

    db.commit()


def _apply_fastest_first(db: Session, task: Task, submission: Submission) -> None:
    if task.type.value != "fastest_first" or task.status != TaskStatus.open:
        return
    if task.threshold is not None and submission.score >= task.threshold:
        task.winner_submission_id = submission.id
        task.status = TaskStatus.closed
        db.commit()
        pay_winner(db, task.id)
        from .trust import apply_event
        from ..models import TrustEventType, User
        if db.query(User).filter_by(id=task.publisher_id).first():
            apply_event(db, task.publisher_id, TrustEventType.publisher_completed,
                        task_bounty=task.bounty or 0.0, task_id=task.id)


def invoke_oracle(submission_id: str, task_id: str) -> None:
    """Entry point for FastAPI BackgroundTasks. Creates its own db session."""
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task and task.type == TaskType.quality_first:
            give_feedback(db, submission_id, task_id)
        else:
            score_submission(db, submission_id, task_id)
    except Exception as e:
        print(f"[oracle] Error for submission {submission_id}: {e}", flush=True)
    finally:
        db.close()
