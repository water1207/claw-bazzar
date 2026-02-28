# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python/FastAPI)

```bash
pip install -e ".[dev]"                          # Install deps
uvicorn app.main:app --port 8000                 # Dev server (不要加 --reload，见下方说明)
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

quality_first 赏金全程通过 ChallengeEscrow 智能合约结算（统一池分配模型）：
1. `createChallenge()` — Phase 2 结束时，平台锁定 bounty×95% 到合约（含 5% 挑战激励 incentive）
2. `joinChallenge()` — 挑战期内，Relayer 用 try/catch Permit + transferFrom 收取押金 + 0.01 USDC 服务费
3. `resolveChallenge(taskId, finalWinner, winnerPayout, refunds[], arbiters[], arbiterReward)` — 统一池分配：
   - 押金处理：upheld 挑战者全额退回，其余没收进统一池
   - 赢家赏金：后端按信誉等级计算 winnerPayout（PW 维持 → bounty×rate，挑战者胜出 → bounty×rate + incentive 余额）
   - 仲裁者奖励：统一池 30% + incentive 补贴（挑战者胜出时，从 incentive 支付胜出者押金的 30%）
   - 平台收取剩余（服务费 + 没收池 70% + 平台费差额）
4. `voidChallenge()` — PW 恶意时：退还 publisher、分配恶意者没收押金
5. No challengers → `resolveChallenge(task, winner, payout, [], [], 0)` 空裁决释放赏金

Contract: `contracts/src/ChallengeEscrow.sol` (Foundry, Solidity 0.8.20, OpenZeppelin Ownable)
Address: `0x5BC8c88093Ab4E92390d972EE13261a29A02adE8` (Base Sepolia)

### quality_first lifecycle phases

1. **open**: Accepts submissions; oracle runs gate check + individual scoring per-dimension. Gate pass → status `gate_passed` with structured revision suggestions; gate fail → status `gate_failed`. Scores hidden from API.
2. **scoring**: Deadline passed; scheduler calls `batch_score_submissions()` which selects top 3 gate_passed submissions by `penalized_total`, then runs horizontal comparison per-dimension (parallelized). Scores still hidden.
3. **challenge_window**: All scored; winner selected, `challenge_window_end` set. Scores now visible.
4. **arbitrating**: Jury selected (3 arbiters), 6-hour voting timeout. Hawkish trust matrix scoring after all challenges resolved.
5. **closed**: Challenge resolution or direct close.
6. **voided**: PW malicious detected (≥2 arbiter tags) → publisher refunded, task voided.

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

Trust events: `worker_won`, `worker_consolation`, `challenger_*`, `arbiter_majority`, `arbiter_minority`, `arbiter_tp_malicious`, `arbiter_fp_malicious`, `arbiter_fn_malicious`, `publisher_completed`, `stake_bonus`, `stake_slash`, `weekly_leaderboard`, etc.

**Hawkish trust matrix** (两维谢林点共识，merged jury path):
- 主维度（选赢家）：`arbiter_majority` +2, `arbiter_minority` -15, deadlock 0（不发事件）
- 副维度（抓恶意）：基于 MaliciousTag 共识（≥2 票）
  - TP 精准排雷 `arbiter_tp_malicious` +5/target
  - FP 防卫过当 `arbiter_fp_malicious` -1/target
  - FN 严重漏判 `arbiter_fn_malicious` -10/target

**Legacy arbiter coherence** (per-challenge ArbiterVote path): `arbiter_coherence` delta via `compute_coherence_delta()`. >80% → +3, 60-80% → +2, 40-60% → 0, <40% → -10, 0% with ≥2 → -30.

Key services: `app/services/trust.py`, `app/services/arbiter_pool.py`, `app/services/staking.py`

### Jury-based arbitration

**Merged jury path** (JuryBallot + MaliciousTag):
1. `select_jury()` — Selects 3 random arbiters per task (excluding participants)
2. Arbiters submit merged votes: single-select winner + multi-select malicious tags
3. `resolve_merged_jury()` — Determines winner, verdicts, PW malicious detection (≥2 tags → VOID)
4. `_settle_after_arbitration()` — Unified pool financial settlement + hawkish trust matrix
5. Non-voters penalized with `arbiter_timeout` trust event

**Legacy per-challenge path** (ArbiterVote):
1. `resolve_jury()` per challenge — Detects 2:1, 3:0, or 1:1:1 deadlock (defaults to rejected)
2. Coherence-based trust scoring via `compute_coherence_delta()`

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

### 故障排查

**问题一：`--reload` 导致启动挂起**

`uvicorn --reload` 在 lifespan 启动期间触发热重载，Alembic 写 SQLite 时产生死锁，服务器无法完成启动。**始终不加 `--reload` 启动后端。**

**问题二：DB 版本与本地迁移文件不匹配**

拉取远端代码后，本地 DB 的 `alembic_version` 可能指向一个本地不存在的 revision，导致报错：
```
alembic.util.exc.CommandError: Can't locate revision identified by 'xxxxxxxx'
```

修复步骤：
```bash
# 1. 查看本地实际 head
alembic heads

# 2. 把 DB 版本强制指向本地 head（替换为实际 revision id）
sqlite3 claw_bazzar.db "UPDATE alembic_version SET version_num = '<local_head>';"

# 3. 验证
alembic current
```

> ⚠️ 仅在本地 schema 已与 head 一致时使用（如 DB 是本地新建的）。若 schema 真有差异，应先跑 `alembic upgrade head` 或删 DB 重建。

**问题三：多头（multiple heads）冲突**

两个分支各自生成迁移导致分叉：
```bash
alembic merge heads -m "merge_heads"
alembic upgrade head
# 将 merge 文件与其他改动一起 commit
```

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
