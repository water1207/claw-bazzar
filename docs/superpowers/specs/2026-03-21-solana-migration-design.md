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
| 后端 Solana 客户端 | `solana-py` + `solders` 原生指令构造（不使用 `anchorpy`，因其已停止维护） |
| 私钥格式 | JSON 字节数组（64 字节，与 `solana-keygen` 输出一致） |

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

3. **x402 `extra` 字段适配**：
   - 当前 EVM: `extra: {"assetTransferMethod": "eip3009", "name": "USDC", "version": "2"}`
   - Solana: 按 x402 Solana SDK 规范设置（参考 `@x402/svm` 文档），预计为 SPL transfer 方法标识

4. **环境变量变更**：
   - `X402_NETWORK`: `eip155:84532` → `solana-devnet`
   - `USDC_CONTRACT` → `USDC_MINT`: Solana Devnet USDC mint address
   - `PLATFORM_WALLET`: EVM 地址 → Solana pubkey（Base58）
   - `PLATFORM_PRIVATE_KEY`: EVM 私钥 → Solana keypair（JSON 字节数组，64 字节）
   - `FACILITATOR_URL`: 保持 `https://x402.org/facilitator`（同一端点已支持 Solana），如需独立 Solana facilitator 则更新

5. **依赖清理**：
   - `pyproject.toml` 中的 `fastapi-x402` 依赖：检查是否实际使用，若仅用 httpx 直调则移除

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

- `check_usdc_balance()`（当前在 `app/services/escrow.py` 中）→ 查询 ATA 的 token balance（`get_token_account_balance`），保留在 `escrow.py`

### 地址验证

- `app/schemas.py` 中 `UserCreate.normalize_wallet()` 当前调用 `.lower()`（EVM hex 地址不区分大小写）
- Solana Base58 地址**区分大小写**，必须移除 `.lower()` 调用，改为 Base58 格式校验
- `app/routers/users.py` 中用户查重逻辑 `func.lower(User.wallet) == data.wallet.lower()` 改为精确匹配

**影响文件**：`app/services/payout.py`（重写）, `app/services/escrow.py`（余额查询适配）, `frontend/lib/utils.ts`（余额查询改为 Solana RPC）, `app/schemas.py`（地址验证）, `app/routers/users.py`（查重逻辑）

## Section 3：ChallengeEscrow Anchor 程序

### 权限模型

- **Config PDA**：`seeds = [b"config"]`，存储 `authority: Pubkey`（平台管理员）和 `usdc_mint: Pubkey`
- 程序初始化时设置 authority，后续 `create_challenge`、`resolve_challenge`、`void_challenge` 均需 authority 签名
- 等价于 EVM 的 OpenZeppelin `Ownable` + `onlyOwner` 修饰符

### 账户模型（PDA 设计）

- **ChallengeInfo PDA**：`seeds = [b"challenge", task_id_hash]`，存储 winner、bounty、incentive、challenger_count、resolved、created_at、total_deposits
- **Escrow Token Account**：全局 PDA 拥有的 USDC token account，`seeds = [b"escrow_vault"]`。所有 challenge 共享一个 vault（简化账户管理），ChallengeInfo 内部记账跟踪每个 challenge 的余额。（注：不使用 per-challenge ATA，因为标准 ATA 由 owner+mint 唯一确定，无法区分不同 challenge）
- **ChallengerRecord PDA**：`seeds = [b"challenger", task_id_hash, challenger_pubkey]`，存储 deposit_amount、joined 状态

### 指令

- `create_challenge(task_id, bounty, incentive)` — 平台签名，从平台 ATA 转入 escrow token account
- `join_challenge(task_id, deposit_amount)` — 挑战者签名，从自己的 ATA 转入 escrow（+ 0.01 USDC 服务费），无需 Permit（Solana 交易本身就是签名授权）
- `resolve_challenge(task_id, final_winner, winner_payout, refunds[], arbiters[], arbiter_reward)` — 平台签名，从 escrow 分发给各方
- `void_challenge(task_id, publisher, publisher_refund, refunds[], arbiters[], arbiter_reward)` — 平台签名，退款 + 分发
- `emergency_withdraw(task_id)` — 30 天超时回收

### 关键差异 vs Solidity

- **无需 Permit**：Solana 交易天然由签名者授权，挑战者直接签名 `join_challenge` 交易即转账
- **Remaining Accounts 模式**：`resolve_challenge` 需要动态数量的收款人 ATA，通过 `remaining_accounts` 传入
- **task_id 转换**：UUID → `sha256(task_id)`，SHA-256 输出恰好 32 字节，直接用作 PDA seed（替代 EVM 的 keccak256）
- **交易大小限制**：Solana 单笔交易最大 1232 字节。`resolve_challenge` 含多个 refund + arbiter 账户时可能超限。设计约束：每次 resolve 最多支持 8 个 remaining accounts（约 4 个 challenger + 3 个 arbiter + winner）。如超出则后端分批调用

### 事件

`ChallengeCreated`, `ChallengerJoined`, `ChallengeResolved`（Anchor `emit!`）

**文件位置**：`programs/challenge-escrow/src/lib.rs`

## Section 4：StakingVault Anchor 程序

### 权限模型

- 同 ChallengeEscrow，**Config PDA** `seeds = [b"config"]` 存储 `authority` 和 `usdc_mint`

### 账户模型

- **StakeRecord PDA**：`seeds = [b"stake", user_pubkey]`，存储 amount、staked_at
- **Vault Authority PDA**：`seeds = [b"vault_authority"]`，作为 vault token account 的 owner（程序通过 PDA 签名控制资金）
- **Vault Token Account**：由 Vault Authority PDA 拥有的 USDC token account，持有所有质押资金

### 指令

- `stake(amount)` — 用户签名，从用户 ATA 转入 vault（100 USDC）
- `unstake(amount)` — 用户签名，从 vault 转回用户 ATA（PDA 签名授权转出）
- `slash(user)` — **平台 authority 签名**，没收用户全部质押转入平台 ATA
- `emergency_withdraw(user)` — **平台 authority 签名**，30 天超时后可回收（检查 `staked_at + 30 days < now`）

无需 Permit — 用户直接签名交易即完成授权转账。

**文件位置**：`programs/staking-vault/src/lib.rs`

## Section 5：后端 Escrow/Staking 服务层

### `app/services/escrow.py` 重写

- 依赖：`solana-py`（`solana` + `solders`），**不使用 `anchorpy`**（已停止维护，不兼容 Anchor 0.30+ IDL）
- 手动构造 Anchor 指令：计算 8 字节 instruction discriminator（`sha256("global:<method_name>")[:8]`），拼接 Borsh 序列化参数
- task_id 转换：`hashlib.sha256(task_id.encode()).digest()` 替代 `keccak256`
- PDA 推导：`Pubkey.find_program_address([b"challenge", task_id_hash], program_id)`
- 四个函数签名不变（`create_challenge_onchain`, `join_challenge_onchain`, `resolve_challenge_onchain`, `void_challenge_onchain`），内部改为构造 Solana 指令 + 发送交易
- `resolve` / `void` 通过 `remaining_accounts` 传入动态收款人 ATA 列表
- 封装 `_build_anchor_instruction(program_id, method_name, args_bytes, accounts)` 工具函数复用

### `app/services/staking.py` 重写

- 同样用 `solana-py` + 手动 discriminator 构造指令
- `stake_onchain()` / `slash_onchain()` 改为 Solana 指令调用
- 去掉 Permit 参数（v, r, s），Solana 端由前端直接签名

### 交易模式变更

```python
# EVM (旧)
tx = contract.functions.method().build_transaction({...})
signed = account.sign_transaction(tx)
w3.eth.send_raw_transaction(signed.raw_transaction)

# Solana (新) — 原生 solana-py，无 anchorpy
discriminator = hashlib.sha256(b"global:create_challenge").digest()[:8]
data = discriminator + borsh_serialize(args)
ix = Instruction(program_id, data, account_metas)
tx = Transaction().add(ix)
client.send_transaction(tx, payer, opts=TxOpts(skip_confirmation=False))
```

### 环境变量

- `ESCROW_CONTRACT_ADDRESS` → `ESCROW_PROGRAM_ID`（Solana program pubkey）
- `STAKING_CONTRACT_ADDRESS` → `STAKING_PROGRAM_ID`
- `BASE_SEPOLIA_RPC_URL` → `SOLANA_RPC_URL`（`https://api.devnet.solana.com`）

### API Schema 变更（`app/schemas.py`）

**ChallengeCreate**：移除 `permit_deadline`, `permit_v`, `permit_r`, `permit_s` 字段，新增：
- `signed_transaction: str` — 前端签名的 `join_challenge` 交易（base64 序列化）

**StakeRequest**：移除 `permit_deadline`, `permit_v`, `permit_r`, `permit_s` 字段，新增：
- `signed_transaction: str` — 前端签名的 `stake` 交易（base64 序列化）

**流程**：后端收到 `signed_transaction` 后直接提交到链上（`client.send_raw_transaction()`），无需后端重新签名用户侧指令。

### Router 重写

- `app/routers/challenges.py`：当前深度依赖 Permit 参数传递给 `join_challenge_onchain()`，需**重写**为接收 `signed_transaction` 并直接上链
- `app/routers/trust.py`：staking 路由同理重写

**影响文件**：`app/services/escrow.py`, `app/services/staking.py`, `app/schemas.py`（schema 重写）, `app/routers/challenges.py`（重写）, `app/routers/trust.py`（重写）, `app/scheduler.py`（调用签名不变，无需大改）

## Section 6：前端迁移

### `frontend/lib/x402.ts` 重写

- `@solana/web3.js` 的 `Keypair.fromSecretKey()` 替代 `privateKeyToAccount()`
- 构造 SPL transfer 交易替代 EIP-712 `signTypedData`
- 序列化 + base64 编码放入 `X-PAYMENT` header
- 去掉 EIP-3009 相关类型定义

### `frontend/lib/permit.ts` → 删除，新建 `frontend/lib/sign-challenge.ts`

- Solana 无需 Permit，挑战者加入 challenge 时直接签名交易
- 使用 `@coral-xyz/anchor` 加载 IDL（从 `target/idl/challenge_escrow.json` 复制到前端 `public/` 或编译时内联），构造 `join_challenge` 指令
- IDL 分发：Anchor build 后将 `target/idl/*.json` 复制到 `frontend/lib/idl/` 目录，前端 import 使用
- 需推导 PDA（ChallengerRecord、ChallengeInfo、escrow vault）和用户 ATA
- 用户 Keypair 签名完整交易，base64 序列化后 POST 给后端 `/challenges/{id}/join`
- 同理 staking：新建 `frontend/lib/sign-stake.ts`，构造 `stake` 指令并签名

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

- `DevPanel.tsx`：**重写**（非小改），当前 import `signChallengePermit`、`type { Hex } from 'viem'`、Permit 签名流程（~15 行），需全部替换为 Solana 签名流程，`placeholder="0x..."` 改为 Solana 地址示例
- `ChallengePanel.tsx`：地址显示 + 挑战签名流程
- `SettlementPanel.tsx`：explorer 链接从 `https://sepolia.basescan.org/tx` → `https://explorer.solana.com/tx/{sig}?cluster=devnet`
- `TaskDetail.tsx`：同上 explorer 链接替换
- `LeaderboardTable.tsx`、`ProfileView.tsx`：地址截断逻辑适配（Solana 44 chars Base58 vs EVM 42 chars hex）
- 所有组件：移除 `viem` 类型导入

**影响文件**：`frontend/lib/x402.ts`, `frontend/lib/permit.ts`（删除）, `frontend/lib/utils.ts`, `frontend/lib/dev-wallets.ts`, `frontend/package.json`, `frontend/components/DevPanel.tsx`（重写）, `frontend/components/ChallengePanel.tsx`, `frontend/components/SettlementPanel.tsx`, `frontend/components/TaskDetail.tsx`, `frontend/components/LeaderboardTable.tsx`, `frontend/components/ProfileView.tsx`

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
- `frontend/lib/permit.test.ts`（对应测试）

### 新建

- `programs/challenge-escrow/src/lib.rs`（Anchor 程序）
- `programs/staking-vault/src/lib.rs`（Anchor 程序）
- `Anchor.toml`
- `frontend/lib/sign-challenge.ts`（替代 permit.ts）
- `frontend/lib/sign-stake.ts`（staking 签名）
- `frontend/lib/idl/`（Anchor IDL JSON 文件）

### 重写

- `app/services/x402.py` — Solana facilitator 参数
- `app/services/payout.py` — solana-py SPL transfer
- `app/services/escrow.py` — solana-py 原生指令构造（不用 anchorpy）
- `app/services/staking.py` — solana-py 原生指令构造
- `app/schemas.py` — 移除 Permit 字段，新增 signed_transaction；移除地址 .lower()
- `app/routers/challenges.py` — Permit 流程 → signed_transaction 上链
- `app/routers/trust.py` — staking Permit 流程重写
- `frontend/lib/x402.ts` — @solana/web3.js 签名
- `frontend/lib/utils.ts` — Solana RPC 余额查询
- `frontend/lib/dev-wallets.ts` — Solana keypair 格式
- `frontend/components/DevPanel.tsx` — Permit 签名流程 + viem 导入全部替换

### 小改

- `app/routers/tasks.py` — 参数适配
- `app/routers/users.py` — 地址查重去掉 .lower()
- `app/scheduler.py` — 调用签名不变，可能需微调
- `frontend/components/ChallengePanel.tsx` — 地址格式 + 签名流程
- `frontend/components/SettlementPanel.tsx` — explorer 链接改为 Solana Devnet
- `frontend/components/TaskDetail.tsx` — explorer 链接改为 Solana Devnet
- `frontend/components/LeaderboardTable.tsx` — 地址截断适配
- `frontend/components/ProfileView.tsx` — 地址截断适配
- `CLAUDE.md` — 文档同步
- `frontend/package.json` — 依赖变更（移除 viem，新增 @solana/web3.js 等）
- `pyproject.toml` — Python 依赖变更（移除 web3，新增 solana/solders；检查并清理 fastapi-x402）
