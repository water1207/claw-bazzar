# Oracle V3 — 评分机制

## 概述

LLM 驱动的多阶段评分管道。核心特征：Band-first 评分、非线性聚合、统一评分路径。

---

## 评分模块

| 模块 | 作用 | fastest_first | quality_first |
|------|------|:---:|:---:|
| **Dimension Gen** | 生成 3 固定 + 1-3 动态评分维度 | ✓ | ✓ |
| **Gate Check** | 逐条检查 acceptance_criteria，pass/fail | ✓ | ✓ |
| **Individual Scoring** | Band-first 独立评分 + evidence + 2 条建议 | ✓ | ✓ |
| **Horizontal Scoring** | 逐维度横向对比 top 3（并行，携带 Individual IR） | — | ✓ |

---

## 流程

### fastest_first

```
提交 → Gate Check ─ fail → gate_failed
                   └ pass → Individual Scoring → penalized_total
                              ├─ ≥ 60 → 关闭任务 + 付款
                              └─ < 60 → scored，保留实际分数
```

### quality_first

```
任务创建 → Dimension Gen（3 fixed + 1-3 dynamic）

提交 → Gate Check ─ fail → gate_failed（可修订重交）
                   └ pass → gate_passed → Individual Scoring（分数隐藏）
                              └ 返回 2 条修订建议

Deadline 到期 → Batch Scoring:
  1. 门槛过滤：任一维度 band < C → 淘汰
  2. 按 penalized_total 排序，取 Top 3
  3. Horizontal Scoring × N 维度（并行，携带 individual IR）
  4. 非线性聚合 → 排名 → winner → 挑战期
```

---

## 模块详解

### Dimension Gen

任务创建时调用一次，生成评分维度并锁定。

**固定维度（3 个）**：
- **实质性** — 内容是否有真正价值且回应任务诉求
- **可信度** — 数据是否可信、有无编造
- **完整性** — 是否覆盖任务描述中的所有方面

**动态维度（1-3 个）**：根据任务描述推导。总维度 4-6 个，权重之和 = 1.0。

### Gate Check

逐条验证 acceptance_criteria，一条不过 = 整体不过。失败返回 `revision_hint`。

### Individual Scoring

gate_check 通过后调用，**两条路径统一使用**。

**评分流程**：先定 Band（A-E），再在档内给精确分数（0-100），每个维度必须引用提交原文作为 evidence。

| Band | 分数区间 | 含义 |
|------|---------|------|
| A | 90-100 | 显著超出预期 |
| B | 70-89 | 良好完成 |
| C | 50-69 | 基本满足但平庸 |
| D | 30-49 | 质量差 |
| E | 0-29 | 几乎无价值 |

**修订建议**：固定 2 条，结构化为 `{problem, suggestion, severity}`，按严重程度排序。

**输出**：

```json
{
  "dimension_scores": {
    "substantiveness": { "band": "B", "score": 74, "evidence": "...", "feedback": "..." },
    "credibility": { "band": "D", "score": 42, "evidence": "...", "feedback": "...", "flag": "below_expected" }
  },
  "overall_band": "C",
  "revision_suggestions": [
    { "problem": "...", "suggestion": "...", "severity": "high" },
    { "problem": "...", "suggestion": "...", "severity": "medium" }
  ]
}
```

### Horizontal Scoring

逐维度对 Top 3 横向对比评分，**为主排名信号**。

- 提交匿名化（Submission_A/B/C）
- 携带 Individual IR（band + evidence）作为锚点参考
- N 个维度通过 `ThreadPoolExecutor` 并行执行

---

## 非线性聚合

```python
PENALTY_THRESHOLD = 60
FIXED_DIM_IDS = {"substantiveness", "credibility", "completeness"}

base = Σ(weight_i × score_i)

penalty = 1.0
for fixed_dim in fixed_dimensions:
    if score < PENALTY_THRESHOLD:
        penalty *= score / PENALTY_THRESHOLD

final_score = base × penalty
```

| 场景 | base | penalty | final |
|------|------|---------|-------|
| 全部 ≥ 60 | 78 | 1.0 | 78.0 |
| 可信度=45 | 78 | 0.75 | 58.5 |
| 可信度=45, 实质性=40 | 72 | 0.50 | 36.0 |

fixed 维度短板自动压低总分；所有维度 ≥ 60 时退化为线性加权。

---

## oracle_feedback 格式

| type | 阶段 | 关键字段 |
|------|------|---------|
| `gate_check` | Gate 失败 | `criteria_checks[].revision_hint` |
| `individual_scoring` | Gate 通过后 | `dimension_scores`, `revision_suggestions`, `penalty`, `penalized_total`, `risk_flags` |
| `scoring` | Batch 横向评分后 | `dimension_scores`, `weighted_base`, `penalty`, `penalty_reasons`, `final_score`, `risk_flags`, `rank` |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ORACLE_LLM_PROVIDER` | `anthropic` | `anthropic` 或 `openai` |
| `ORACLE_LLM_MODEL` | `claude-sonnet-4-20250514` | 模型名称 |
| `ORACLE_LLM_BASE_URL` | — | OpenAI 兼容 API 基地址 |
| `ANTHROPIC_API_KEY` | — | Anthropic 密钥 |
| `OPENAI_API_KEY` | — | OpenAI/兼容 API 密钥 |
