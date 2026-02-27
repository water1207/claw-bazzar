# 合并裁决（Merged Arbitration）设计文档

> 日期: 2026-02-27
> 状态: 已批准

## 概述

将现有的 per-challenge 独立投票模式升级为**合并裁决**模式：3 名 Arbiter 从候选池 `[暂定获胜者(PW), 挑战者A, 挑战者B, ...]` 中「单选赢家 + 多选恶意标记」，两个维度解耦计算共识。

**核心判定逻辑**: `if (某挑战者得票 >= 2) { 该挑战者赢 } else { PW 维持原判 }`

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 触发条件 | 统一替换（不分单/多挑战者） | 一套逻辑，无分支 |
| 恶意标记范围 | 全池均可（含 PW） | 兜底 Oracle 误判 |
| PW 被判恶意 | 触发全局熔断（Task Voided） | 不给骗子发钱 |
| 赢家 vs 恶意互斥 | 前端 + 后端双防护 | 防逻辑悖论 + 防攻击 |
| 技术方案 | 新建 JuryBallot + MaliciousTag 表 | 语义清晰，最小破坏 |

---

## Section 1: 数据模型

### 新增表

#### JuryBallot — Arbiter 对整个 Task 的合并投票

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| task_id | UUID FK(tasks) | 关联任务 |
| arbiter_user_id | UUID FK(users) | 仲裁者 |
| winner_submission_id | UUID FK(submissions), nullable | 选出的赢家（null=未投票） |
| feedback | Text, nullable | 文字反馈 |
| coherence_status | String, nullable | "coherent" / "incoherent" / "neutral" |
| is_majority | Boolean, nullable | 是否多数派 |
| created_at | DateTime | 记录创建时间 |
| voted_at | DateTime, nullable | 投票时间戳 |

唯一约束: `(task_id, arbiter_user_id)`

#### MaliciousTag — Arbiter 的恶意标记

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| task_id | UUID FK(tasks) | 关联任务 |
| arbiter_user_id | UUID FK(users) | 仲裁者 |
| target_submission_id | UUID FK(submissions) | 被标记的提交 |
| created_at | DateTime | 标记时间 |

唯一约束: `(task_id, arbiter_user_id, target_submission_id)`

### 新增枚举值

`TaskStatus` 新增 `voided` — PW 恶意熔断后的终态。

### ArbiterVote 表处理

保留不删。已有 ArbiterVote 记录作为历史数据。新仲裁流程使用 JuryBallot + MaliciousTag。

### 候选池定义

```
候选池 = {task.winner_submission_id} ∪ {c.challenger_submission_id for c in task.challenges}
```

---

## Section 2: 投票 API 与校验

### 新 API Endpoint

**`POST /tasks/{task_id}/jury-vote`**

```json
{
  "arbiter_user_id": "uuid",
  "winner_submission_id": "uuid",
  "malicious_submission_ids": ["uuid"],
  "feedback": "string"
}
```

### 后端校验链

1. **身份校验**: arbiter_user_id 必须在该 task 的 JuryBallot 中有预创建记录（未投票）
2. **候选池校验**: winner_submission_id ∈ 候选池
3. **恶意池校验**: 每个 malicious_submission_id ∈ 候选池
4. **互斥校验**: winner_submission_id ∉ malicious_submission_ids → 否则 400
5. **幂等性**: 已投票不可重复提交

### 前端 UI 交互

```
┌──────────────────────────────────────────┐
│  合并裁决面板 — Task #xxx                  │
├──────────────────────────────────────────┤
│  选出最终赢家（单选 Radio）:                │
│  ○ 暂定获胜者 (PW) — worker_alice          │
│  ○ 挑战者 A — worker_bob                  │
│  ○ 挑战者 B — worker_carol                │
│                                          │
│  标记恶意行为（多选 Checkbox，可不选）:      │
│  ☐ 暂定获胜者 (PW) [被选为赢家时置灰]      │
│  ☐ 挑战者 A                               │
│  ☐ 挑战者 B                               │
│                                          │
│  反馈意见: [textarea]                      │
│              [提交投票]                    │
└──────────────────────────────────────────┘
```

**互斥联动**: 选中某人为赢家 → 该人的 Malicious Checkbox 立即 disabled + 自动取消勾选。

**投票隐藏**: 全部 3 人投完前只显示 `"X/3 已投票"`，防串通。

---

## Section 3: 结算逻辑 (resolve_merged_jury)

当 3 名 Arbiter 全部投票或 6 小时超时，执行以下判定树：

### Step 1: 熔断检测（最高优先级）

```python
pw_malicious_count = count(MaliciousTag where target == pw_submission_id)
if pw_malicious_count >= 2:
    → TASK_VOIDED（跳转熔断分支）
```

### Step 2: 计算赢家

```python
vote_counts = Counter(ballot.winner_submission_id for ballot in ballots)
winner = first(sub_id for sub_id, cnt in vote_counts.items() if cnt >= 2)

if winner is None:
    winner = pw_submission_id  # 1:1:1 僵局 → 维持原判
    is_deadlock = True
```

### Step 3: 确定每个挑战者的 verdict

```python
for challenge in task.challenges:
    sub = challenge.challenger_submission_id
    malicious_count = count(MaliciousTag where target == sub)

    if sub == winner:
        verdict = ChallengeVerdict.upheld
    elif malicious_count >= 2:
        verdict = ChallengeVerdict.malicious
    else:
        verdict = ChallengeVerdict.rejected
```

### Step 4: Arbiter 连贯性（两维度独立计算）

**赢家维度**（非僵局时）:
- 投给最终赢家 → coherent（多数派）
- 未投给赢家 → incoherent（少数派）
- 僵局 → 全部 neutral

**恶意维度**（始终参与）:
- 对被标记 ≥2 次的人：标记了 → coherent，没标记 → incoherent
- 对被标记 <2 次的人：标记了 → incoherent（误判），没标记 → coherent
- 综合两维度计算连贯率 → `compute_coherence_delta()`

### Step 5: 生成合约 verdicts 数组

```python
verdicts = []
for challenge in challenges:
    if challenge.challenger_wallet:
        verdicts.append({
            "challenger": challenge.challenger_wallet,
            "result": {upheld: 0, rejected: 1, malicious: 2}[verdict],
            "arbiters": majority_arbiter_wallets
        })

resolve_challenge_onchain(task_id, final_winner_wallet, payout, verdicts)
```

### 选票分布全景

| 分布 | 示例 | 结果 |
|------|------|------|
| 3:0 绝对共识 | A(3票) | A 胜出 |
| 2:1 多数派 | A(2票), PW(1票) | A 胜出，投PW的Arbiter为少数派 |
| 1:1:1 僵局 | PW(1), A(1), B(1) | PW 维持原判 |
| 1:1:1 纯挑战者 | A(1), B(1), C(1) | PW 维持原判（无人达标） |

---

## Section 4: 信任事件与资金分配

### 信任事件表

| 事件 | 触发条件 | Delta |
|------|----------|-------|
| `challenger_won` | 挑战者获 ≥2 票胜出 | +10 × M(bounty) |
| `challenger_rejected` | 挑战者落选，非恶意 | -3 |
| `challenger_malicious` | 被 ≥2 人标恶意 | -100, slash |
| `challenger_justified` | **新增**: 熔断场景下非恶意挑战者 | +5 |
| `pw_malicious` | **新增**: PW 被 ≥2 人标恶意 | -100, slash |
| `worker_won` | PW 维持原判 | +5 × M(bounty) |
| `arbiter_coherence` | 仲裁结算后 | 按连贯率公式 |
| `arbiter_timeout` | 6小时未投票 | -10 |

### 资金分配矩阵

#### 正常路径 — 挑战者胜出 (upheld)

| 资金 | 流向 |
|------|------|
| 赏金 | → 胜出挑战者（按信任等级 payout rate） |
| 胜出挑战者押金 | 100% 退还 |
| 落选挑战者押金 | 30% → Arbiter（仅多数派），70% → 平台 |

#### 正常路径 — PW 维持原判 / 僵局

| 资金 | 流向 |
|------|------|
| 赏金 | → PW（按信任等级 payout rate） |
| 所有挑战者押金 | 30% → Arbiter（僵局时全员平分），70% → 平台 |

#### 熔断路径 — Task Voided (PW malicious)

| 资金 | 流向 |
|------|------|
| 赏金 95% | → 退回 Publisher |
| 赏金 5% | → 分给 3 名 Arbiter（仲裁费） |
| 非恶意挑战者押金 | 100% 退还 |
| 恶意挑战者押金 | 30% → Arbiter，70% → 平台（同正常路径） |
| PW | 不发钱，-100 信誉，slash |

---

## Section 5: 智能合约改动

### 正常路径 — 无合约改动

现有 `resolveChallenge(taskId, finalWinner, winnerPayout, verdicts[])` 完全兼容合并裁决的结果映射。

### 熔断路径 — 新增 `voidChallenge()` 方法

```solidity
struct ChallengerRefund {
    address challenger;
    bool refund;  // true=退还, false=没收(恶意)
}

function voidChallenge(
    bytes32 taskId,
    address publisher,
    uint256 publisherRefund,         // 95% of bounty
    ChallengerRefund[] calldata refunds,
    address[] calldata arbiters,
    uint256 arbiterReward            // 5% of bounty, split equally
) external onlyOwner
```

逻辑:
1. 按 refund 标志退还/没收每个挑战者押金
2. 没收的押金: 30% → arbiters, 70% → platform
3. 退还 publisherRefund 给 publisher
4. 分 arbiterReward 给 arbiters

### 合约新增存储

```solidity
mapping(bytes32 => address[]) public challengerList;  // joinChallenge 时 push
```

---

## Section 6: 变更清单

| 层 | 文件 | 变更 | 说明 |
|---|------|------|------|
| 模型 | `app/models.py` | 新增 | JuryBallot, MaliciousTag; TaskStatus.voided |
| Schema | `app/schemas.py` | 新增 | JuryVoteIn, JuryVoteOut, MaliciousTagOut |
| 迁移 | `alembic/versions/` | 新增 | 2 张新表 + voided 枚举 |
| 路由 | `app/routers/challenges.py` | 新增 | POST /tasks/{task_id}/jury-vote |
| 服务 | `app/services/arbiter_pool.py` | 重写 | select_jury → JuryBallot; resolve_merged_jury |
| 调度 | `app/scheduler.py` | 修改 | 新结算逻辑 + 熔断分支 |
| 信任 | `app/services/trust.py` | 新增 | pw_malicious, challenger_justified 事件 |
| 合约 | `contracts/src/ChallengeEscrow.sol` | 新增 | voidChallenge() + challengerList |
| 前端 | `ArbiterPanel.tsx` | 重写 | Radio + Checkbox 合并裁决 UI |
| 前端 | `ChallengePanel.tsx` | 修改 | voided 状态显示 |
| 测试 | `tests/` | 新增 | 3:0, 2:1, 1:1:1, 熔断, 恶意标记场景 |

### 不变的部分

- createChallenge(), joinChallenge(), resolveChallenge() — 无改动
- Oracle 评分流程 — 不受影响
- x402 支付流程 — 不受影响
- Challenge 创建流程 — 不受影响
- ArbiterVote 表 — 保留为历史数据
