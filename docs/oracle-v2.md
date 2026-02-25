# Oracle V2 — LLM 评分机制

## 概述

Oracle V2 用 LLM 替代 V1 随机评分，通过多阶段管道实现智能评分。

**设计要点**：
- 维度锁定 — 任务创建时生成评分维度，全程不可变
- 分数隐藏 — `open`/`scoring` 阶段分数对 API 不可见，防止锚定
- 匿名评比 — 横向对比时匿名化为 Submission_A/B/C
- Token 追踪 — 每次 LLM 调用记录 token 消耗

---

## 评分管道

Oracle 有 5 个评分模块，按任务类型组合使用：

| 模块 | 作用 | fastest_first | quality_first |
|------|------|:---:|:---:|
| **Gate Check** | 逐条检查 acceptance_criteria，pass/fail | ✓ | ✓ |
| **Constraint Check** | 检查任务相关性 + 内容真实性 | ✓ | ✓ |
| **Dimension Gen** | 生成 2 固定 + 1-3 动态评分维度 | — | ✓ |
| **Individual Scoring** | 按维度独立评分（0-100），返回修订建议 | — | ✓ |
| **Horizontal Scoring** | 逐维度横向对比 top 3 提交 | — | ✓ |

### fastest_first 流程

```
提交 → Gate Check ─ 失败 → score=0, 结束
                   └ 通过 → Constraint Check ─ 失败 → score=0, 结束
                                              └ 通过 → score=1, 达标即关闭任务
```

共 2 次 LLM 调用。

### quality_first 流程

```
任务创建 ─────────── Dimension Gen（生成评分维度）

提交 → Gate Check ─ 失败 → gate_failed（可修订重交）
                   └ 通过 → gate_passed → Individual Scoring（分数隐藏）
                            └ 返回修订建议

Deadline 到期 → Batch Scoring:
  1. 按 individual 加权分选 top 3
  2. Constraint Check × N（收集分数上限 cap）
  3. Horizontal Scoring × M 维度（带 cap 横向对比）
  4. 加权总分排名 → 选 winner → 进入挑战期
```

---

## 各模块详解

### 1. Dimension Gen（维度生成）

任务创建时调用一次，根据 `task_description` + `acceptance_criteria` 生成评分维度。

- **固定维度**（2 个）：实质性（substantiveness）、完整性（completeness）
- **动态维度**（1-3 个）：根据任务内容推导，如"领域准确性"、"信息质量"
- 权重之和 = 1.0，存入 `scoring_dimensions` 表后锁定

### 2. Gate Check（验收检查）

逐条验证 acceptance_criteria 是否满足，**一条不过 = 整体不过**。

- 量化标准严格验证（"恰好 5 本" → 数数量）
- 模糊标准偏向宽松（质量差异留给评分阶段）
- 失败时返回 `revision_hint` 告诉 worker 如何修改

### 3. Individual Scoring（独立评分）

quality_first gate_passed 后调用，按每个维度打 0-100 分：

| 分段 | 含义 |
|------|------|
| 90-100 | 超出预期 |
| 70-89 | 良好 |
| 50-69 | 平庸 |
| 30-49 | 低质 |
| 0-29 | 无价值 |

返回 2-3 条 `revision_suggestions` 供 worker 修订。分数此时**对 API 隐藏**，仅用于后续选 top 3。

### 4. Constraint Check（约束检查）

检查两个底线约束，quality_first 模式下失败会施加分数上限：

| 约束 | 检查内容 | 失败 cap |
|------|---------|---------|
| 任务相关性 | 内容是否真正回应任务要求 | 30 |
| 真实性 | 数据是否可信、有无捏造 | 40 |

fastest_first 模式仅做 pass/fail，不设 cap。

### 5. Horizontal Scoring（横向对比）

逐维度对 top 3 提交做横向对比评分：

1. 提交匿名化（Submission_A/B/C）
2. LLM 同时看到所有提交，打出 raw_score
3. 应用 cap：`final_score = min(raw_score, effective_cap)`
4. 全维度评完后计算 `weighted_total = Σ(final_score × weight)`
5. 按 weighted_total 排名

---

## Scheduler 生命周期

`quality_first_lifecycle()` 每分钟执行，分两个 Phase 推进：

| Phase | 转换 | 逻辑 |
|-------|------|------|
| 1 | open → scoring | Deadline 过期，仅转状态 |
| 2 | scoring → challenge_window | 等所有 oracle 处理完 → batch_score → 选 winner → 锁赏金 |
| 3 | challenge_window → closed/arbitrating | 窗口到期，有挑战则仲裁，无挑战则结算 |
| 4 | arbitrating → closed | 仲裁完毕，链上结算 |

Phase 2 关键逻辑：如果还有 `pending` 提交在后台跑 oracle（且已有 `gate_passed`/`gate_failed` 提交），会等待而非强行评分。

---

## oracle_feedback 格式

`submission.oracle_feedback` 存储 JSON，`type` 字段标识阶段：

| type | 阶段 | 关键字段 |
|------|------|---------|
| `gate_check` | Gate 失败 | `criteria_checks[].revision_hint` |
| `individual_scoring` | Gate 通过后 | `dimension_scores`, `revision_suggestions` |
| `scoring` | Batch 评分后 | `dimension_scores`, `weighted_total`, `rank` |
| `fastest_first_scored` | fastest_first | `gate_check`, `constraint_check` |

---

## Token 追踪

每次 oracle subprocess 返回 `_token_usage`（prompt/completion/total tokens），服务层记入内存日志（最多 200 条）。

**API**: `GET /internal/oracle-logs?task_count=5` — 返回最近 N 个任务的调用日志，含 mode、token 用量、耗时、worker 昵称。

**前端**: DevPanel `/dev` 底部 Oracle Logs 面板，5 秒轮询，按任务分组。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ORACLE_LLM_PROVIDER` | `anthropic` | `anthropic` 或 `openai`（兼容 SiliconFlow 等） |
| `ORACLE_LLM_MODEL` | `claude-sonnet-4-20250514` | 模型名称 |
| `ORACLE_LLM_BASE_URL` | — | OpenAI 兼容 API 基地址 |
| `ANTHROPIC_API_KEY` | — | Anthropic 密钥 |
| `OPENAI_API_KEY` | — | OpenAI/兼容 API 密钥 |
