# Settlement Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Task 结算后在 TaskDetail 新增 Settlement tab，用 Sankey 流向图 + 明细表展示完整资金分配。

**Architecture:** 后端新增 `GET /tasks/{id}/settlement` API，在 `services/settlement.py` 中根据 task/challenges/ballots/trust 计算分配明细。前端新增 `SettlementPanel.tsx`（Tab 容器 + 明细表）和 `SettlementSankey.tsx`（纯 SVG Sankey 图）。

**Tech Stack:** Python/FastAPI (backend), React/Next.js + SVG (frontend), SWR (data fetching)

---

### Task 1: Backend — Schema + Settlement Service

**Files:**
- Modify: `app/schemas.py` (append new schemas)
- Create: `app/services/settlement.py`

**Step 1: Add Pydantic schemas to `app/schemas.py`**

Append at end of file (before the final `TaskDetail.model_rebuild()`):

```python
class SettlementSource(BaseModel):
    label: str
    amount: float
    type: str           # "bounty" | "incentive" | "deposit"
    verdict: Optional[str] = None  # "upheld" | "rejected" | "malicious"

class SettlementDistribution(BaseModel):
    label: str
    amount: float
    type: str           # "winner" | "refund" | "arbiter" | "platform" | "publisher_refund"
    wallet: Optional[str] = None
    nickname: Optional[str] = None

class SettlementSummary(BaseModel):
    winner_payout: float
    winner_nickname: Optional[str] = None
    winner_tier: Optional[str] = None
    payout_rate: float
    deposits_forfeited: float
    deposits_refunded: float
    arbiter_reward_total: float
    platform_fee: float

class SettlementOut(BaseModel):
    escrow_total: float
    sources: list[SettlementSource]
    distributions: list[SettlementDistribution]
    resolve_tx_hash: Optional[str] = None
    summary: SettlementSummary
```

**Step 2: Create `app/services/settlement.py`**

Implements `compute_settlement(db, task_id) -> SettlementOut | None`.

Three code paths:
1. **quality_first closed** (with or without challenges): Reconstructs escrow pool (bounty×95% + incentive 5% + deposits), distributions (winner payout, deposit refunds, arbiter rewards, platform fee = remainder).
2. **quality_first voided**: Publisher refund (95%), arbiter reward (5%), deposit handling.
3. **fastest_first closed**: Simple direct payout (bounty × tier rate → winner, remainder → platform).

Key logic (mirrors `_resolve_via_contract` and `_settle_after_arbitration` in `scheduler.py`):
- `winner_payout = task.payout_amount` (already stored in DB after settlement)
- `deposits_refunded = sum(c.deposit_amount for c in challenges if c.verdict == 'upheld')`
- `deposits_forfeited = sum(c.deposit_amount for c in challenges if c.verdict != 'upheld')`
- `arbiter_reward = losing_deposits * 0.30 + (upheld_deposit * 0.30 if challenger_win)`
- `platform_fee = escrow_total - winner_payout - deposits_refunded - arbiter_reward`
- For arbiter wallets: query `JuryBallot` → `User` to get nicknames and wallets

```python
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
```

**Step 3: Run existing tests to verify no breakage**

Run: `pytest tests/ -x -q`
Expected: All existing tests pass (no imports broken)

**Step 4: Commit**

```
feat: 新增 settlement 结算明细计算服务和 schema
```

---

### Task 2: Backend — Settlement API Endpoint + Tests

**Files:**
- Modify: `app/routers/tasks.py` (add endpoint)
- Create: `tests/test_settlement.py`

**Step 1: Add endpoint to `app/routers/tasks.py`**

Add import at top:
```python
from ..services.settlement import compute_settlement
from ..schemas import SettlementOut
```

Add route after `get_task`:
```python
@router.get("/{task_id}/settlement", response_model=SettlementOut)
def get_settlement(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    result = compute_settlement(db, task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Settlement not available")
    return result
```

**Step 2: Write tests in `tests/test_settlement.py`**

Test cases:
1. `test_settlement_404_not_found` — Nonexistent task returns 404
2. `test_settlement_404_still_open` — Open task returns 404
3. `test_settlement_fastest_first_closed` — fastest_first with payout_amount returns correct breakdown
4. `test_settlement_quality_first_with_challenges` — quality_first closed with challenges: verifies sources (bounty+incentive+deposits), distributions (winner+refund+arbiter+platform), summary totals

Use `client_with_db` fixture to directly insert DB records (Task, Submission, Challenge, User, JuryBallot) for test scenarios. Mock no oracle or blockchain calls needed — this is pure computation from DB state.

```python
from unittest.mock import patch
from datetime import datetime, timezone
from app.models import (
    Task, TaskType, TaskStatus, Submission, SubmissionStatus,
    Challenge, ChallengeVerdict, ChallengeStatus,
    User, UserRole, TrustTier, PayoutStatus, JuryBallot,
)

PAYMENT_MOCK = patch("app.routers.tasks.verify_payment",
                     return_value={"valid": True, "tx_hash": "0xtest"})


def _seed_quality_first_settled(db):
    """Seed a fully settled quality_first task with challenges."""
    publisher = User(id="pub1", nickname="Alice", wallet="0xPUB", role=UserRole.publisher)
    worker_a = User(id="w1", nickname="Bob", wallet="0xBOB", role=UserRole.worker, trust_tier=TrustTier.A)
    worker_b = User(id="w2", nickname="Charlie", wallet="0xCHA", role=UserRole.worker, trust_tier=TrustTier.A)
    arbiter1 = User(id="a1", nickname="arb-alpha", wallet="0xARB1", role=UserRole.worker, trust_tier=TrustTier.S, is_arbiter=True)
    arbiter2 = User(id="a2", nickname="arb-beta", wallet="0xARB2", role=UserRole.worker, trust_tier=TrustTier.S, is_arbiter=True)
    db.add_all([publisher, worker_a, worker_b, arbiter1, arbiter2])

    task = Task(
        id="t1", title="Test", description="test", type=TaskType.quality_first,
        status=TaskStatus.closed, bounty=10.0, publisher_id="pub1",
        winner_submission_id="s2", payout_amount=9.2, payout_status=PayoutStatus.paid,
        payout_tx_hash="0xRESOLVE", escrow_tx_hash="0xESCROW",
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
        acceptance_criteria='["test"]',
    )
    sub_a = Submission(id="s1", task_id="t1", worker_id="w1", content="a", status=SubmissionStatus.scored, score=0.9)
    sub_b = Submission(id="s2", task_id="t1", worker_id="w2", content="b", status=SubmissionStatus.scored, score=0.95)
    db.add_all([task, sub_a, sub_b])

    # Charlie challenged and won (upheld), Bob's rejected
    ch1 = Challenge(
        id="c1", task_id="t1",
        challenger_submission_id="s2", target_submission_id="s1",
        reason="better", verdict=ChallengeVerdict.upheld, status=ChallengeStatus.judged,
        challenger_wallet="0xCHA", deposit_amount=1.0,
    )
    ch2 = Challenge(
        id="c2", task_id="t1",
        challenger_submission_id="s1", target_submission_id="s2",
        reason="disagree", verdict=ChallengeVerdict.rejected, status=ChallengeStatus.judged,
        challenger_wallet="0xBOB", deposit_amount=1.0,
    )
    db.add_all([ch1, ch2])

    # Jury ballots
    b1 = JuryBallot(id="jb1", task_id="t1", arbiter_user_id="a1", winner_submission_id="s2", coherence_status="coherent")
    b2 = JuryBallot(id="jb2", task_id="t1", arbiter_user_id="a2", winner_submission_id="s2", coherence_status="coherent")
    db.add_all([b1, b2])
    db.commit()


def test_settlement_404_not_found(client):
    resp = client.get("/tasks/nonexistent/settlement")
    assert resp.status_code == 404


def test_settlement_404_still_open(client_with_db):
    c, db = client_with_db
    with PAYMENT_MOCK:
        resp = c.post("/tasks", json={
            "title": "T", "description": "d", "type": "fastest_first",
            "threshold": 0.6, "bounty": 1.0, "publisher_id": "p",
            "deadline": "2099-01-01T00:00:00Z", "acceptance_criteria": ["x"],
        }, headers={"X-PAYMENT": "test"})
    task_id = resp.json()["id"]
    resp = c.get(f"/tasks/{task_id}/settlement")
    assert resp.status_code == 404


def test_settlement_quality_first_with_challenges(client_with_db):
    c, db = client_with_db
    _seed_quality_first_settled(db)

    resp = c.get("/tasks/t1/settlement")
    assert resp.status_code == 200
    data = resp.json()

    # Sources: bounty(9.5) + incentive(0.5) + 2 deposits(1.0 each)
    assert data["escrow_total"] == 12.0
    assert len(data["sources"]) == 4

    # Winner payout is stored as 9.2
    assert data["summary"]["winner_payout"] == 9.2
    assert data["summary"]["winner_nickname"] == "Charlie"

    # Upheld deposit refunded
    assert data["summary"]["deposits_refunded"] == 1.0
    assert data["summary"]["deposits_forfeited"] == 1.0

    # Arbiter reward: losing_deposits(1.0)*0.30 + upheld_deposit(1.0)*0.30 = 0.6
    assert data["summary"]["arbiter_reward_total"] == 0.6

    # Platform fee = 12.0 - 9.2 - 1.0 - 0.6 = 1.2
    assert data["summary"]["platform_fee"] == 1.2

    # resolve_tx_hash
    assert data["resolve_tx_hash"] == "0xRESOLVE"
```

**Step 3: Run tests**

Run: `pytest tests/test_settlement.py -v`
Expected: All pass

**Step 4: Commit**

```
feat: 新增 GET /tasks/{id}/settlement 结算明细 API + 测试
```

---

### Task 3: Frontend — Types + SWR Hook

**Files:**
- Modify: `frontend/lib/api.ts`

**Step 1: Add TypeScript types and SWR hook**

Add after existing interfaces:

```typescript
/* ── Settlement ── */

export interface SettlementSource {
  label: string
  amount: number
  type: 'bounty' | 'incentive' | 'deposit'
  verdict: ChallengeVerdict | null
}

export interface SettlementDistribution {
  label: string
  amount: number
  type: 'winner' | 'refund' | 'arbiter' | 'platform' | 'publisher_refund'
  wallet: string | null
  nickname: string | null
}

export interface SettlementSummary {
  winner_payout: number
  winner_nickname: string | null
  winner_tier: TrustTier | null
  payout_rate: number
  deposits_forfeited: number
  deposits_refunded: number
  arbiter_reward_total: number
  platform_fee: number
}

export interface Settlement {
  escrow_total: number
  sources: SettlementSource[]
  distributions: SettlementDistribution[]
  resolve_tx_hash: string | null
  summary: SettlementSummary
}
```

Add hook:

```typescript
export function useSettlement(taskId: string | null) {
  return useSWR<Settlement>(
    taskId ? `/api/tasks/${taskId}/settlement` : null,
    fetcher,
    { refreshInterval: 30_000 },
  )
}
```

**Step 2: Commit**

```
feat(ui): 新增 Settlement 类型定义和 SWR hook
```

---

### Task 4: Frontend — Sankey SVG Component

**Files:**
- Create: `frontend/components/SettlementSankey.tsx`

**Step 1: Create Sankey component**

Pure SVG component. Layout:
- Canvas: 100% width, fixed 280px height
- Left column (x=0–140): source nodes stacked vertically, height ∝ amount
- Center column (x=280–320): single pool node, full height
- Right column (x=460–600): distribution nodes stacked vertically
- Bezier curves connecting left→center and center→right, stroke-width ∝ amount
- Hover state: highlight flow path + show tooltip

Color map:
- bounty: `#34d399` (emerald-400)
- incentive: `#60a5fa` (blue-400)
- deposit(upheld): `#34d399`, deposit(rejected): `#f87171` (red-400), deposit(malicious): `#facc15` (yellow-400)
- winner: `#34d399`, refund: `#60a5fa`, arbiter: `#a78bfa` (purple-400), platform: `#a1a1aa` (zinc-400), publisher_refund: `#60a5fa`

Props: `{ sources: SettlementSource[], distributions: SettlementDistribution[], escrowTotal: number }`

Use `useState` for hover. Bezier control points: `M startX,startY C cpX1,startY cpX2,endY endX,endY`.

**Step 2: Commit**

```
feat(ui): 新增 SettlementSankey 纯 SVG 流向图组件
```

---

### Task 5: Frontend — Settlement Panel + Tab Integration

**Files:**
- Create: `frontend/components/SettlementPanel.tsx`
- Modify: `frontend/components/TaskDetail.tsx`

**Step 1: Create SettlementPanel**

Composes `SettlementSankey` + detail table + summary cards.

```
<SettlementPanel task={task}>
  ├── Summary row: 4 stat cards (Winner Payout, Arbiter Reward, Platform Fee, Deposits)
  ├── <SettlementSankey ... />
  └── Distribution table (# | Recipient | Amount | Type | Tx)
</SettlementPanel>
```

Uses `useSettlement(task.id)` hook. Shows loading state if data not ready.

Table reuses existing patterns: `text-xs`, `font-mono`, badge colors for type column, `TxLink` for tx hash (import from TaskDetail or extract to shared).

**Step 2: Add Settlement tab to TaskDetail**

In `TaskDetail.tsx`:

1. Update Tab type: `type Tab = 'overview' | 'submissions' | 'challenges' | 'settlement'`
2. Add visibility check: `const showSettlementTab = task.status === 'closed' || task.status === 'voided'`
3. Add TabButton in tab bar (after challenges):
```tsx
{showSettlementTab && (
  <TabButton active={tab === 'settlement'} onClick={() => setTab('settlement')}>
    Settlement
  </TabButton>
)}
```
4. Add tab content:
```tsx
{tab === 'settlement' && showSettlementTab && (
  <SettlementPanel task={task} />
)}
```
5. Import `SettlementPanel`.

**Step 3: Extract `TxLink` to shared**

Move `TxLink` from `TaskDetail.tsx` into its own reusable pattern or keep inline in both files — pragmatically just duplicate the 10-line component in `SettlementPanel.tsx` since it's tiny.

**Step 4: Test manually**

Run: `npm run dev` (frontend) + `uvicorn app.main:app --port 8000` (backend)
Navigate to a closed task → verify Settlement tab appears with Sankey chart and detail table.

**Step 5: Run frontend tests**

Run: `cd frontend && npm test`
Expected: All existing tests pass

**Step 6: Commit**

```
feat(ui): 新增 Settlement Tab — Sankey 流向图 + 资金分配明细表
```

---

### Task 6: Final Verification

**Step 1: Run all backend tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 2: Run all frontend tests**

Run: `cd frontend && npm test`
Expected: All pass

**Step 3: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No errors

**Step 4: Final commit if any fixes needed**
