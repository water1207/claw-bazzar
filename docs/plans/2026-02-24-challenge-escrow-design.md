# 挑战阶段智能合约托管设计

日期：2026-02-24

## 概述

将 quality_first 任务的挑战阶段资金流从链下 ERC-20 直转改为链上智能合约托管。平台通过 ChallengeEscrow 合约锁定赏金，用 EIP-2612 Permit + Relayer 模式帮挑战者免 gas 缴纳押金，仲裁完成后由平台 Oracle 调合约批量结算。

## 核心决策

| 决策 | 选择 |
|------|------|
| 合约框架 | Foundry (Solidity + Forge) |
| 架构模式 | 单一 ChallengeEscrow 合约（方案 A） |
| Relayer | 平台后端 (PLATFORM_PRIVATE_KEY) |
| Oracle | 平台后端 (scheduler 仲裁后调合约) |
| 挑战押金 | bounty × 10% |
| 罚没押金归属 | 转入平台账户 |
| 网络服务费 | 0.01 USDC (回收 gas 成本) |
| 防空头支票 | 链下余额校验 + 频率限制 + 合约 nonce |

## Section 1：智能合约 ChallengeEscrow

### 状态存储

```solidity
struct ChallengeInfo {
    address winner;           // 暂定获胜者钱包
    uint256 bounty;           // 锁定的赏金（bounty × 80%）
    uint256 depositAmount;    // 每个挑战者需缴纳的押金 (bounty × 10%)
    uint256 serviceFee;       // 网络服务费 (0.01 USDC = 10000 wei)
    uint8   challengerCount;  // 挑战者数量
    bool    resolved;         // 是否已结算
}

mapping(bytes32 => ChallengeInfo) public challenges;  // taskId => info
mapping(bytes32 => mapping(address => bool)) public challengers;  // taskId => challenger => joined
```

### 核心函数

| 函数 | 调用者 | 作用 |
|------|--------|------|
| `createChallenge(taskId, winner, bounty, depositAmount)` | 平台 (owner) | 把赏金从平台钱包转入合约并初始化 |
| `joinChallenge(taskId, challenger, deadline, v, r, s)` | 平台 Relayer | 用 EIP-2612 Permit 代扣押金+服务费 |
| `resolveChallenge(taskId, finalWinner, Verdict[])` | 平台 Oracle | 批量结算：分配赏金、退还/扣除押金 |
| `emergencyWithdraw(taskId)` | 平台 (owner) | 紧急提款（超时 30 天未结算的安全阀） |

### 访问控制

- `owner`：平台地址 (`PLATFORM_WALLET`)，唯一有权调用所有写入函数
- 合约不接受用户直接调用，所有操作通过平台 Relayer 中转
- 使用 OpenZeppelin `Ownable` 做权限管理

### Verdict 结算逻辑

```solidity
struct Verdict {
    address challenger;
    uint8   result;      // 0=upheld, 1=rejected, 2=malicious
}
```

结算规则：
- **upheld (0)**：退还 100% 押金给挑战者
- **rejected (1)**：退还 70% 押金，30% 转平台
- **malicious (2)**：0% 退还，100% 转平台
- 服务费始终归平台
- 有 upheld 挑战者 → 赏金转给 finalWinner（后端传入 arbiter_score 最高的挑战者）
- 无 upheld 挑战者 → 赏金转给原 winner

## Section 2：Relayer + 防空头支票

### 挑战全流程

```
前端                              后端 (Relayer)                    链上
 │                                    │                              │
 ├─ 1. 签名 EIP-2612 Permit ────────→│                              │
 │   (授权合约扣 deposit+fee)         │                              │
 │                                    ├─ 2. 校验链下 USDC 余额 ────→│ (RPC: balanceOf)
 │                                    │← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┤
 │                                    │                              │
 │                                    ├─ 3. 频率限制检查              │
 │                                    │   (DB: 同地址1分钟内无挑战)   │
 │                                    │                              │
 │                                    ├─ 4. 发送 joinChallenge tx ──→│
 │                                    │   (含 permit 参数)            │ → permit() + transferFrom()
 │                                    │← ─ tx_hash ─ ─ ─ ─ ─ ─ ─ ─ ┤
 │← 5. 返回成功 ─────────────────────┤                              │
```

### 前端签名

前端用 viem 签名 EIP-2612 Permit，授权 ChallengeEscrow 合约从挑战者钱包扣 `deposit + serviceFee`：

```typescript
const { v, r, s } = await walletClient.signTypedData({
  domain: {
    name: "USDC", version: "2",
    chainId: 84532,
    verifyingContract: USDC_ADDRESS
  },
  types: {
    Permit: [
      { name: "owner", type: "address" },
      { name: "spender", type: "address" },   // ChallengeEscrow 合约地址
      { name: "value", type: "uint256" },      // deposit + serviceFee
      { name: "nonce", type: "uint256" },
      { name: "deadline", type: "uint256" }
    ]
  },
  primaryType: "Permit",
  message: {
    owner: challengerAddr,
    spender: escrowAddr,
    value: totalAmount,
    nonce,
    deadline
  }
});
```

### 后端 Relayer 逻辑

```python
# POST /tasks/{task_id}/challenges
async def create_challenge(task_id, body: ChallengeCreate):
    # 1. 业务校验（现有逻辑：challenge_window、不能挑战自己等）

    # 2. 链下余额校验
    balance = await check_usdc_balance(body.challenger_wallet)
    required = task.submission_deposit + SERVICE_FEE
    if balance < required:
        raise HTTPException(400, "USDC余额不足")

    # 3. 频率限制
    recent = db.query(Challenge).filter(
        Challenge.challenger_wallet == body.challenger_wallet,
        Challenge.created_at > datetime.utcnow() - timedelta(minutes=1)
    ).first()
    if recent:
        raise HTTPException(429, "每分钟最多提交一次挑战")

    # 4. 调合约 joinChallenge（Relayer 代付 gas）
    tx_hash = await call_join_challenge(
        task_id, body.challenger_wallet,
        body.deadline, body.v, body.r, body.s
    )

    # 5. 保存 Challenge 记录
    challenge = Challenge(task_id=task_id, ..., deposit_tx_hash=tx_hash)
    db.add(challenge)
```

### 防护措施

| 攻击 | 防护 | 层级 |
|------|------|------|
| 余额不足签名 | 链下 `balanceOf` RPC 查询 | 后端 |
| 并发双花 | 1分钟频率限制 + DB 行锁 | 后端 |
| permit replay | EIP-2612 nonce 自增 | 合约 |
| Gas 白嫖 | 余额校验拦截在链下 | 后端 |
| Gas 费回收 | 0.01 USDC 服务费 | 合约 |

## Section 3：仲裁结算 + 赏金分配

### 结算触发

scheduler 的 `_settle_after_arbitration()` 在所有 challenge 都 judged 后触发链上结算：

```
Scheduler                          后端                              链上
 │                                    │                              │
 ├─ 所有 challenge 已 judged ────────→│                              │
 │                                    ├─ 1. 构建 Verdict[] 数组       │
 │                                    ├─ 2. 确定 finalWinner          │
 │                                    │   (有upheld→最高arbiter_score) │
 │                                    │   (无upheld→原winner)         │
 │                                    ├─ 3. 调 resolveChallenge() ──→│
 │                                    │← ─ tx_hash ─ ─ ─ ─ ─ ─ ─ ─ ┤
 │                                    ├─ 4. 更新 DB                   │
 │                                    │   task.payout_tx_hash = hash  │
 │                                    │   task.payout_status = paid   │
```

### 合约结算伪代码

```solidity
function resolveChallenge(
    bytes32 taskId,
    address finalWinner,
    Verdict[] calldata verdicts
) external onlyOwner {
    ChallengeInfo storage info = challenges[taskId];
    require(!info.resolved, "Already resolved");

    // 1. 赏金 → 最终 winner
    usdc.transfer(finalWinner, info.bounty);

    // 2. 逐个处理押金
    uint256 platformTotal = 0;
    for (uint i = 0; i < verdicts.length; i++) {
        if (verdicts[i].result == 0) {        // upheld
            usdc.transfer(verdicts[i].challenger, info.depositAmount);
        } else if (verdicts[i].result == 1) { // rejected
            usdc.transfer(verdicts[i].challenger, info.depositAmount * 70 / 100);
            platformTotal += info.depositAmount * 30 / 100;
        } else {                               // malicious
            platformTotal += info.depositAmount;
        }
    }

    // 3. 罚没押金 + 所有服务费 → 平台
    platformTotal += info.serviceFee * info.challengerCount;
    if (platformTotal > 0) {
        usdc.transfer(owner(), platformTotal);
    }

    info.resolved = true;
    emit ChallengeResolved(taskId, finalWinner);
}
```

### 无挑战时的流程

challenge_window 结束没人挑战 → **不走合约**（`createChallenge` 未调用，赏金在平台钱包）→ 沿用现有 `pay_winner()` 直接 ERC-20 transfer。

关键判断：
- 无挑战 → `pay_winner()`（现有逻辑不变）
- 有挑战 → `createChallenge` → `joinChallenge` → `resolveChallenge`（新合约流程）

### emergencyWithdraw

安全阀：task 挑战超过 30 天未结算时，owner 可调 `emergencyWithdraw` 把资金退回平台，后续手动处理。

## Section 4：项目结构 + 后端集成

### Foundry 项目

```
contracts/
├── foundry.toml
├── src/
│   └── ChallengeEscrow.sol
├── test/
│   └── ChallengeEscrow.t.sol
├── script/
│   └── Deploy.s.sol
└── lib/
    └── openzeppelin-contracts/
```

### 后端新增

```
app/services/
├── escrow.py
│   ├── create_challenge_onchain()
│   ├── join_challenge_onchain()
│   ├── resolve_challenge_onchain()
│   ├── check_usdc_balance()
│   └── get_challenge_escrow_abi()
```

### 现有代码改动

| 文件 | 改动 |
|------|------|
| `app/routers/challenges.py` | 增加余额校验、频率限制、调 `join_challenge_onchain()` |
| `app/scheduler.py` | `_settle_after_arbitration()` 增加链上结算分支 |
| `app/models.py` | Challenge 新增 `deposit_tx_hash`、`challenger_wallet` |
| `app/schemas.py` | ChallengeCreate 新增 `challenger_wallet`、`deadline`、`v`、`r`、`s` |
| `.env` | 新增 `ESCROW_CONTRACT_ADDRESS` |

### 环境变量

```
ESCROW_CONTRACT_ADDRESS=0x...       # 部署后的合约地址
```

### 测试策略

- **合约层**：Forge test，fork 模式测真实 USDC
- **后端层**：mock `escrow.py` 链上调用，与现有 mock 模式一致
- **集成测试**：Base Sepolia testnet 端对端
