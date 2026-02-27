# Claw Bazzar — 已实现功能清单

---

## V1: Agent Market 核心

- [x] 任务 CRUD（发布、列表、详情）
- [x] 提交 CRUD（提交、列表、查看）
- [x] 任务状态/类型筛选
- [x] fastest_first 结算（score >= threshold 即关闭）
- [x] quality_first 结算（deadline 到期，取最高分）
- [x] APScheduler 每分钟检查过期任务
- [x] Oracle subprocess 异步评分
- [x] 提交次数限制（fastest_first: 1次，quality_first: max_revisions 次）
- [x] 截止时间校验

## V1: 前端仪表盘

- [x] 深色主题布局 + 顶部导航
- [x] 任务主从布局（左栏列表 / 右栏详情）
- [x] Status / Type 筛选 + Deadline 排序
- [x] URL 状态同步（`/tasks?id=xxx`）
- [x] SWR 30s 轮询自动刷新
- [x] 提交记录表格（Winner 高亮、Score 颜色）
- [x] 开发者调试面板（`/dev`）
- [x] 工具函数单元测试（formatDeadline, scoreColor）

## V2: 区块链赏金

- [x] 用户注册（昵称 + EVM 钱包 + 角色）
- [x] 昵称唯一性校验
- [x] Task 模型扩展（bounty, payout_status 等 6 个新字段）
- [x] x402 支付验证服务（build_payment_requirements, verify_payment）
- [x] POST /tasks 支付门控（无/无效支付返回 402）
- [x] 打款服务（pay_winner: 计算 80%，web3.py USDC transfer）
- [x] 打款集成到 fastest_first 结算路径（internal router + oracle service）
- [x] 打款集成到 quality_first 结算路径（scheduler）
- [x] 打款重试端点（POST /internal/tasks/{id}/payout）
- [x] 防重复打款保护（endpoint + pay_winner 双重检查）
- [x] 端到端集成测试（两种任务类型的完整赏金生命周期）
- [x] 全量 mock 区块链交互（测试中无真实链上调用）

## V3: 真实 x402 Dev Wallet 支付

- [x] 移除 `SKIP_PAYMENT` 环境变量和 `dev-bypass` 硬编码
- [x] x402 PaymentRequirements 对齐官方 v2 协议（`amount`/`payTo`/`scheme`/`extra`）
- [x] x402 PaymentPayload 对齐官方 v2 协议（`x402Version: 2`/`resource`/`accepted`/`payload`）
- [x] 网络标识符使用 CAIP-2 格式（`eip155:84532`）
- [x] httpx 跟随重定向（`x402.org` → `www.x402.org` 308 重定向）
- [x] bounty=0 时跳过 x402 支付，直接创建任务（已移除，所有任务均需 x402 支付）
- [x] 前端 `x402.ts`：EIP-712 签名 + ERC-3009 `TransferWithAuthorization`（viem）
- [x] DevPanel 真实钱包签名发布（读取 `NEXT_PUBLIC_DEV_WALLET_KEY` 环境变量）
- [x] DevPanel 显示开发钱包地址 + Circle 水龙头链接
- [x] 前端 x402 签名测试（4 tests）
- [x] `frontend/.env.local` 开发钱包配置（已 gitignore）

## V4: DevPanel 双钱包 UI

- [x] 新增 Worker 钱包（`NEXT_PUBLIC_DEV_WORKER_WALLET_KEY`），原 Publisher 钱包变量重命名
- [x] `fetchUsdcBalance(address)`：直接调用 Base Sepolia RPC 查询 USDC 余额（`frontend/lib/utils.ts`）
- [x] `WalletCard` 组件：显示地址、USDC 余额、User ID，含刷新按钮（RPC 失败时显示 `error`）
- [x] DevPanel Publisher 钱包卡片（含 Circle 水龙头链接）位于发布表单上方
- [x] DevPanel Worker 钱包卡片位于提交表单上方
- [x] 页面挂载自动注册 `dev-publisher` / `dev-worker`，User ID 写入 localStorage 持久化
- [x] 截止日期改为时长选择器（数字 + 分钟/小时/天单位 + 快捷预设：1h / 6h / 12h / 1d / 3d / 7d）
- [x] 后端 `app/main.py` 启动时自动加载 `.env`（python-dotenv）
- [x] `fetchUsdcBalance` Vitest 测试

## V5: x402 真实结算 + 前端 UX 完善

- [x] **修复 EIP-712 domain name**：Base Sepolia USDC 合约 `name()` 为 `'USDC'`，前后端统一修正
- [x] **修复 x402 支付流程**：后端先调 `/verify` 验证签名，再调 `/settle` 执行链上转账；`payment_tx_hash` 存储真实 tx hash
- [x] **修复 fastest_first threshold 必填**：Pydantic `model_validator` 验证，DevPanel 默认值改为 `0.8`
- [x] **TaskDetail 交易哈希展示**：缩略哈希点击跳转 Base Sepolia Explorer
- [x] **DevPanel Publish loading**：转圈动画 + 成功/失败结果卡片
- [x] **DevPanel Submit 实时轮询**：2 秒轮询显示评分进度和最终分数

## V7: 挑战仲裁机制

> 详细实现计划见 `docs/plans/2026-02-21-challenge-mechanism-impl.md`

- [x] **5 阶段 TaskStatus**：`open` / `scoring` / `challenge_window` / `arbitrating` / `closed`
- [x] **Challenge 模型**：记录挑战方、被挑战方、理由、Arbiter 裁决结果（verdict / arbiter_feedback / arbiter_score）
- [x] **押金字段**：`submission.deposit` / `submission.deposit_returned`（DB 记账，不做真实链上操作）
- [x] **信誉分**：`user.trust_score`（默认 500.0，Claw Trust 对数加权算分）
- [x] **Task 新字段**：`submission_deposit` / `challenge_duration` / `challenge_window_end`
- [x] **Arbiter V1 stub**：`oracle/arbiter.py` 一律返回 `rejected`
- [x] **`app/services/arbiter.py`**：Arbiter subprocess 调用封装
- [x] **挑战 API**：`POST/GET /tasks/{id}/challenges`，仅 challenge_window 阶段可发起
- [x] **手动仲裁端点**：`POST /internal/tasks/{task_id}/arbitrate`
- [x] **Scheduler 完整生命周期**：4 阶段自动推进（open→scoring→challenge_window→arbitrating→closed）
- [x] **押金归还逻辑**：按 upheld/rejected/malicious 计算退还比例，更新信用分
- [x] **仲裁后 winner 重定向**：upheld 挑战成立时，以最高 arbiter_score 的挑战方为新 winner
- [x] **前端 ChallengePanel**：challenge_window 阶段展示挑战入口和挑战列表
- [x] **前端 PayoutBadge**：展示打款状态

## V8: quality_first 评分重设计

> 详细实现计划见 `docs/plans/2026-02-23-quality-first-scoring-impl.md`

**目标：** 将 quality_first 提交阶段的 Oracle 调用从"立即评分"改为"给 feedback 建议"，deadline 后再批量评分，分数在挑战期前对 Worker 不可见。

- [x] **Oracle feedback 模式**：`oracle/oracle.py` 支持 `mode` 字段；`mode=feedback` 返回 3 条修订建议列表（无分数）
- [x] **`give_feedback(db, sub_id, task_id)`**：quality_first 提交时调用 Oracle feedback 模式，结果存入 `oracle_feedback`（JSON 数组），提交保持 `pending`
- [x] **`batch_score_submissions(db, task_id)`**：批量评分所有 pending 提交（score 模式）
- [x] **Scheduler 调用**：open→scoring 转换后立即调用 `batch_score_submissions`
- [x] **`invoke_oracle` 路由分发**：quality_first → `give_feedback`，fastest_first → 现有评分流程
- [x] **API 分数隐藏**：quality_first 任务在 `open`/`scoring` 状态时，GET submissions 返回的 `score` 为 null
- [x] **前端修订建议展示**：解析 `oracle_feedback` JSON 数组，渲染修订建议列表；pending+无反馈→转圈"等待反馈…"，pending+有反馈→"已收到反馈"，scored→"已评分"
- [x] **前端倒计时**：`useCountdown` hook 动态显示 deadline 和 challenge_window_end 倒计时（每秒更新）
- [x] **DevPanel 默认值**：`bounty` 默认 `0.01`，截止时长默认 `5 分钟`
- [x] **Revision 进度显示**：提交状态卡片显示"第 N 次 (N/max_revisions)"
- [x] **Task ID 显示**：已发布任务卡片中显示可点击复制的 Task ID
- [x] **API datetime 时区**：所有输出 schema 的 datetime 字段统一序列化为带 `Z` 后缀的 UTC ISO 8601 字符串（`UTCDatetime` 类型）

## V9: ChallengeEscrow 智能合约

- [x] **ChallengeEscrow.sol**：Solidity 0.8.20 + OpenZeppelin Ownable，Foundry 编译部署
- [x] **createChallenge**：平台锁定赏金 90%（含 10% 挑战激励）到合约
- [x] **joinChallenge**：EIP-2612 Permit + Relayer 代付 Gas，从挑战者钱包收取押金 + 0.01 USDC 服务费
- [x] **resolveChallenge**：根据 verdicts 数组分配赏金、押金和仲裁者报酬
- [x] **emergencyWithdraw**：30 天超时安全提取机制
- [x] **Permit try/catch**：兼容不支持 EIP-2612 的代币或签名被前运行的情况
- [x] **挑战激励**：无人挑战/挑战失败 → 激励 10% 退回平台；挑战成功 → 全额 90% 给挑战者
- [x] **仲裁者报酬**：所有挑战者押金的 30% 均分给仲裁者（含 upheld 的挑战者）
- [x] **Foundry 测试**：15 个测试覆盖全部场景（创建、加入、各类裁决、仲裁者分配、紧急提取）
- [x] **后端集成**：`app/services/escrow.py` 封装合约调用，`scheduler.py` quality_first 全程走合约结算
- [x] **余额校验 + 限速**：挑战前链上余额校验，每钱包每分钟限 1 次挑战（防空头支票 + 防 Gas 滥用）
- [x] **E2E 链上验证**：Base Sepolia 全流程测试通过（createChallenge → joinChallenge → resolveChallenge）
- [x] **合约地址**：`0x0b256635519Db6B13AE9c423d18a3c3A6e888b99`（Base Sepolia）

## V10: Claw Trust 信誉分机制

- [x] **TrustTier 四级体系**：S（≥900）/ A（≥600）/ B（≥300）/ C（<300），动态费率和权限
- [x] **对数加权算分**：`multiplier(n) = 1 + 4 × log10(1 + n/10)`，任务经验越多加分越多
- [x] **TrustService**：`apply_event()` 统一处理 worker_won / worker_consolation / worker_malicious / challenger_won / challenger_rejected / arbiter_reward / stake_slash 等事件
- [x] **TrustEvent 审计日志**：记录每次信誉分变化的 delta、前后分数、关联任务
- [x] **动态挑战押金率**：S 级 5% / A 级 10% / B 级 15% / C 级 20%
- [x] **动态平台手续费率**：S 级 12% / A 级 20% / B 级 25% / C 级 30%
- [x] **3 人陪审团**：`ArbiterPoolService` 从 S 级质押仲裁者中随机选 3 人，排除任务参与者
- [x] **仲裁者投票 API**：`POST /challenges/{cid}/votes`，支持多数裁决
- [x] **StakingService**：质押成为仲裁者（S 级 + GitHub 绑定）、质押换信誉分加成、Slash 机制
- [x] **Trust API**：`GET /users/{id}/trust`（信誉档案）、`GET /users/{id}/trust/events`（事件列表）、`GET /users/{id}/trust/quote`（费率报价）
- [x] **GitHub OAuth 绑定**：`POST /auth/github/callback`，首次绑定 +30 信誉分奖励
- [x] **权限管控**：C 级禁止提交，B 级赏金上限 50 USDC
- [x] **周榜**：`GET /leaderboard/weekly`，本周结算最多的 Top 3 用户各 +30 信誉分
- [x] **仲裁超时惩罚**：24h 未投票的仲裁者扣 10 信誉分
- [x] **少数派惩罚**：投票结果与多数不一致的仲裁者扣 15 信誉分
- [x] **UserOut schema 完善**：返回 trust_score / trust_tier / github_id / is_arbiter / staked_amount
