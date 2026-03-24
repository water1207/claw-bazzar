# Solana E2E Full Flow Runthrough Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 Solana x402 改写后的系统可以正常运行，跑通 quality_first 和 fastest_first 任务从发布到结算的全流程，使用 `.env.local` 里的测试钱包，赋予不同信誉分层级和 arbiter 权限。

**Architecture:** 分 4 大阶段：(1) 环境补全 — 补齐缺失的 env 变量、添加 internal API 让测试能直接设置 arbiter 标志、初始化合约；(2) 用户初始化 — 注册所有测试钱包用户、设置信誉分/tier、注册 arbiter；(3) fastest_first 全流程 — 发布→提交→Oracle 评分→阈值关闭→链上支付；(4) quality_first 全流程 — 发布→提交→门检→截止→水平比较→挑战窗口→挑战→仲裁→结算。

**Tech Stack:** Python/FastAPI backend, Next.js frontend, Solana devnet (Anchor programs), x402 payment protocol, SPL Token (USDC)

---

## Task 1: 补全后端 .env 缺失变量

**Files:**
- Modify: `.env`

**Step 1: 添加缺失的 Solana/x402 环境变量**

```env
# 在 .env 末尾追加（这些有代码默认值但应显式配置）
SOLANA_RPC_URL=https://api.devnet.solana.com
USDC_MINT=4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU
FACILITATOR_URL=https://x402.org/facilitator
X402_NETWORK=solana-devnet
```

**Step 2: 验证后端能启动**

Run: `uvicorn app.main:app --port 8000`
Expected: 启动成功，无报错

**Step 3: Commit**

```bash
git add .env
git commit -m "补全 .env Solana/x402 环境变量"
```

---

## Task 2: 添加 internal API — 直接设置 is_arbiter 和 github_id

**问题：** 正常流程中 arbiter 注册需要 S-tier + GitHub 绑定 + 100 USDC 质押。测试环境需要绕过这些前置条件。

**Files:**
- Modify: `app/routers/internal.py:89-101`

**Step 1: 写测试**

在 `tests/test_internal_api.py`（如已有则追加）：

```python
def test_set_user_flags(client):
    """internal API should allow setting is_arbiter and github_id directly."""
    # Create user first
    resp = client.post("/users", json={
        "nickname": "flag-test",
        "wallet": "FLAGtestWallet111111111111111111111111111111",
        "role": "worker",
    })
    user_id = resp.json()["id"]

    # Set is_arbiter and github_id
    resp = client.patch(f"/internal/users/{user_id}/trust", json={
        "score": 850,
        "is_arbiter": True,
        "github_id": "12345",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["trust_score"] == 850
    assert data["is_arbiter"] is True
    assert data["github_id"] == "12345"
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_internal_api.py::test_set_user_flags -v`
Expected: FAIL — 当前 set_trust_score 不处理 is_arbiter / github_id

**Step 3: 修改 internal.py 的 set_trust_score**

`app/routers/internal.py` 第 89-101 行：

```python
@router.patch("/users/{user_id}/trust")
def set_trust_score(user_id: str, data: dict, db: Session = Depends(get_db)):
    """Dev-only: directly set a user's trust score, tier, arbiter flag, and github_id."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    from ..services.trust import _compute_tier
    score = float(data.get("score", user.trust_score))
    user.trust_score = max(0.0, min(1000.0, score))
    user.trust_tier = _compute_tier(user.trust_score)
    if "is_arbiter" in data:
        user.is_arbiter = bool(data["is_arbiter"])
    if "github_id" in data:
        user.github_id = str(data["github_id"])
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "trust_score": user.trust_score,
        "trust_tier": user.trust_tier.value,
        "is_arbiter": user.is_arbiter,
        "github_id": user.github_id,
    }
```

**Step 4: 运行测试确认通过**

Run: `pytest tests/test_internal_api.py::test_set_user_flags -v`
Expected: PASS

**Step 5: 运行全部后端测试确保无回归**

Run: `pytest -v`
Expected: 全部通过

**Step 6: Commit**

```bash
git add app/routers/internal.py tests/test_internal_api.py
git commit -m "feat: internal API 支持直接设置 is_arbiter 和 github_id"
```

---

## Task 3: 初始化链上合约 (ChallengeEscrow + StakingVault)

**前置：** 合约已部署到 devnet，但还没调用 `initialize`。

**Files:**
- Use: `scripts/initialize-programs.ts`

**Step 1: 在 WSL 中运行初始化脚本**

用户需在 WSL 终端执行：
```bash
cd /mnt/c/Users/Hank/PycharmProjects/claw-bazzar
npx ts-node scripts/initialize-programs.ts
```

Expected: 两个程序都输出 "initialized!" 或 "already initialized"

**Step 2: 验证**

通过 Solana Explorer 或 CLI 确认 config PDA 账户存在。

---

## Task 4: 写测试用户初始化脚本

**目标：** 注册所有 dev-wallets 用户 → 设置不同信誉分/tier → 设置 arbiter 标志

**Files:**
- Create: `scripts/init_test_users.py`

**Step 1: 创建脚本**

```python
"""
Initialize test users via API calls.
Registers all dev wallets, sets trust tiers, and marks arbiters.

Usage: python scripts/init_test_users.py [--base-url http://localhost:8000]
"""
import base64
import sys
import httpx
from pathlib import Path

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

# Parse wallet keys from frontend/.env.local
env_local = Path(__file__).parent.parent / "frontend" / ".env.local"
wallets = {}
for line in env_local.read_text().splitlines():
    if "_WALLET_KEY=" in line and line.startswith("NEXT_PUBLIC_DEV_"):
        name, val = line.split("=", 1)
        role_key = name.replace("NEXT_PUBLIC_DEV_", "").replace("_WALLET_KEY", "")
        key_bytes = base64.b64decode(val)
        # Extract pubkey from 64-byte keypair (last 32 bytes)
        from solders.keypair import Keypair
        kp = Keypair.from_bytes(key_bytes)
        wallets[role_key] = str(kp.pubkey())

# User definitions: (env_key, nickname, role, trust_score, is_arbiter)
USERS = [
    ("PUBLISHER",  "dev-publisher",  "publisher", 850,  False),
    ("WORKER",     "Alice",          "worker",    850,  False),   # S-tier
    ("WORKER2",    "Bob",            "worker",    550,  False),   # A-tier
    ("WORKER3",    "Charlie",        "worker",    350,  False),   # B-tier
    ("WORKER4",    "Diana",          "worker",    400,  False),   # B-tier
    ("WORKER5",    "Ethan",          "worker",    200,  False),   # C-tier (banned)
    ("ARBITER1",   "arbiter-alpha",  "worker",    850,  True),    # S-tier arbiter
    ("ARBITER2",   "arbiter-beta",   "worker",    850,  True),    # S-tier arbiter
    ("ARBITER3",   "arbiter-gamma",  "worker",    850,  True),    # S-tier arbiter
]

client = httpx.Client(base_url=BASE_URL, timeout=10)

for env_key, nickname, role, trust_score, is_arbiter in USERS:
    wallet = wallets.get(env_key)
    if not wallet:
        print(f"  SKIP {nickname}: no wallet key found for {env_key}")
        continue

    # 1. Register user
    resp = client.post("/users", json={
        "nickname": nickname,
        "wallet": wallet,
        "role": role,
    })
    if resp.status_code in (200, 201):
        user_id = resp.json()["id"]
        print(f"  Registered {nickname} ({wallet[:12]}...): {user_id}")
    else:
        print(f"  WARN {nickname}: register returned {resp.status_code} — {resp.text}")
        # Try to get existing user
        resp2 = client.get("/users", params={"nickname": nickname})
        if resp2.status_code == 200:
            user_id = resp2.json()["id"]
            print(f"  Found existing {nickname}: {user_id}")
        else:
            print(f"  FAIL {nickname}: cannot find or create user")
            continue

    # 2. Set trust score + arbiter flag
    patch_data = {"score": trust_score}
    if is_arbiter:
        patch_data["is_arbiter"] = True
        patch_data["github_id"] = f"gh-{nickname}"
    resp = client.patch(f"/internal/users/{user_id}/trust", json=patch_data)
    if resp.status_code == 200:
        data = resp.json()
        print(f"    → trust={data['trust_score']}, tier={data['trust_tier']}, arbiter={data.get('is_arbiter', False)}")
    else:
        print(f"    → WARN: set trust returned {resp.status_code} — {resp.text}")

print("\nDone! User summary:")
print(f"{'Nickname':<20} {'Wallet':<48} {'Trust':>6} {'Tier':>5} {'Arbiter':>8}")
print("-" * 90)
for env_key, nickname, role, trust_score, is_arbiter in USERS:
    wallet = wallets.get(env_key, "???")
    from app.services.trust import _compute_tier
    from app.models import TrustTier
    tier = "S" if trust_score >= 800 else "A" if trust_score >= 500 else "B" if trust_score >= 300 else "C"
    print(f"{nickname:<20} {wallet:<48} {trust_score:>6} {tier:>5} {'Yes' if is_arbiter else 'No':>8}")
```

**Step 2: 启动后端并运行脚本**

Run: `python scripts/init_test_users.py`
Expected: 所有 9 个用户注册成功，信誉分/tier 设置正确，3 个 arbiter 标记完成

**Step 3: Commit**

```bash
git add scripts/init_test_users.py
git commit -m "添加测试用户初始化脚本（注册 + 信誉分 + arbiter）"
```

---

## Task 5: 修复前端启动问题

**问题：** `npm run dev` 报错 — port 3000 被占用 + lock 文件冲突

**Files:**
- Modify: `frontend/` (清理 .next 缓存)

**Step 1: 清理旧进程和锁文件**

```bash
# 找到并终止占用 3000 端口的进程
netstat -ano | findstr :3000
taskkill /PID <pid> /F

# 清理 Next.js lock
rm -rf frontend/.next
```

**Step 2: 重新启动前端**

```bash
cd frontend && npm run dev
```

Expected: `✓ Ready on http://localhost:3000`

---

## Task 6: Fastest-First 全流程测试

**目标：** Publisher 发任务 → Worker 提交 → Oracle 评分 → 阈值达标 → 自动关闭 → 链上支付

**Files:**
- Use: DevPanel (前端) 或 API 直接调用

**Step 1: Publisher 发布 fastest_first 任务**

通过 DevPanel 或 API：
```bash
# 用 dev-publisher 钱包签 x402 支付
# POST /tasks with:
{
  "title": "E2E Test: Fastest First",
  "description": "Test task for fastest_first flow",
  "type": "fastest_first",
  "bounty": 1.0,
  "acceptance_criteria": "Submit any text response about Solana",
  "deadline": "<now + 1 hour>",
  "publisher_id": "<dev-publisher user_id>"
}
# X-PAYMENT header: signed x402 payment
```

Expected: 201 Created, task status = "open"

**Step 2: Worker (Alice) 提交**

```bash
# POST /tasks/{task_id}/submissions
{
  "worker_id": "<Alice user_id>",
  "content": "Solana is a high-performance blockchain that uses Proof of History..."
}
```

Expected: 201 Created, submission status = "pending"

**Step 3: 等待 Oracle 评分**

Oracle 后台异步评分。检查 submission 状态变为 `scored`，`penalized_total >= 60`。

```bash
# GET /tasks/{task_id}
```

Expected: task status = "closed", winner_submission_id = Alice's submission, payout_status = "paid"

**Step 4: 验证链上支付**

```bash
# GET /users/{alice_id}/balance-events
```

Expected: 出现 payout 记录，金额 = bounty × payout_rate (S-tier: 85%)

**Step 5: 验证信誉事件**

```bash
# GET /users/{alice_id}/trust/events
```

Expected: `worker_won` 事件，信誉分上升

---

## Task 7: Quality-First 全流程测试 — Phase 1: 发布 + 提交

**目标：** Publisher 发任务 → 多 Worker 提交 → Oracle 门检 + 个人评分

**Step 1: Publisher 发布 quality_first 任务**

```bash
# POST /tasks
{
  "title": "E2E Test: Quality First",
  "description": "Write a comprehensive analysis of Solana's consensus mechanism",
  "type": "quality_first",
  "bounty": 5.0,
  "acceptance_criteria": "Must cover: PoH, Tower BFT, Turbine, Gulf Stream. Min 500 words.",
  "deadline": "<now + 5 minutes>",
  "publisher_id": "<dev-publisher user_id>"
}
```

Expected: 201, status = "open", scoring_dimensions generated in background

**Step 2: 多个 Worker 提交**

- Alice (S-tier): 提交高质量内容
- Bob (A-tier): 提交中等质量
- Charlie (B-tier): 提交低质量

```bash
# POST /tasks/{task_id}/submissions (for each worker)
```

Expected: 各 submission 经 Oracle 门检后状态变为 `gate_passed` 或 `gate_failed`

**Step 3: 验证分数在 API 中隐藏**

```bash
# GET /tasks/{task_id}
```

Expected: task status = "open" 时，submission.score = null（quality_first 隐藏机制）

---

## Task 8: Quality-First 全流程测试 — Phase 2: 截止 + 水平比较

**目标：** 截止日期到达 → scheduler 触发 batch_score → 选出 winner → 创建链上 escrow

**Step 1: 等待 deadline**

Scheduler 每分钟检查。deadline 到达后自动触发。

**Step 2: 验证状态转换**

```bash
# GET /tasks/{task_id}
```

Expected:
- status 变为 `challenge_window`
- winner_submission_id 已设置
- submissions 的 score 现在可见
- escrow_tx_hash 非空（链上锁定了赏金 × 95%）

---

## Task 9: Quality-First 全流程测试 — Phase 3: 挑战

**目标：** 非赢家 Worker 发起挑战 → 签名押金 → 链上 joinChallenge

**Step 1: Bob 发起挑战**

通过 DevPanel 或 API：
```bash
# POST /tasks/{task_id}/challenges
{
  "challenger_submission_id": "<Bob's submission_id>",
  "reason": "I believe my submission better covers Tower BFT consensus details",
  "challenger_wallet": "<Bob's wallet>",
  "signed_transaction": "<Bob 签名的 joinChallenge Solana tx, base64>"
}
```

前端 DevPanel 会调用 `signJoinChallenge()` 构造签名交易。

Expected: 201, challenge created, deposit_tx_hash 非空

**Step 2: 验证挑战押金**

```bash
# GET /tasks/{task_id}/challenges
```

Expected: challenge 列表包含 Bob 的挑战，status = "open", deposit_amount = bounty × 10% (A-tier)

---

## Task 10: Quality-First 全流程测试 — Phase 4: 仲裁

**目标：** 挑战窗口结束 → scheduler 选陪审团 → 3 个 Arbiter 投票 → 解决

**Step 1: 等待挑战窗口结束**

Scheduler 每分钟检查 `challenge_window_end`。

Expected: task status 变为 `arbitrating`，3 个 JuryBallot 被创建

**Step 2: 3 个 Arbiter 投票**

```bash
# POST /tasks/{task_id}/jury-vote (for each arbiter)
{
  "arbiter_user_id": "<arbiter-alpha user_id>",
  "winner_submission_id": "<Alice's submission_id>",
  "malicious_submission_ids": [],
  "feedback": "Alice's submission is more comprehensive"
}
```

对 3 个 arbiter 重复：alpha 选 Alice，beta 选 Alice，gamma 选 Bob（2:1 majority）

Expected: 各投票返回成功

**Step 3: Scheduler 解决仲裁**

所有 3 票提交后，scheduler 下一轮 tick 触发 `resolve_merged_jury()`。

Expected:
- task status = "closed"
- winner = Alice（majority 2:1）
- Bob 的 challenge verdict = "rejected"（挑战者没赢）
- Bob 押金被没收进统一池
- Alice 收到赏金（链上 resolveChallenge）
- 3 个 arbiter 收到仲裁奖励
- 信誉事件：alpha/beta 获得 `arbiter_majority` +2，gamma 获得 `arbiter_minority` -15

**Step 4: 验证链上结算**

```bash
# GET /tasks/{task_id}/settlement
# GET /users/{alice_id}/balance-events
# GET /users/{arbiter-alpha_id}/trust/events
```

---

## Task 11: 边界场景 — 挑战者胜出

**目标：** 测试挑战者胜出（PW 被推翻）的流程

**Step 1: 发布新 quality_first 任务**

同 Task 7 但设计让初始 winner 不那么好。

**Step 2: 提交 + 等待 deadline + 挑战**

按正常流程走到 arbitrating。

**Step 3: Arbiter 投票选挑战者**

3 个 arbiter 投票都选挑战者的 submission 为 winner。

Expected:
- challenge verdict = "upheld"
- 挑战者获得赏金 + incentive 余额
- 原 winner 无赏金
- 挑战者押金全额退还

---

## Task 12: 边界场景 — 恶意检测 + VOID

**目标：** 测试 ≥2 个 arbiter 标记 PW 为恶意 → task VOID

**Step 1: 发布任务 + 走到 arbitrating**

**Step 2: Arbiter 投票时标记恶意**

```bash
# 2 个 arbiter 的 malicious_submission_ids 包含原 winner
```

Expected:
- task status = "voided"
- publisher 获得退款
- 所有挑战者押金退还
- 恶意提交者信誉大幅下降

---

## 执行优先级

**必须完成（系统能跑起来）：** Task 1-5
**核心流程验证：** Task 6-10
**高级场景（可选）：** Task 11-12

## 关键阻塞点

1. **链上合约未初始化** → Task 3 必须先完成，否则 escrow 交互全部失败
2. **Arbiter 注册依赖 S-tier + GitHub** → Task 2 的 internal API 绕过是前提
3. **Oracle 需要 LLM API** → `.env` 中的 `OPENAI_API_KEY` + `ORACLE_LLM_BASE_URL` 必须可用
4. **x402 facilitator** → 需要能连通 `https://x402.org/facilitator`
5. **Devnet RPC** → 后端需能连通 `https://api.devnet.solana.com`
