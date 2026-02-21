# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python/FastAPI)

```bash
pip install -e ".[dev]"                          # Install deps
uvicorn app.main:app --reload --port 8000        # Dev server
pytest -v                                        # All tests (53)
pytest tests/test_tasks.py::test_create_task -v  # Single test
pytest -k "test_submission" -v                   # Pattern match
```

### Frontend (Next.js + Vitest)

```bash
cd frontend
npm install                                # Install deps
npm run dev                                # Dev server (port 3000)
npm test                                   # All tests (18)
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
services/         → Business logic (oracle, x402 payment, payout)
models.py         → SQLAlchemy ORM (Task, User, Submission)
schemas.py        → Pydantic request/response validation
scheduler.py      → APScheduler (quality_first deadline settlement, every 1 min)
database.py       → SQLite + SQLAlchemy session
```

### Two settlement paths

- **fastest_first**: Oracle scores submission → score ≥ threshold → close task → `pay_winner()`
- **quality_first**: Deadline expires → scheduler picks highest score → `pay_winner()`

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

Blockchain calls (web3.py payout) are always mocked — no real chain interaction in tests.

## Key environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PLATFORM_WALLET` | `0x0000...` | Receives x402 payments |
| `PLATFORM_PRIVATE_KEY` | (none) | Signs USDC payout transactions |
| `FACILITATOR_URL` | `https://x402.org/facilitator` | x402 verification endpoint |
| `X402_NETWORK` | `eip155:84532` | CAIP-2 chain identifier |
| `NEXT_PUBLIC_DEV_WALLET_KEY` | (in `.env.local`) | DevPanel signing key |

## Conventions

- Documentation is in Chinese (`docs/project-overview.md` is the authoritative spec)
- `bounty` field is required `float` (use 0 for free tasks, not null)
- Payout = bounty × 0.80 (20% platform fee)
- Oracle V1 is a stub (`oracle/oracle.py`) that always returns score 0.9
- Double-payout protection exists at both endpoint and service level
