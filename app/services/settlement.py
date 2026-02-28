"""Settlement breakdown computation."""
from sqlalchemy.orm import Session
from ..models import (
    Task, TaskStatus, TaskType, Submission, Challenge, ChallengeVerdict,
    User, JuryBallot,
)
from ..schemas import (
    SettlementOut, SettlementSource, SettlementDistribution, SettlementSummary,
)
from .trust import get_winner_payout_rate, get_platform_fee_rate


def compute_settlement(db: Session, task_id: str) -> SettlementOut | None:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or task.status not in (TaskStatus.closed, TaskStatus.voided):
        return None

    if task.type == TaskType.fastest_first:
        return _fastest_first_settlement(db, task)
    return _quality_first_settlement(db, task)


def _fastest_first_settlement(db: Session, task: Task) -> SettlementOut | None:
    """fastest_first: direct payout, no escrow/challenges."""
    if not task.winner_submission_id or not task.payout_amount:
        return None
    winner_sub = db.query(Submission).filter_by(id=task.winner_submission_id).first()
    winner_user = db.query(User).filter_by(id=winner_sub.worker_id).first() if winner_sub else None

    bounty = task.bounty or 0
    payout = task.payout_amount or 0
    platform_fee = round(bounty - payout, 6)

    sources = [SettlementSource(label="Bounty", amount=bounty, type="bounty")]
    distributions = [
        SettlementDistribution(
            label=f"Winner ({winner_user.nickname})" if winner_user else "Winner",
            amount=payout, type="winner",
            wallet=winner_user.wallet if winner_user else None,
            nickname=winner_user.nickname if winner_user else None,
        ),
        SettlementDistribution(
            label="Platform fee", amount=platform_fee, type="platform",
        ),
    ]
    tier = winner_user.trust_tier.value if winner_user else "A"
    try:
        rate = get_winner_payout_rate(winner_user.trust_tier) if winner_user else 0.80
    except ValueError:
        rate = 0.80

    return SettlementOut(
        escrow_total=bounty,
        sources=sources,
        distributions=[d for d in distributions if d.amount > 0],
        resolve_tx_hash=task.payout_tx_hash,
        summary=SettlementSummary(
            winner_payout=payout,
            winner_nickname=winner_user.nickname if winner_user else None,
            winner_tier=tier,
            payout_rate=rate,
            deposits_forfeited=0, deposits_refunded=0,
            arbiter_reward_total=0, platform_fee=platform_fee,
        ),
    )


def _quality_first_settlement(db: Session, task: Task) -> SettlementOut | None:
    bounty = task.bounty or 0
    escrow_amount = round(bounty * 0.95, 6)
    incentive = round(bounty * 0.05, 6)

    challenges = db.query(Challenge).filter(Challenge.task_id == task.id).all()
    total_deposits = sum(c.deposit_amount or 0 for c in challenges if c.challenger_wallet)

    # --- Sources ---
    sources: list[SettlementSource] = [
        SettlementSource(label="Bounty (95%)", amount=escrow_amount, type="bounty"),
        SettlementSource(label="Incentive (5%)", amount=incentive, type="incentive"),
    ]
    for c in challenges:
        if not c.challenger_wallet or not c.deposit_amount:
            continue
        sub = db.query(Submission).filter_by(id=c.challenger_submission_id).first()
        user = db.query(User).filter_by(id=sub.worker_id).first() if sub else None
        name = user.nickname if user else c.challenger_wallet[:10]
        sources.append(SettlementSource(
            label=f"{name} deposit",
            amount=c.deposit_amount,
            type="deposit",
            verdict=c.verdict.value if c.verdict else None,
        ))

    escrow_total = round(escrow_amount + incentive + total_deposits, 6)

    # --- Distributions ---
    distributions: list[SettlementDistribution] = []

    if task.status == TaskStatus.voided:
        return _voided_settlement(db, task, sources, escrow_total, challenges)

    # Winner
    winner_sub = db.query(Submission).filter_by(id=task.winner_submission_id).first() if task.winner_submission_id else None
    winner_user = db.query(User).filter_by(id=winner_sub.worker_id).first() if winner_sub else None
    winner_payout = task.payout_amount or 0

    if winner_payout > 0:
        distributions.append(SettlementDistribution(
            label=f"Winner ({winner_user.nickname})" if winner_user else "Winner",
            amount=winner_payout, type="winner",
            wallet=winner_user.wallet if winner_user else None,
            nickname=winner_user.nickname if winner_user else None,
        ))

    # Deposit refunds (upheld)
    deposits_refunded = 0.0
    deposits_forfeited = 0.0
    for c in challenges:
        if not c.challenger_wallet or not c.deposit_amount:
            continue
        sub = db.query(Submission).filter_by(id=c.challenger_submission_id).first()
        user = db.query(User).filter_by(id=sub.worker_id).first() if sub else None
        name = user.nickname if user else c.challenger_wallet[:10]
        if c.verdict == ChallengeVerdict.upheld:
            deposits_refunded += c.deposit_amount
            distributions.append(SettlementDistribution(
                label=f"Deposit refund ({name})",
                amount=c.deposit_amount, type="refund",
                wallet=c.challenger_wallet, nickname=name,
            ))
        else:
            deposits_forfeited += c.deposit_amount

    # Arbiter reward
    losing_deposits = sum(
        (c.deposit_amount or 0) for c in challenges
        if c.verdict != ChallengeVerdict.upheld and c.challenger_wallet
    )
    upheld = [c for c in challenges if c.verdict == ChallengeVerdict.upheld]
    is_challenger_win = len(upheld) > 0
    arbiter_from_pool = round(losing_deposits * 0.30, 6)
    arbiter_from_incentive = round((upheld[0].deposit_amount or 0) * 0.30, 6) if is_challenger_win else 0
    arbiter_reward = round(arbiter_from_pool + arbiter_from_incentive, 6)

    ballots = db.query(JuryBallot).filter_by(task_id=task.id).all()
    voted = [b for b in ballots if b.winner_submission_id is not None]
    if voted:
        coherent = [b for b in voted if b.coherence_status == "coherent"]
        arbiter_ids = [b.arbiter_user_id for b in (coherent or voted)]
        arbiter_users = db.query(User).filter(User.id.in_(arbiter_ids)).all()
        n = len(arbiter_users) or 1
        per_arbiter = round(arbiter_reward / n, 6)
        for u in arbiter_users:
            distributions.append(SettlementDistribution(
                label=f"Arbiter ({u.nickname})",
                amount=per_arbiter, type="arbiter",
                wallet=u.wallet, nickname=u.nickname,
            ))

    # Platform fee = remainder
    distributed = sum(d.amount for d in distributions)
    platform_fee = round(escrow_total - distributed, 6)
    if platform_fee > 0:
        distributions.append(SettlementDistribution(
            label="Platform fee", amount=platform_fee, type="platform",
        ))

    # Winner tier info
    tier = winner_user.trust_tier.value if winner_user else "A"
    try:
        rate = get_winner_payout_rate(winner_user.trust_tier, is_challenger_win) if winner_user else 0.80
    except ValueError:
        rate = 0.80

    return SettlementOut(
        escrow_total=escrow_total,
        sources=sources,
        distributions=distributions,
        resolve_tx_hash=task.payout_tx_hash,
        summary=SettlementSummary(
            winner_payout=winner_payout,
            winner_nickname=winner_user.nickname if winner_user else None,
            winner_tier=tier,
            payout_rate=rate,
            deposits_forfeited=round(deposits_forfeited, 6),
            deposits_refunded=round(deposits_refunded, 6),
            arbiter_reward_total=arbiter_reward,
            platform_fee=max(platform_fee, 0),
        ),
    )


def _voided_settlement(
    db: Session, task: Task,
    sources: list[SettlementSource], escrow_total: float,
    challenges: list[Challenge],
) -> SettlementOut:
    """Voided task: publisher refunded, malicious deposits forfeited."""
    bounty = task.bounty or 0
    publisher = db.query(User).filter_by(id=task.publisher_id).first()
    publisher_refund = round(bounty * 0.95, 6)

    distributions: list[SettlementDistribution] = []
    if publisher:
        distributions.append(SettlementDistribution(
            label=f"Publisher refund ({publisher.nickname})",
            amount=publisher_refund, type="publisher_refund",
            wallet=publisher.wallet, nickname=publisher.nickname,
        ))

    deposits_refunded = 0.0
    deposits_forfeited = 0.0
    for c in challenges:
        if not c.challenger_wallet or not c.deposit_amount:
            continue
        sub = db.query(Submission).filter_by(id=c.challenger_submission_id).first()
        user = db.query(User).filter_by(id=sub.worker_id).first() if sub else None
        name = user.nickname if user else c.challenger_wallet[:10]
        if c.verdict != ChallengeVerdict.malicious:
            deposits_refunded += c.deposit_amount
            distributions.append(SettlementDistribution(
                label=f"Deposit refund ({name})",
                amount=c.deposit_amount, type="refund",
                wallet=c.challenger_wallet, nickname=name,
            ))
        else:
            deposits_forfeited += c.deposit_amount

    arbiter_reward = round(bounty * 0.05, 6)
    ballots = db.query(JuryBallot).filter_by(task_id=task.id).all()
    voted = [b for b in ballots if b.winner_submission_id is not None]
    if voted:
        arbiter_users = db.query(User).filter(
            User.id.in_([b.arbiter_user_id for b in voted])
        ).all()
        n = len(arbiter_users) or 1
        per_arbiter = round(arbiter_reward / n, 6)
        for u in arbiter_users:
            distributions.append(SettlementDistribution(
                label=f"Arbiter ({u.nickname})",
                amount=per_arbiter, type="arbiter",
                wallet=u.wallet, nickname=u.nickname,
            ))

    distributed = sum(d.amount for d in distributions)
    platform_fee = round(escrow_total - distributed, 6)
    if platform_fee > 0:
        distributions.append(SettlementDistribution(
            label="Platform fee", amount=platform_fee, type="platform",
        ))

    return SettlementOut(
        escrow_total=escrow_total,
        sources=sources,
        distributions=distributions,
        resolve_tx_hash=task.payout_tx_hash,
        summary=SettlementSummary(
            winner_payout=0, winner_nickname=None, winner_tier=None, payout_rate=0,
            deposits_forfeited=round(deposits_forfeited, 6),
            deposits_refunded=round(deposits_refunded, 6),
            arbiter_reward_total=arbiter_reward,
            platform_fee=max(platform_fee, 0),
        ),
    )
