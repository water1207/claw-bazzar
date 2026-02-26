# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python/FastAPI)

```bash
pip install -e ".[dev]"                          # Install deps
uvicorn app.main:app --reload --port 8000        # Dev server
pytest -v                                        # All tests (252)
pytest tests/test_tasks.py::test_create_task -v  # Single test
pytest -k "test_submission" -v                   # Pattern match
pytest tests/test_challenge_api.py -v            # Challenge API tests
```

### Frontend (Next.js + Vitest)

```bash
cd frontend
npm install                                # Install deps
npm run dev                                # Dev server (port 3000)
npm test                                   # All tests (22)
npx vitest lib/x402.test.ts               # Single file
npx vitest -t "formatDeadline"            # Pattern match
npm run lint                               # ESLint
```

Both servers must run simultaneously. Frontend proxies `/api/*` → `http://localhost:8000/*` via Next.js rewrites (no CORS).

## Architecture

**Agent task marketplace**: Publishers post bounty tasks, Workers submit results, Oracle scores them, winners get paid USDC on-chain. Trust tier system governs permissions and payout rates.

### Backend layers

```
routers/          → HTTP handlers (tasks, submissions, users, trust, challenges, internal)
services/         → Business logic (oracle, x402 payment, payout, escrow, trust, arbiter_pool, staking)
models.py         → SQLAlchemy ORM (Task, User, Submission, ScoringDimension, Challenge, ArbiterVote, TrustEvent, StakeRecord)
schemas.py        → Pydantic request/response validation
scheduler.py      → APScheduler (quality_first deadline settlement + jury arbitration, every 1 min)
database.py       → SQLite + SQLAlchemy session
oracle/oracle.py  → Oracle mode router (V3 LLM modules)
oracle/llm_client.py → LLM API wrapper (Anthropic / OpenAI-compatible)
oracle/dimension_gen.py → Scoring dimension generation (3 fixed + 1-3 dynamic)
oracle/gate_check.py    → Acceptance criteria gate check
oracle/score_individual.py → Band-first per-dimension individual scoring
oracle/dimension_score.py  → Parallelized horizontal comparison scoring
```

### Two settlement paths

- **fastest_first**: Oracle `score_individual` → `penalized_total` ≥ 60 threshold → close task → `pay_winner()`
- **quality_first**: Submission → gate check → individual scoring (per-dimension) → deadline → horizontal comparison (top 3) → `createChallenge()` locks bounty → challenge window → jury arbitration → `resolveChallenge()` settles via contract

### Challenge escrow (ChallengeEscrow contract)

quality_first 赏金全程通过 ChallengeEscrow 智能合约结算：
1. `createChallenge()` — Phase 2 结束时，平台锁定 bounty×95% 到合约（含 10% 挑战激励）
2. `joinChallenge()` — 挑战期内，Relayer 用 try/catch Permit + transferFrom 收取押金 + 0.01 USDC 服务费
3. `resolveChallenge(verdicts, arbiters)` — 仲裁完成后分配：
   - 赏金：upheld → 90% 给挑战者；否则 → 80% 给原 winner + 10% 退回平台
   - 押金：30% 给仲裁者（仅多数方，平分），upheld → 70% 退回挑战者，rejected/malicious → 70% 归平台
4. No challengers → `resolveChallenge([], [])` 空裁决释放赏金

Contract: `contracts/src/ChallengeEscrow.sol` (Foundry, Solidity 0.8.20, OpenZeppelin Ownable)
Address: `0x0b256635519Db6B13AE9c423d18a3c3A6e888b99` (Base Sepolia)

### quality_first lifecycle phases

1. **open**: Accepts submissions; oracle runs gate check + individual scoring per-dimension. Gate pass → status `gate_passed` with structured revision suggestions; gate fail → status `gate_failed`. Scores hidden from API.
2. **scoring**: Deadline passed; scheduler calls `batch_score_submissions()` which selects top 3 gate_passed submissions by `penalized_total`, then runs horizontal comparison per-dimension (parallelized). Scores still hidden.
3. **challenge_window**: All scored; winner selected, `challenge_window_end` set. Scores now visible.
4. **arbitrating**: Jury selected (3 arbiters), 6-hour voting timeout. Coherence-based trust scoring after all challenges resolved.
5. **closed**: Challenge resolution or direct close.

### Submission status flow

- `pending` → `gate_passed` (gate check passed, individual scores stored) or `gate_failed` (gate check failed)
- `gate_passed` → `scored` (after horizontal comparison in batch_score)
- `pending` → `scored` (fastest_first path, via score_individual + penalized_total)

### Oracle V3 scoring (`oracle/oracle.py`)

Oracle V3 uses LLM-based scoring via Anthropic Claude or OpenAI-compatible API. Unified scoring pipeline for both settlement paths.

**Modes:**
- `mode = "dimension_gen"` → Generates 3 fixed + 1-3 dynamic scoring dimensions for a task
- `mode = "gate_check"` → Pass/fail verification against acceptance criteria
- `mode = "score_individual"` → Band-first (A-E) per-dimension scoring with evidence + 2 structured revision suggestions
- `mode = "dimension_score"` → Horizontal comparison of top submissions on a single dimension (parallelized with ThreadPoolExecutor)

**Three fixed dimensions** (always generated):
1. **Substantiveness** (实质性) — content depth and value
2. **Credibility** (可信度) — authenticity and reliability (absorbs former constraint_check)
3. **Completeness** (完整性) — coverage of acceptance criteria

**Non-linear penalized total** (`app/services/oracle.py`):
- Base = weighted sum of all dimension scores
- Any fixed dimension scoring < 60 applies multiplicative penalty: `penalty = ∏(score/60)` for each fixed dim below threshold
- Final = `weighted_base × penalty`
- fastest_first threshold: `penalized_total ≥ 60`

Entry point `invoke_oracle()` in `app/services/oracle.py` auto-selects mode. Service functions (`generate_dimensions`, `give_feedback`, `batch_score_submissions`) orchestrate the full pipeline.

### Trust tier system

Four-tier system (S/A/B/C) based on `trust_score` (default 500, tier A):

| Tier | Permissions | Challenge deposit rate | Platform fee |
|------|-------------|----------------------|-------------|
| S | All | 5% | 15% |
| A | All | 10% | 20% |
| B | All | 30% | 25% |
| C | Banned | — | — |

Trust events: `worker_won`, `worker_consolation`, `challenger_*`, `arbiter_coherence`, `publisher_completed`, `stake_bonus`, `stake_slash`, `weekly_leaderboard`, etc.

**Arbiter coherence**: Trust delta deferred to task-level after all challenges resolved. Coherence rate (majority/total votes) determines delta: >80% → +3, 60-80% → +2, 40-60% → 0, <40% → -10, 0% with ≥2 votes → -30.

Key services: `app/services/trust.py`, `app/services/arbiter_pool.py`, `app/services/staking.py`

### Jury-based arbitration

1. `select_jury()` — Selects 3 random arbiters (excluding task participants)
2. Arbiters submit votes (upheld/rejected/malicious) within 6-hour window
3. `resolve_jury()` — Detects 2:1, 3:0, or 1:1:1 deadlock (defaults to rejected)
4. Only majority arbiters' wallets passed to `resolveChallenge()` for on-chain reward
5. Non-voters penalized with `arbiter_timeout` trust event

### x402 payment flow

Frontend signs EIP-712 `TransferWithAuthorization` (viem) → base64 payload in `X-PAYMENT` header → backend decodes and verifies via `x402.org/facilitator`. Bounty=0 skips payment entirely.

Key details: network must be CAIP-2 format (`eip155:84532`), facilitator only supports Base Sepolia, httpx needs `follow_redirects=True` (308 redirect).

### Frontend data flow

`SWR hooks` (30s polling) → `fetch('/api/tasks')` → Next.js rewrite → FastAPI `:8000`. State managed via URL params (`/tasks?id=xxx`).

Key frontend components:
- `BalanceTrustHistoryPanel.tsx` — Consolidated balance events + trust events history per user
- `ArbiterPanel.tsx` — Arbiter votes with coherence status display
- `ChallengePanel.tsx` — Challenge details + voting interface

## Testing patterns

Backend tests use in-memory SQLite (`conftest.py`). Payment verification is mocked at the router level:

```python
PAYMENT_MOCK = patch("app.routers.tasks.verify_payment",
                     return_value={"valid": True, "tx_hash": "0xtest"})
PAYMENT_HEADERS = {"X-PAYMENT": "test"}

def test_create_task(client):
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={...}, headers=PAYMENT_HEADERS)
```

Oracle subprocess calls are mocked in service/scheduler tests:

```python
mock_result = type("R", (), {"stdout": json.dumps({"score": 0.9, "feedback": "ok"}), "returncode": 0})()
with patch("app.services.oracle.subprocess.run", return_value=mock_result):
    ...
```

Blockchain calls (web3.py payout) are always mocked — no real chain interaction in tests.

## Key environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PLATFORM_WALLET` | `0x0000...` | Receives x402 payments |
| `PLATFORM_PRIVATE_KEY` | (none) | Signs USDC payout transactions |
| `FACILITATOR_URL` | `https://x402.org/facilitator` | x402 verification endpoint |
| `X402_NETWORK` | `eip155:84532` | CAIP-2 chain identifier |
| `NEXT_PUBLIC_DEV_WALLET_KEY` | (in `.env.local`) | DevPanel signing key |
| `ESCROW_CONTRACT_ADDRESS` | (none) | Deployed ChallengeEscrow contract |
| `NEXT_PUBLIC_ESCROW_CONTRACT_ADDRESS` | (in `.env.local`) | Frontend escrow address |
| `ORACLE_LLM_PROVIDER` | `openai` | LLM provider (`anthropic` or `openai`) |
| `ORACLE_LLM_MODEL` | (none) | LLM model name |
| `ORACLE_LLM_BASE_URL` | (none) | OpenAI-compatible API base URL |
| `ANTHROPIC_API_KEY` | (none) | Anthropic API key |
| `OPENAI_API_KEY` | (none) | OpenAI / compatible provider API key |

## Database migrations (Alembic)

**IMPORTANT: Whenever `app/models.py` is modified, a migration script MUST be generated before committing.**

```bash
alembic revision --autogenerate -m "describe what changed"  # Generate migration script
alembic upgrade head                                         # Apply to local DB
```

The migration script under `alembic/versions/` must be committed together with the `models.py` change. Colleagues get the schema update automatically when they restart the server (Alembic runs `upgrade head` on every startup via `lifespan`).

Never use `Base.metadata.create_all()` to apply schema changes — Alembic owns the schema.

## Conventions

- Documentation is in Chinese (`docs/project-overview.md` is the authoritative spec)
- `bounty` field is required `float` (use 0 for free tasks, not null)
- Payout rate is trust-tier-based: S=85%, A=80%, B=75% (inverse of platform fee)
- Oracle V3 uses unified LLM-based scoring pipeline; V1 stub fallback removed
- Three fixed scoring dimensions (substantiveness, credibility, completeness) + 1-3 dynamic per task
- `ScoringDimension` table stores LLM-generated scoring dimensions per task, locked at creation time
- Task `acceptance_criteria` field drives gate checks and dimension generation
- Double-payout protection exists at both endpoint and service level
- All API datetime fields are serialized as UTC ISO 8601 with `Z` suffix (via `UTCDatetime` type in `schemas.py`) — no frontend timezone handling needed
- Scores for `quality_first` tasks are hidden (`null`) in API responses while task status is `open` or `scoring`
- Arbiter votes hidden from other arbiters until all votes submitted
- Trust tier recalculated after each trust event; C-tier users are banned
