# Claw Trust 信誉分机制 — 设计文档

**日期**: 2026-02-25
**状态**: 已审批
**范围**: 后端 + 智能合约（前端 UI 留待后续单独设计）

---

## 1. 概述

Claw Trust 是 Claw Bazzar 生态的核心信任引擎。采用 **链下服务器计算与存储** 架构，信誉分直接决定用户的资金摩擦成本（挑战押金）、平台手续费率以及核心治理权限（Arbiter 资格）。

- **分值范围**: 0–1000，初始 500
- **等级**: S (800–1000) / A (500–799) / B (300–499) / C (<300)
- **架构**: 分层服务（TrustService + ArbiterPoolService + StakingService）

---

## 2. 数据模型变更

### 2.1 修改 User 模型

| 字段 | 类型 | 说明 |
|------|------|------|
| `credit_score` → `trust_score` | Float, default=500 | 改名 + 默认值从 100 改为 500 |
| `trust_tier` | Enum(S/A/B/C) | 缓存当前等级，每次分数变动同步 |
| `github_id` | String, nullable | GitHub 绑定标识（OAuth） |
| `github_bonus_claimed` | Boolean, default=False | 防止重复领取 +50 |
| `consolation_total` | Float, default=0 | 累计陪跑安慰分（封顶 50） |
| `is_arbiter` | Boolean, default=False | Arbiter 资格标记 |
| `staked_amount` | Float, default=0 | 质押金额（DB 记账） |
| `stake_bonus` | Float, default=0 | 质押获得的临时加成分（封顶 100） |

### 2.2 新增 TrustEvent 模型（信誉分变更日志）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `user_id` | String | 关联用户 |
| `event_type` | Enum | 行为类型 |
| `task_id` | String, nullable | 关联任务 |
| `amount` | Float | 任务赏金（用于计算加权） |
| `delta` | Float | 分数变动 |
| `score_before` | Float | 变动前分数 |
| `score_after` | Float | 变动后分数 |
| `created_at` | DateTime (UTC) | 时间戳 |

`event_type` 枚举值：`worker_won`, `worker_consolation`, `worker_malicious`, `challenger_won`, `challenger_rejected`, `challenger_malicious`, `arbiter_majority`, `arbiter_minority`, `arbiter_timeout`, `github_bind`, `weekly_leaderboard`, `stake_bonus`, `stake_slash`

### 2.3 新增 ArbiterVote 模型（陪审团投票记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `challenge_id` | String | 关联挑战 |
| `arbiter_user_id` | String | 仲裁者用户 ID |
| `vote` | Enum (upheld/rejected/malicious) | 投票结果 |
| `feedback` | Text, **required** | 评判理由（必填） |
| `is_majority` | Boolean, nullable | 投票后计算 |
| `reward_amount` | Float, nullable | 分润金额 |
| `created_at` | DateTime (UTC) | 时间戳 |

### 2.4 新增 StakeRecord 模型（质押记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `user_id` | String | 关联用户 |
| `amount` | Float | 质押金额 |
| `purpose` | Enum (arbiter_deposit/credit_recharge) | 质押目的 |
| `tx_hash` | String, nullable | 链上交易哈希 |
| `slashed` | Boolean, default=False | 是否被罚没 |
| `created_at` | DateTime (UTC) | 时间戳 |

---

## 3. TrustService — 算分引擎

新增 `app/services/trust.py`。

### 3.1 对数加权系数

```python
def _multiplier(amount: float) -> float:
    """M = 1 + log10(1 + amount / 10)"""
    return 1 + math.log10(1 + amount / 10)
```

效果：$0→1.0, $10→1.3, $90→2.0, $990→3.0

### 3.2 行为分值矩阵

统一入口 `apply_event(db, user_id, event_type, task_bounty=0)`：

| event_type | delta | 加权？ | 约束 |
|------------|-------|--------|------|
| `worker_won` | +5 × M | 是 | — |
| `worker_consolation` | +1 | 否 | `consolation_total` 封顶 50 |
| `worker_malicious` | -100 | 否 | — |
| `challenger_won` | +10 × M | 是 | — |
| `challenger_rejected` | -3 | 否 | 仅同任务被驳回挑战者中后 30%；单人挑战被驳回必触发 |
| `challenger_malicious` | -100 | 否 | — |
| `arbiter_majority` | +2 | 否 | — |
| `arbiter_minority` | -15 | 否 | — |
| `arbiter_timeout` | -10 | 否 | — |
| `github_bind` | +50 | 否 | 仅一次 |
| `weekly_leaderboard` | +10/15/20/30 | 否 | 按排名段 |
| `stake_bonus` | +50 per $50 | 否 | 封顶 +100 |

分数始终 clamp 在 [0, 1000]。每次 apply_event 写入 TrustEvent 日志。

### 3.3 等级映射

```python
def _compute_tier(score: float) -> TrustTier:
    if score >= 800: return TrustTier.S
    if score >= 500: return TrustTier.A
    if score >= 300: return TrustTier.B
    return TrustTier.C
```

### 3.4 动态费率

| 等级 | 挑战押金比例 | 平台手续费率 | 限制 |
|------|-------------|-------------|------|
| S | 5% | 15% | Arbiter 资格 |
| A | 10% | 20% | 正常 |
| B | 30% | 25% | 单笔限额 50 USDC |
| C | 禁止挑战 | 禁止接单 | 黑名单 |

### 3.5 权限校验

`check_permissions(user, action)` 方法在 router 层调用：
- C 级禁止发起挑战、禁止接单
- B 级限制单笔接单/发单 50 USDC

---

## 4. ArbiterPoolService — 3 人陪审团

新增 `app/services/arbiter_pool.py`。

### 4.1 Arbiter 资格准入

同时满足：
- `trust_score >= 800`（S 级）
- `staked_amount >= 100`（已质押 $100 USDC）
- `github_id is not None`（已绑定 GitHub）

注册后 `user.is_arbiter = True`。

### 4.2 陪审团抽签

`arbitrating` 阶段触发：
1. 查询所有 `is_arbiter=True` 且不是该任务相关方的用户
2. 随机抽取 3 人（不足 3 人用所有可用；0 人 fallback 到平台 stub）
3. 创建 ArbiterVote 记录
4. 设置 `arbiter_deadline`（6 小时）

### 4.3 投票流程

- 每位 Arbiter 通过 API 提交：`verdict` + `feedback`（必填）
- 每人只能投一次
- 3 人全部投完或 6h 超时后进入判定

### 4.4 多数派判定

```python
def resolve_jury(votes: list[ArbiterVote]) -> ChallengeVerdict:
    # 2/3 一致为多数派
    # 3 票均不同 → rejected（保守策略）
    # 标记 is_majority
```

### 4.5 信誉结算

- 多数派：+2 分 + 分润押金 30%（平分）
- 少数派：-15 分，0 收益
- 超时未投：-10 分

---

## 5. StakingVault 智能合约

新增 `contracts/src/StakingVault.sol`，与 ChallengeEscrow 独立。

### 5.1 合约设计

```solidity
contract StakingVault is Ownable {
    IERC20 public usdc;

    struct Stake {
        uint256 amount;
        uint256 timestamp;
        bool slashed;
    }

    mapping(address => Stake) public stakes;

    function stake(address user, uint256 amount,
                   uint256 deadline, uint8 v, bytes32 r, bytes32 s) external onlyOwner;
    function unstake(address user, uint256 amount) external onlyOwner;
    function slash(address user) external onlyOwner;
    function emergencyWithdraw(address user) external onlyOwner;
}
```

使用 Permit + Relayer 代付 Gas（与 ChallengeEscrow 相同模式）。

### 5.2 后端交互层

新增 `app/services/staking.py`：
- `stake_for_arbiter(user_id, permit_sig)` — 校验 S 级 + GitHub，调用合约 stake(100)
- `stake_for_credit(user_id, amount, permit_sig)` — 校验封顶，调用合约，更新 stake_bonus
- `check_and_slash(user_id)` — 扣分后检查，跌破 300 → 自动 Slash
- `unstake(user_id)` — 解除质押

### 5.3 Slash 触发

TrustService.apply_event() 每次扣分后检查：
- 新分数 < 300 且 staked_amount > 0 → 调用 slash()
- Slash 后：staked_amount=0, stake_bonus=0, is_arbiter=False

---

## 6. API 端点

### 6.1 新增端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/users/{id}/trust` | 信誉档案（分数、等级、费率、权限） |
| `GET` | `/auth/github` | GitHub OAuth 跳转 |
| `GET` | `/auth/github/callback` | GitHub OAuth 回调，绑定 +50 分 |
| `POST` | `/users/{id}/stake` | 质押 USDC |
| `POST` | `/users/{id}/unstake` | 解除质押 |
| `POST` | `/users/{id}/register-arbiter` | 注册 Arbiter |
| `GET` | `/challenges/{cid}/votes` | 陪审团投票状态 |
| `POST` | `/challenges/{cid}/vote` | Arbiter 投票（verdict + feedback required） |
| `GET` | `/leaderboard/weekly` | 周榜 |
| `GET` | `/trust/quote` | 询价（动态押金/费率） |

### 6.2 修改现有端点

| 端点 | 变更 |
|------|------|
| `POST /tasks/{id}/challenges` | C 级禁止；押金改为动态计算 |
| `POST /tasks/{id}/submissions` | C 级禁止接单；B 级限额 50 USDC |
| `POST /tasks` | 手续费率动态化 |
| `GET /users/{id}` | 响应增加 trust_score, trust_tier, is_arbiter |

### 6.3 环境变量

| 变量 | 说明 |
|------|------|
| `GITHUB_CLIENT_ID` | GitHub OAuth App Client ID |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App Client Secret |
| `STAKING_CONTRACT_ADDRESS` | StakingVault 合约地址 |

---

## 7. Scheduler 变更

### 7.1 仲裁投票检查（每分钟）

扫描 `arbitrating` 状态任务：
- 检查 ArbiterVote 是否全部投完或超时 6h
- 满足条件 → resolve_jury() → 信誉结算 → resolveChallenge() → closed

### 7.2 周榜快照（每周日 24:00 UTC）

- 统计本周所有 closed 任务中已结算 Worker 的总金额
- 排名 Top 100，按段发放信誉分
- Top 1-3: +30, Top 4-10: +20, Top 11-30: +15, Top 31-100: +10

### 7.3 生命周期更新

```
challenge_window 到期
  ├─ 有挑战 → 抽签 3 人 → arbitrating（等待投票，最多 6h）
  │            └─ 投票完成 → resolve_jury → 信誉结算 → resolveChallenge → closed
  └─ 无挑战 → resolveChallenge(空裁决) → closed
```

---

## 8. 新增文件清单

| 文件 | 说明 |
|------|------|
| `app/services/trust.py` | TrustService 算分引擎 |
| `app/services/arbiter_pool.py` | ArbiterPoolService 陪审团管理 |
| `app/services/staking.py` | StakingService 质押交互 |
| `app/routers/trust.py` | Trust 相关 API（信誉查询、GitHub 绑定、质押、Arbiter） |
| `app/routers/auth.py` | GitHub OAuth 端点 |
| `contracts/src/StakingVault.sol` | 质押合约 |
| `contracts/test/StakingVault.t.sol` | 质押合约测试 |
| `tests/test_trust_service.py` | TrustService 单元测试 |
| `tests/test_arbiter_pool.py` | ArbiterPoolService 单元测试 |
| `tests/test_staking_service.py` | StakingService 单元测试 |
| `tests/test_trust_api.py` | Trust API 集成测试 |
| `tests/test_weekly_leaderboard.py` | 周榜测试 |
