# Settlement Dashboard Design

## Goal

Task 结算后，在 TaskDetail 新增 "Settlement" tab，用 Sankey 流向图 + 明细表展示完整资金分配情况。

## Architecture

### Backend: `GET /tasks/{task_id}/settlement`

新增 API 端点，仅 `closed`/`voided` 状态返回数据。后端根据 task + challenges + jury_ballots + trust tier 计算完整结算明细。

**Response schema (`SettlementOut`)**:

```python
class SettlementSource(BaseModel):
    label: str              # "Bounty (95%)", "Charlie deposit", ...
    amount: float
    type: str               # "bounty" | "incentive" | "deposit"
    verdict: str | None     # "upheld" | "rejected" | "malicious" (deposits only)

class SettlementDistribution(BaseModel):
    label: str              # "Winner (Charlie)", "Arbiter (alpha)", "Platform fee"
    amount: float
    type: str               # "winner" | "refund" | "arbiter" | "platform" | "publisher_refund"
    wallet: str | None
    nickname: str | None

class SettlementSummary(BaseModel):
    winner_payout: float
    winner_nickname: str | None
    winner_tier: str | None
    payout_rate: float
    deposits_forfeited: float
    deposits_refunded: float
    arbiter_reward_total: float
    platform_fee: float

class SettlementOut(BaseModel):
    escrow_total: float
    sources: list[SettlementSource]
    distributions: list[SettlementDistribution]
    resolve_tx_hash: str | None
    summary: SettlementSummary
```

**Calculation logic** (in new `services/settlement.py`):
1. Read task, challenges, jury_ballots from DB
2. Compute sources: bounty split (95% + 5% incentive) + per-challenger deposits
3. Compute distributions: winner payout (tier-based rate + incentive remainder), deposit refunds (upheld), arbiter rewards (30% losing pool + incentive subsidy), platform fee (remainder)
4. Handle edge cases: no challengers, voided tasks (publisher refund), fastest_first (direct payout)

### Frontend: Settlement Tab + Sankey

**New files:**
- `components/SettlementPanel.tsx` — Tab content component
- `components/SettlementSankey.tsx` — Pure SVG Sankey chart

**SWR hook:** `useSettlement(taskId)` → `GET /api/tasks/{id}/settlement`, 30s poll

**Tab visibility:** Only show "Settlement" tab when `task.status === 'closed' || task.status === 'voided'`

### Sankey Chart (Pure SVG)

```
  Sources (left)         Pool (center)        Distributions (right)

  Bounty 0.95 ━━━━━┓                   ┏━━━ Winner    0.92
                    ┣━━ Escrow 1.55 ━━━╋━━━ Refund    0.10
  Incentive 0.05 ━━┫                   ┣━━━ Arbiter   0.18
                    ┃                   ┗━━━ Platform  0.35
  Deposits 0.60 ━━━┛
```

- Left nodes: bounty (emerald), incentive (blue), deposits (colored by verdict)
- Center: Escrow pool with total amount
- Right nodes: winner (emerald), refund (blue), arbiter (purple), platform (zinc)
- Flow width proportional to amount
- Hover highlights flow + shows tooltip with amount
- SVG bezier curves for flows, no third-party library

### Detail Table

Below Sankey, a table listing each distribution:

| # | Recipient | Amount | Type | Tx |
|---|-----------|--------|------|----|
| 1 | Charlie (0x5cED...) | 0.10 USDC | Deposit refund | link |
| 2 | Charlie (0x5cED...) | 0.92 USDC | Winner payout | link |
| ... | | | | |

Color-coded badges matching Sankey node colors. Tx links to Base Sepolia explorer.

## Scope

- **In scope**: quality_first closed/voided, fastest_first closed (simple payout view)
- **Out of scope**: real-time settlement tracking, historical comparison
