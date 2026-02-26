# Arbiter 赏金分配与信誉分连贯率机制设计

> 日期: 2026-02-26
> 状态: 待实现

## 背景

当前仲裁系统存在两个问题：
1. **资金分配过于平均**：30% 押金由全部 3 名 arbiter 均分，无论投票是否站在多数方
2. **信誉分逐挑战结算**：每次挑战立即 +2/-15，在多挑战 Task 中可能导致刷分或瞬间暴毙
3. **1:1:1 僵局无特殊处理**：默认判定 rejected 但 arbiter 处理方式与正常共识相同

## 设计目标

- 资金分配区分多数派/少数派，激励 arbiter 认真投票
- 信誉分延迟到 Task 结束后按「连贯率」统一结算，防止刷分
- 1:1:1 僵局给予公平处理（仍发劳动报酬，不影响信誉）

## 核心规则

### 一、1:1:1 僵局处理（Status Quo 机制）

当 3 名 arbiter 投出 upheld×1 / rejected×1 / malicious×1：

- **结果定性**：判定为 **rejected**（维持原判，疑罪从无）
- **arbiter 标记**：3 人均标记为 **neutral**
- **资金**：30% 押金由 3 人均分（每人 10%）
- **信誉**：此局不计入连贯率计算

### 二、资金分配（逐挑战即时结算）

#### 共识成功（2:1 或 3:0）

| 角色 | coherence_status | 资金分配 |
|------|-----------------|----------|
| 多数派 arbiter | coherent | 平分 30% 押金 |
| 少数派 arbiter | incoherent | 0 |

#### 共识坍塌（1:1:1）

| 角色 | coherence_status | 资金分配 |
|------|-----------------|----------|
| 全部 arbiter | neutral | 均分 30% 押金（每人 10%） |

#### 智能合约层面

不修改 ChallengeEscrow 合约。后端调用 `resolveChallenge()` 时：
- **共识成功**：`arbiter_wallets` 只传入 coherent 的 arbiter 地址
- **共识坍塌**：`arbiter_wallets` 传入全部 3 个地址

合约内部仍按传入地址均分，但后端控制了「谁有资格参与分配」。

### 三、信誉分结算（Task 维度连贯率）

资金逐挑战即时发放，但**信誉分在 Task 结束后一次性结算**。

#### 计算步骤

1. **收集**：该 Task 所有 ArbiterVote，按 arbiter 分组
2. **剔除无效局**：排除 `coherence_status == "neutral"` 和超时未投票的记录
3. **计算连贯率**：`coherent_count / effective_count`
4. **阶梯判定**：

| 连贯率 | 信誉 delta | 说明 |
|--------|-----------|------|
| > 80% | +3 | 优秀，判断力极强 |
| > 60% 且 ≤ 80% | +2 | 良好，与共识吻合 |
| ≥ 40% 且 ≤ 60% | 0 | 勉强及格，不奖不罚 |
| > 0% 且 < 40% | -10 | 不合格，能力差或疑似作恶 |
| = 0% 且有效局 ≥ 2 | -30 | 极度危险，连续全错加倍严惩 |

#### 特殊情况

- **有效局 = 0**（全部是 neutral/超时）：不结算信誉分
- **超时未投票**：立即扣 -10（保留现有 `arbiter_timeout` 逻辑），该局从连贯率计算中剔除
- **只参与 1 局且 incoherent**：rate=0% 但 effective=1 < 2，走 `<40%` 分支 → -10（不触发 -30 的极端惩罚）

#### 实战举例

某 Task 有 4 个挑战，Arbiter-X 全部被抽中：

| 挑战 | 结果 | Arbiter-X | 资金 | coherence |
|------|------|----------|------|-----------|
| #1 | 2:1 共识 | 投了多数派 | 拿到 15% 押金 | coherent |
| #2 | 3:0 共识 | 投了多数派 | 拿到 10% 押金 | coherent |
| #3 | 1:1:1 僵局 | — | 拿到 10% 押金 | neutral（剔除） |
| #4 | 1:2 共识 | 投了少数派 | 0 | incoherent |

Task 结束时：有效局 = 3，coherent = 2，rate = 66.7% → delta = **+2**

## 数据模型变更

### ArbiterVote 新增字段

```python
coherence_status = Column(String, nullable=True)
# "coherent" | "incoherent" | "neutral" | None(未结算/超时)
```

### TrustEventType 新增枚举

```python
arbiter_coherence = "arbiter_coherence"  # Task 结束时按连贯率下发
```

旧的 `arbiter_majority` / `arbiter_minority` 枚举保留（兼容历史数据），但不再在新结算中使用。

### 不变的部分

- ChallengeEscrow 合约不改
- ChallengeVerdict 枚举不变（upheld / rejected / malicious）
- Challenge 模型不变
- User 模型不变

## 代码变更范围

### app/models.py
- `ArbiterVote` 新增 `coherence_status` 字段
- `TrustEventType` 新增 `arbiter_coherence`

### app/services/arbiter_pool.py
- `resolve_jury()`: 增加 1:1:1 检测，设置 `coherence_status`

### app/scheduler.py
- `_try_resolve_challenge_jury()`: 移除逐挑战的 `arbiter_majority/minority` 信誉分发放
- `_settle_after_arbitration()`: 末尾新增 `settle_arbiter_reputation()` 调用
- `_resolve_via_contract()`: arbiter_wallets 只收集 coherent + neutral

### app/services/trust.py
- `_FIXED_DELTAS` 新增 `arbiter_coherence` 映射（实际 delta 由调用方传入）
- 或改为 `apply_event()` 支持动态 delta

### Alembic 迁移
- 新增 `arbiter_votes.coherence_status` 列

## 测试用例

| 场景 | 验证点 |
|------|--------|
| 2:1 共识 | 多数派 coherent, 少数派 incoherent, 只传多数派钱包 |
| 3:0 共识 | 全员 coherent, 传 3 个钱包 |
| 1:1:1 僵局 | verdict=rejected, 全员 neutral, 传 3 个钱包 |
| 连贯率 > 80% | delta=+3 |
| 连贯率 60%-80% | delta=+2 |
| 连贯率 40%-60% | delta=0 |
| 连贯率 < 40% | delta=-10 |
| 连贯率 0% 且 ≥ 2 局 | delta=-30 |
| 超时不计入连贯率 | 超时局剔除，不影响 rate |
| 全部 neutral / 超时 | 不结算信誉分 |
| 多 upheld 场景 | 按 arbiter_score 选 winner，其余保持 upheld（现有逻辑不变） |
