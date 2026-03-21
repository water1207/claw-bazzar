# Solana 迁移设计：Base EVM → Solana Devnet

**日期**：2026-03-21
**分支**：solana-x402
**范围**：完全替换 EVM 基础设施（x402 支付、ChallengeEscrow、StakingVault、payout），仅保留 Solana

## 决策摘要

| 决策项 | 选择 |
|--------|------|
| x402 协议 | 继续使用，适配 Solana facilitator |
| 目标网络 | Solana Devnet |
| 合约框架 | Anchor |
| 前端钱包 | DevPanel 私钥模式（Keypair） |
| USDC | Circle 官方 Devnet USDC（`4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`） |
| 迁移范围 | 完全替换，删除所有 EVM 代码 |
| 整体方案 | 完整 Anchor 链上迁移 |

## Section 1：x402 支付层迁移

### 当前流程（EVM）

前端 viem EIP-712 签名 → base64 编码为 `X-PAYMENT` header → 后端调 x402.org facilitator verify/settle → 返回 tx_hash

### Solana 新流程

1. **前端签名**（`frontend/lib/x402.ts` 重写）：
   - 用 `@solana/web3.js` 的 `Keypair` 从私钥创建签名者
   - 构造 SPL Token transfer 指令（from → platform wallet）
   - 签名交易，序列化后 base64 编码放入 `X-PAYMENT` header
   - x402 payload 格式适配 Solana：network 改为 `solana-devnet`，token 改为 USDC mint address

2. **后端验证**（`app/services/x402.py` 重写）：
   - payment requirements 改用 Solana 参数：`network: "solana-devnet"`, `token: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"`
   - 继续调用 x402 facilitator HTTP API 做 verify + settle（流程不变，只改参数）
   - 返回 Solana transaction signature 作为 tx_hash

3. **环境变量变更**：
   - `X402_NETWORK`: `eip155:84532` → `solana-devnet`
   - `USDC_CONTRACT` → `USDC_MINT`: Solana Devnet USDC mint address
   - `PLATFORM_WALLET`: EVM 地址 → Solana pubkey（Base58）
   - `PLATFORM_PRIVATE_KEY`: EVM 私钥 → Solana keypair（Base58 或字节数组）

**影响文件**：`frontend/lib/x402.ts`, `app/services/x402.py`, `app/routers/tasks.py`（小改）

## Section 2：Payout 服务迁移

### 依赖替换

`web3.py` → `solana-py`（`solana` + `solders` + `spl-token`）

### 核心函数重写

- `_send_usdc_transfer(to_address, amount)` → 构造 SPL Token `transfer` 指令：
  - 获取平台的 Associated Token Account（ATA）
  - 获取/创建收款方的 ATA（如不存在则附带 `create_associated_token_account` 指令）
  - 构造 `spl.token.transfer()` 指令（amount 仍为 6 decimals）
  - 签名发送，等待确认（`commitment="confirmed"`）
- `pay_winner()` / `refund_publisher()` 逻辑不变，只是底层调用换了

### 地址格式

- 数据库中 `wallet_address` 从 `0x...`（40 hex）→ Base58 Solana pubkey
- 用户注册时提交 Solana 地址

### 余额查询

- `check_usdc_balance()` → 查询 ATA 的 token balance（`get_token_account_balance`）

**影响文件**：`app/services/payout.py`（重写）, `frontend/lib/utils.ts`（余额查询改为 Solana RPC）

## Section 3：ChallengeEscrow Anchor 程序

### 账户模型（PDA 设计）

- **ChallengeInfo PDA**：`seeds = [b"challenge", task_id_bytes]`，存储 winner、bounty、incentive、challenger_count、resolved、created_at、total_deposits
- **Escrow Token Account**：PDA 拥有的 USDC ATA，每个 challenge 独立，用于持有托管资金
- **ChallengerRecord PDA**：`seeds = [b"challenger", task_id_bytes, challenger_pubkey]`，存储 deposit_amount、joined 状态

### 指令

- `create_challenge(task_id, bounty, incentive)` — 平台签名，从平台 ATA 转入 escrow token account
- `join_challenge(task_id, deposit_amount)` — 挑战者签名，从自己的 ATA 转入 escrow（+ 0.01 USDC 服务费），无需 Permit（Solana 交易本身就是签名授权）
- `resolve_challenge(task_id, final_winner, winner_payout, refunds[], arbiters[], arbiter_reward)` — 平台签名，从 escrow 分发给各方
- `void_challenge(task_id, publisher, publisher_refund, refunds[], arbiters[], arbiter_reward)` — 平台签名，退款 + 分发
- `emergency_withdraw(task_id)` — 30 天超时回收

### 关键差异 vs Solidity

- **无需 Permit**：Solana 交易天然由签名者授权，挑战者直接签名 `join_challenge` 交易即转账
- **Remaining Accounts 模式**：`resolve_challenge` 需要动态数量的收款人 ATA，通过 `remaining_accounts` 传入
- **task_id 转换**：UUID → `sha256(task_id)` 取前 32 字节作为 PDA seed（替代 EVM 的 keccak256）

### 事件

`ChallengeCreated`, `ChallengerJoined`, `ChallengeResolved`（Anchor `emit!`）

**文件位置**：`programs/challenge-escrow/src/lib.rs`

## Section 4：StakingVault Anchor 程序

### 账户模型

- **StakeRecord PDA**：`seeds = [b"stake", user_pubkey]`，存储 amount、staked_at
- **Vault Token Account**：程序拥有的全局 USDC ATA，持有所有质押资金

### 指令

- `stake(amount)` — 用户签名，从用户 ATA 转入 vault（100 USDC）
- `unstake(amount)` — 用户签名，从 vault 转回用户 ATA
- `slash(user)` — 平台签名（authority），没收用户全部质押
- `emergency_withdraw(user)` — 30 天超时回收

无需 Permit — 用户直接签名交易即完成授权转账。

**文件位置**：`programs/staking-vault/src/lib.rs`

## Section 5：后端 Escrow/Staking 服务层

### `app/services/escrow.py` 重写

- 依赖：`solana-py` + `anchorpy`（Anchor Python 客户端）
- 加载 Anchor IDL（从 `target/idl/challenge_escrow.json`）
- task_id 转换：`hashlib.sha256(task_id.encode()).digest()` 替代 `keccak256`
- PDA 推导：`Pubkey.find_program_address([b"challenge", task_id_hash], program_id)`
- 四个函数签名不变（`create_challenge_onchain`, `join_challenge_onchain`, `resolve_challenge_onchain`, `void_challenge_onchain`），内部改为构造 Anchor 指令 + 发送交易
- `resolve` / `void` 通过 `remaining_accounts` 传入动态收款人 ATA 列表

### `app/services/staking.py` 重写

- 同样用 `anchorpy` 加载 IDL
- `stake_onchain()` / `slash_onchain()` 改为 Anchor 指令调用
- 去掉 Permit 参数（v, r, s），Solana 端由前端直接签名

### 交易模式变更

```python
# EVM (旧)
tx = contract.functions.method().build_transaction({...})
signed = account.sign_transaction(tx)
w3.eth.send_raw_transaction(signed.raw_transaction)

# Solana (新)
ix = program.instruction["method"](args, ctx=Context(accounts={...}))
tx = Transaction().add(ix)
client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
```

### 环境变量

- `ESCROW_CONTRACT_ADDRESS` → `ESCROW_PROGRAM_ID`（Solana program pubkey）
- `STAKING_CONTRACT_ADDRESS` → `STAKING_PROGRAM_ID`
- `BASE_SEPOLIA_RPC_URL` → `SOLANA_RPC_URL`（`https://api.devnet.solana.com`）

**影响文件**：`app/services/escrow.py`, `app/services/staking.py`, `app/scheduler.py`（调用签名不变，无需大改）

## Section 6：前端迁移

### `frontend/lib/x402.ts` 重写

- `@solana/web3.js` 的 `Keypair.fromSecretKey()` 替代 `privateKeyToAccount()`
- 构造 SPL transfer 交易替代 EIP-712 `signTypedData`
- 序列化 + base64 编码放入 `X-PAYMENT` header
- 去掉 EIP-3009 相关类型定义

### `frontend/lib/permit.ts` → 删除或重写为 `sign-challenge.ts`

- Solana 无需 Permit，挑战者加入 challenge 时直接签名交易
- 构造 `join_challenge` Anchor 指令，用户 Keypair 签名，序列化后发送给后端
- 同理 staking 也改为直接签名

### `frontend/lib/utils.ts` 余额查询

- `getUsdcBalance()` 改为调用 Solana RPC `getTokenAccountBalance`
- 需要先通过 `getAssociatedTokenAddress()` 获取用户的 USDC ATA
- RPC endpoint 改为 `https://api.devnet.solana.com`

### `frontend/lib/dev-wallets.ts`

- 私钥格式从 hex → Base58 或字节数组（Solana Keypair 格式）
- 地址从 `0x...` → Base58 pubkey

### 依赖变更

- 移除：`viem`
- 新增：`@solana/web3.js`, `@solana/spl-token`, `@coral-xyz/anchor`

### 组件层

- `DevPanel.tsx`、`ChallengePanel.tsx` 等组件中的地址显示从 `0x` 格式改为 Base58
- 地址长度展示截断逻辑调整（Solana 地址更长）

**影响文件**：`frontend/lib/x402.ts`, `frontend/lib/permit.ts`, `frontend/lib/utils.ts`, `frontend/lib/dev-wallets.ts`, `frontend/package.json`, 以及使用钱包地址的组件

## Section 7：测试与配置

### 后端测试

- 现有 mock 模式不变：`verify_payment` mock 返回 `{"valid": True, "tx_hash": "..."}`，tx_hash 改为 Solana 风格的 Base58 签名
- `payout.py` / `escrow.py` / `staking.py` 的链上调用继续 mock
- 无需真实 Solana 节点跑测试

### Anchor 程序测试

- Anchor 自带测试框架（`anchor test`），用 TypeScript 写集成测试
- 在本地 `solana-test-validator` 上跑，部署程序 + mock USDC mint
- 测试用例覆盖：create → join → resolve、void、emergency_withdraw

### 前端测试

- `x402.test.ts` 重写：mock `@solana/web3.js` 的签名和序列化
- permit 相关测试删除，新增 challenge 签名测试

### 项目结构变更

```
contracts/          → 删除（Foundry/Solidity）
programs/           → 新建
  challenge-escrow/ → Anchor 程序
  staking-vault/    → Anchor 程序
Anchor.toml         → 新建（Anchor 配置）
```

### 环境变量汇总

| 旧（EVM） | 新（Solana） |
|-----------|-------------|
| `X402_NETWORK=eip155:84532` | `X402_NETWORK=solana-devnet` |
| `USDC_CONTRACT=0x036C...` | `USDC_MINT=4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU` |
| `PLATFORM_WALLET=0x32dD...` | `PLATFORM_WALLET=<Base58 pubkey>` |
| `PLATFORM_PRIVATE_KEY=0x...` | `PLATFORM_PRIVATE_KEY=<Base58 keypair>` |
| `BASE_SEPOLIA_RPC_URL` | `SOLANA_RPC_URL=https://api.devnet.solana.com` |
| `ESCROW_CONTRACT_ADDRESS` | `ESCROW_PROGRAM_ID=<program pubkey>` |
| `STAKING_CONTRACT_ADDRESS` | `STAKING_PROGRAM_ID=<program pubkey>` |

### CLAUDE.md 更新

命令、环境变量、架构描述同步更新为 Solana 相关内容。

## 影响文件清单

### 删除

- `contracts/` 目录（Foundry/Solidity）
- `frontend/lib/permit.ts`（EIP-2612 Permit）

### 新建

- `programs/challenge-escrow/src/lib.rs`（Anchor 程序）
- `programs/staking-vault/src/lib.rs`（Anchor 程序）
- `Anchor.toml`
- `frontend/lib/sign-challenge.ts`（替代 permit.ts）

### 重写

- `app/services/x402.py` — Solana facilitator 参数
- `app/services/payout.py` — solana-py SPL transfer
- `app/services/escrow.py` — anchorpy Anchor 调用
- `app/services/staking.py` — anchorpy Anchor 调用
- `frontend/lib/x402.ts` — @solana/web3.js 签名
- `frontend/lib/utils.ts` — Solana RPC 余额查询
- `frontend/lib/dev-wallets.ts` — Solana keypair 格式

### 小改

- `app/routers/tasks.py` — 参数适配
- `app/scheduler.py` — 调用签名不变，可能需微调
- `frontend/components/DevPanel.tsx` — 地址格式
- `frontend/components/ChallengePanel.tsx` — 地址格式
- `CLAUDE.md` — 文档同步
- `frontend/package.json` — 依赖变更
- `requirements.txt` / `pyproject.toml` — Python 依赖变更
