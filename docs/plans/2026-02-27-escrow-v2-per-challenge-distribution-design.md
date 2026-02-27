# Escrow V2：逐挑战独立资金分配 + Upheld 全额退押 + 原 Winner 补偿

> 日期: 2026-02-27
> 状态: 待实现

## 背景

当前 ChallengeEscrow 合约的 `resolveChallenge` 存在三个问题：
1. **arbiter 奖励全局均分**：所有挑战的押金 30% 汇入同一个 arbiterPool，由所有传入 arbiter 均分。应改为每个挑战独立分配。
2. **upheld 时押金仅退 70%**：upheld challenger 的押金被扣 30% 给 arbiter。应改为 100% 全额退还，arbiter 奖励从 10% 挑战激励中支付。
3. **失败挑战无 winner 补偿**：rejected/malicious 押金 70% 全归平台。当无 upheld 时，应抽 10% 补偿原 winner。

## 核心规则

### 每个 task 最多 1 个 upheld

即使多个挑战被陪审团投票为 upheld，arbiters 会进行打分评比，只有最高分的保留 upheld，其余降级为 rejected。

### 场景 A：有 upheld（新 winner 出现）

| verdict | 押金分配 |
|---------|---------|
| **upheld** | 100% 退回 challenger；arbiter 奖励 = deposit×30%，从 incentive 支付给该挑战多数方 arbiter |
| **rejected / malicious** | 30% → 该挑战多数方 arbiter，70% → 平台 |

赏金分配：
- winnerPayout = min(task.bounty × trust_rate, mainBounty)，其中 mainBounty = 锁仓 - incentive = task.bounty × 85%
- incentive 余额（incentive - upheld_arbiter_reward）→ finalWinner
- 赏金余额 → 平台

### 场景 B：无 upheld（原 winner 保持）

| verdict | 押金分配 |
|---------|---------|
| **rejected / malicious** | 30% → 该挑战多数方 arbiter，10% → 原 winner，60% → 平台 |

赏金分配（与现有一致）：
- winnerPayout = task.bounty × trust_rate
- 赏金余额 → 平台

### 押金分配与信誉分的关系

rejected 和 malicious 的**押金分配完全相同**，区别仅在信誉分惩罚力度。

### 安全保证：incentive 始终覆盖 arbiter 奖励

最大 arbiter 奖励 = max_deposit × 30% = bounty × 30%（B级）× 30% = bounty × 9%
incentive = bounty × 10%
9% < 10%，始终够用。

## 合约改动 (`contracts/src/ChallengeEscrow.sol`)

### Verdict 结构体

```solidity
struct Verdict {
    address challenger;
    uint8   result;      // 0=upheld, 1=rejected, 2=malicious
    address[] arbiters;  // 该挑战的多数方 arbiter 地址（僵局时全部 3 人）
}
```

### 新增常量

```solidity
uint256 public constant WINNER_COMPENSATION_BPS = 1000; // 10% of deposit → original winner
```

### resolveChallenge 新签名

```solidity
function resolveChallenge(
    bytes32 taskId,
    address finalWinner,
    uint256 winnerPayout,
    Verdict[] calldata verdicts
) external onlyOwner
```

去掉 flat `address[] calldata arbiters` 参数。

### resolveChallenge 逻辑

```
1. hasUpheld = 遍历 verdicts 检查 result==0

2. 赏金分配：
   - 有 upheld: require(winnerPayout <= bounty - incentive)
   - 无 upheld: require(winnerPayout <= bounty)
   → transfer(finalWinner, winnerPayout)

3. 逐 verdict 处理押金：
   upheld:
     - transfer(challenger, deposit) 全额退回
     - arbiterReward = deposit × 30%, 从 incentive 支付
     - _splitAmong(v.arbiters, arbiterReward)

   rejected/malicious + hasUpheld:
     - arbiterShare = deposit × 30% → _splitAmong(v.arbiters, ...)
     - remaining 70% → platformTotal

   rejected/malicious + !hasUpheld:
     - arbiterShare = deposit × 30% → _splitAmong(v.arbiters, ...)
     - winnerComp = deposit × 10% → winnerBonus
     - remaining 60% → platformTotal

4. hasUpheld 时 incentive 余额 → winnerBonus

5. winnerBonus > 0 → transfer(finalWinner, winnerBonus)

6. 剩余（platformTotal + serviceFees + rounding）→ transfer(owner())
```

### _splitAmong 内部函数

```solidity
function _splitAmong(address[] calldata addrs, uint256 amount) internal returns (uint256 sent) {
    if (addrs.length == 0 || amount == 0) return 0;
    uint256 per = amount / addrs.length;
    for (uint i = 0; i < addrs.length; i++) {
        usdc.transfer(addrs[i], per);
    }
    return per * addrs.length; // rounding remainder stays → platform
}
```

### 不变的函数

- `createChallenge` — 不变
- `joinChallenge` — 不变
- `emergencyWithdraw` — 不变

## 后端改动

### `app/services/escrow.py` — `resolve_challenge_onchain()`

- 去掉 `arbiter_wallets` 参数
- verdicts 参数改为包含 per-challenge `arbiters` 地址列表
- ABI 调用匹配新合约签名

### `app/scheduler.py` — `_settle_after_arbitration()`

构建 verdicts 时为每个 challenge 附加该挑战的 arbiter 钱包：

```python
for c in challenges:
    jury_votes = db.query(ArbiterVote).filter_by(challenge_id=c.id).all()
    # 共识：只传 coherent；僵局：传全部
    if any(v.coherence_status == "neutral" for v in jury_votes):
        arbiter_ids = [v.arbiter_user_id for v in jury_votes if v.vote is not None]
    else:
        arbiter_ids = [v.arbiter_user_id for v in jury_votes
                       if v.coherence_status == "coherent"]
    arbiter_wallets = [u.wallet for u in db.query(User).filter(User.id.in_(arbiter_ids)).all()]
    verdicts.append({
        "challenger": c.challenger_wallet,
        "result": result_map[c.verdict],
        "arbiters": arbiter_wallets,
    })
```

### `app/scheduler.py` — `_resolve_via_contract()`

- 检测 `has_upheld = any(v["result"] == 0 for v in verdicts)`
- 当 `has_upheld`：`payout_amount = min(task.bounty * rate, task.bounty * 0.85)`
- 去掉 `arbiter_wallets` 参数

### 不需改动的部分

- `createChallenge` / `create_challenge_onchain()` — 不变
- `joinChallenge` / `join_challenge_onchain()` — 不变
- Trust 信誉分逻辑 — 不变
- 前端 — 不变

## 数值验证

### 案例 1：bounty=5, B 级 upheld + A 级 rejected

```
锁仓: 4.75, incentive: 0.50, mainBounty: 4.25
B级 deposit: 1.50, A级 deposit: 0.50

winnerPayout = min(5.0 × 0.85, 4.25) = 4.25 → finalWinner
upheld (B级): 1.50 全退; arbiter = 0.45 from incentive
rejected (A级): arbiter = 0.15; platform += 0.35

incentive 余额: 0.50 - 0.45 = 0.05 → winnerBonus
Winner 总计: 4.25 + 0.05 = 4.30
Arbiters: 0.45 + 0.15 = 0.60
Platform: 0.35 + 0.02(fees) = 0.37
检验: 4.30 + 1.50 + 0.60 + 0.37 = 6.77 ✓
```

### 案例 2：bounty=5, A 级 rejected + B 级 rejected（无 upheld）

```
锁仓: 4.75
A级 deposit: 0.50, B级 deposit: 1.50

winnerPayout = 5.0 × 0.85 = 4.25 → originalWinner (S级假设)
A级 rejected: arbiter=0.15, winner_comp=0.05, platform+=0.30
B级 rejected: arbiter=0.45, winner_comp=0.15, platform+=0.90

Winner 总计: 4.25 + 0.05 + 0.15 = 4.45
Arbiters: 0.15 + 0.45 = 0.60
Platform: 4.75 - 4.25 + 0.30 + 0.90 + 0.02(fees) = 1.72
检验: 4.45 + 0.60 + 1.72 = 6.77 ✓
```

### 案例 3：bounty=5, 无挑战者

```
锁仓: 4.75
winnerPayout = 5.0 × 0.80 = 4.00 (A级原winner)
Platform: 4.75 - 4.00 = 0.75
检验: 4.00 + 0.75 = 4.75 ✓
```

## 修改文件清单

| 文件 | 操作 |
|------|------|
| `contracts/src/ChallengeEscrow.sol` | Verdict 新增 arbiters, resolveChallenge 重写, 新增 _splitAmong |
| `contracts/test/ChallengeEscrow.t.sol` | 全面更新测试 |
| `app/services/escrow.py` | resolve_challenge_onchain 签名和 ABI 调用更新 |
| `app/scheduler.py` | _settle_after_arbitration 构建 per-challenge arbiter 列表 + _resolve_via_contract 逻辑更新 |
| `tests/test_scheduler.py` | 更新 mock |

## 验证

1. `forge test` — 合约测试全过
2. `pytest -v -k "challenge or scheduler"` — 后端测试全过
3. 部署新合约到 Base Sepolia，更新 `.env` 和 `.env.local`
4. 手动测试案例 1/2/3 验证链上分配正确
