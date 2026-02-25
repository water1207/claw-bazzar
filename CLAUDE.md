# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python/FastAPI)

```bash
pip install -e ".[dev]"                          # Install deps
uvicorn app.main:app --reload --port 8000        # Dev server
pytest -v                                        # All tests (101)
pytest tests/test_tasks.py::test_create_task -v  # Single test
pytest -k "test_submission" -v                   # Pattern match
pytest tests/test_challenge_api.py -v            # Challenge API tests
```

### Frontend (Next.js + Vitest)

```bash
cd frontend
npm install                                # Install deps
npm run dev                                # Dev server (port 3000)
npm test                                   # All tests (20)
npx vitest lib/x402.test.ts               # Single file
npx vitest -t "formatDeadline"            # Pattern match
npm run lint                               # ESLint
```

Both servers must run simultaneously. Frontend proxies `/api/*` → `http://localhost:8000/*` via Next.js rewrites (no CORS).

## Architecture

**Agent task marketplace**: Publishers post bounty tasks, Workers submit results, Oracle scores them, winners get paid USDC on-chain.

### Backend layers

```
routers/          → HTTP handlers (tasks, submissions, users, internal)
services/         → Business logic (oracle, x402 payment, payout, escrow)
models.py         → SQLAlchemy ORM (Task, User, Submission)
schemas.py        → Pydantic request/response validation
scheduler.py      → APScheduler (quality_first deadline settlement, every 1 min)
database.py       → SQLite + SQLAlchemy session
oracle/oracle.py  → Oracle stub (subprocess, stdin/stdout JSON)
```

### Two settlement paths

- **fastest_first**: Oracle scores submission → score ≥ threshold → close task → `pay_winner()`
- **quality_first**: Submission → oracle feedback → deadline → batch score → `createChallenge()` locks 90% bounty → challenge window → arbitration → `resolveChallenge()` settles via contract

### Challenge escrow (ChallengeEscrow contract)

quality_first 赏金全程通过 ChallengeEscrow 智能合约结算：
1. `createChallenge()` — Phase 2 结束时，平台锁定 bounty×90% 到合约（含 10% 挑战激励）
2. `joinChallenge()` — 挑战期内，Relayer 用 try/catch Permit + transferFrom 收取押金 + 0.01 USDC 服务费
3. `resolveChallenge(verdicts, arbiters)` — 仲裁完成后分配：
   - 赏金：upheld → 90% 给挑战者；否则 → 80% 给原 winner + 10% 退回平台
   - 押金：30% 给仲裁者（平分），upheld → 70% 退回挑战者，rejected/malicious → 70% 归平台
4. No challengers → `resolveChallenge([], [])` 空裁决释放赏金

Contract: `contracts/src/ChallengeEscrow.sol` (Foundry, Solidity 0.8.20, OpenZeppelin Ownable)
Address: `0x0b256635519Db6B13AE9c423d18a3c3A6e888b99` (Base Sepolia)

### quality_first lifecycle phases

1. **open**: Accepts submissions; oracle runs in `feedback` mode, stores suggestions in `oracle_feedback`, status stays `pending`. Scores hidden from API.
2. **scoring**: Deadline passed; scheduler calls `batch_score_submissions()` to score all pending submissions. Scores still hidden.
3. **challenge_window**: All scored; winner selected, `challenge_window_end` set. Scores now visible.
4. **arbitrating / closed**: Challenge resolution or direct close.

### Oracle modes (`oracle/oracle.py`)

- `mode = "feedback"` → `{"suggestions": ["...", "...", "..."]}` (3 random revision suggestions)
- `mode = "score"` → `{"score": <random 0.5–1.0>, "feedback": "..."}` (existing scoring behavior)

Entry point `invoke_oracle()` in `app/services/oracle.py` auto-selects mode based on task type.

### x402 payment flow

Frontend signs EIP-712 `TransferWithAuthorization` (viem) → base64 payload in `X-PAYMENT` header → backend decodes and verifies via `x402.org/facilitator`. Bounty=0 skips payment entirely.

Key details: network must be CAIP-2 format (`eip155:84532`), facilitator only supports Base Sepolia, httpx needs `follow_redirects=True` (308 redirect).

### Frontend data flow

`SWR hooks` (30s polling) → `fetch('/api/tasks')` → Next.js rewrite → FastAPI `:8000`. State managed via URL params (`/tasks?id=xxx`).

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
- Payout = bounty × 0.80 (20% platform fee)
- Oracle V1 is a stub (`oracle/oracle.py`) — feedback mode returns 3 random suggestions, score mode returns random 0.5–1.0
- Double-payout protection exists at both endpoint and service level
- All API datetime fields are serialized as UTC ISO 8601 with `Z` suffix (via `UTCDatetime` type in `schemas.py`) — no frontend timezone handling needed
- Scores for `quality_first` tasks are hidden (`null`) in API responses while task status is `open` or `scoring`
