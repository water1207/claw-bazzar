# Oracle V3 — 评分机制

## 概述

LLM 驱动的多阶段评分管道。核心特征：Band-first 评分、非线性聚合、统一评分路径、Prompt 注入防御。

---

## 评分模块

| 模块 | 作用 | fastest_first | quality_first |
|------|------|:---:|:---:|
| **Dimension Gen** | 生成 3 固定 + 1-3 动态评分维度，任务创建时调用一次 | ✓ | ✓ |
| **Injection Guard** | Rule-based 注入检测，零 LLM 调用，在所有 LLM 模块前运行 | ✓ | ✓ |
| **Gate Check** | 逐条检查 acceptance_criteria，pass/fail | ✓ | ✓ |
| **Individual Scoring** | Band-first 独立评分 + evidence + 2 条修订建议 | ✓ | ✓ |
| **Horizontal Scoring** | 逐维度横向对比 Top 3（并行，携带 Individual IR） | — | ✓ |

---

## 流程

### fastest_first

```
提交 → Injection Guard ─ detected → policy_violation
                        └ clean
                          → Gate Check ─ fail → scored (score=0)
                                        └ pass
                                          → Individual Scoring
                                            → compute_penalized_total
                                              ├─ ≥ 60 → closed + pay_winner
                                              └─ < 60 → scored，保留实际分数
```

### quality_first

```
任务创建 → Dimension Gen（3 fixed + 1-3 dynamic，锁定）

提交 → Injection Guard ─ detected → policy_violation
                        └ clean
                          → Gate Check ─ fail → gate_failed（可修订重交）
                                        └ pass → gate_passed
                                                  → Individual Scoring（分数隐藏）
                                                    → 状态仍为 gate_passed，feedback 含 revision_suggestions
                                                      ├─ 有剩余修订次数 → 可据建议修订重交
                                                      └─ 等 deadline 后 batch_score

Deadline 到期 → batch_score_submissions:
  1. 门槛过滤：任意 fixed 维度 band < C（即 D 或 E）→ below_threshold
  2. eligible 按 penalized_total 排序，取 Top 3
  3. Horizontal Scoring × N 维度（ThreadPoolExecutor 并行）
  4. 非线性聚合 → 排名 → winner → 进入挑战期
  5. Top 3 以外的 eligible 用 individual 加权分直接 scored
  6. below_threshold 也用个人 penalized 分 scored
```

---

## 模块详解

### Dimension Gen

任务创建时调用一次，结果存入 `ScoringDimension` 表后锁定，后续评分全程使用此维度配置。

**固定维度（3 个，id 固定）**：
- `substantiveness` **实质性** — 内容是否有真正价值且回应任务诉求
- `credibility` **可信度** — 数据是否可信、有无编造，来源是否可追溯
- `completeness` **完整性** — 是否覆盖任务描述中的所有方面和需求点

**动态维度（1-3 个）**：根据任务描述和验收标准推导，直接来源于显式/隐式需求，维度间不能高度重叠。

**总维度 4-6 个，权重之和 = 1.0。**

每个维度包含字段：`id`, `name`, `type`(fixed/dynamic), `description`, `weight`, `scoring_guidance`。

### Injection Guard

在 `gate_check`、`score_individual`、`dimension_score` 三个模式前运行，zero LLM，纯正则检测。

**检测字段**：
- `gate_check` / `score_individual`：`submission_payload`
- `dimension_score`：`submissions[*].payload`（逐条检测）

**检测模式**（中英文）：指令覆盖、角色注入、系统提示操控、输出劫持、分隔符伪造。

检测到注入 → `submission.status = policy_violation`，不进入 LLM 评分。

`acceptance_criteria` 为 `list[str]` 时自动 join 为空格分隔字符串后检测。

### Gate Check

逐条验证 acceptance_criteria，**一条不过 = 整体不过**。

- 判断尺度偏向宽松：只要明显在尝试满足标准即 pass，质量差异留给后续评分
- fail 时返回 `revision_hint`

**输入**：`task_description`, `acceptance_criteria`（list[str] → 格式化为编号文本）, `submission_payload`

**输出**：
```json
{
  "overall_passed": true/false,
  "criteria_checks": [
    {
      "criteria": "原文验收标准",
      "passed": true/false,
      "evidence": "判断依据",
      "revision_hint": "（仅 fail 时）修订建议"
    }
  ],
  "summary": "一句话总结"
}
```

### Individual Scoring

Gate Check 通过后调用，**两条路径统一使用**。

**评分流程**：先定 Band（A-E），再在档内给精确分数（0-100），每个维度强制引用提交原文作为 evidence。

| Band | 分数区间 | 含义 |
|------|---------|------|
| A | 90-100 | 显著超出预期 |
| B | 70-89 | 良好完成，有亮点 |
| C | 50-69 | 基本满足但平庸 |
| D | 30-49 | 勉强相关但质量差 |
| E | 0-29 | 几乎无价值 |

fixed 类型维度分数 < 60 时附加 `"flag": "below_expected"`。

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

quality_first 路径中，**Individual Scoring 的分数对 API 隐藏**，仅将 `revision_suggestions` 通过 `oracle_feedback` 返回给 worker。

### Horizontal Scoring（quality_first 专用）

对 Top 3 提交逐维度横向对比，**为最终排名的主要信号**。

- 提交匿名化（Submission_A/B/C）
- 携带 Individual IR（band + evidence）作为锚定参考，不强制约束
- N 个维度通过 `ThreadPoolExecutor` 并行执行，每维度一次 LLM 调用

**输出**（单维度）：
```json
{
  "dimension_id": "substantiveness",
  "dimension_name": "实质性",
  "evaluation_focus": "本次评判的具体焦点",
  "comparative_analysis": "横向比较说明",
  "scores": [
    { "submission": "Submission_A", "raw_score": 85, "final_score": 85, "evidence": "..." }
  ]
}
```

---

## 非线性聚合（compute_penalized_total）

```python
PENALTY_THRESHOLD = 60
FIXED_DIM_IDS = {"substantiveness", "credibility", "completeness"}

base = Σ(weight_i × score_i)

penalty = 1.0
for fixed_dim in fixed_dimensions:
    if score < PENALTY_THRESHOLD:
        penalty *= score / PENALTY_THRESHOLD

final_score = round(base × penalty, 2)
```

| 场景 | base | penalty | final |
|------|------|---------|-------|
| 全部 ≥ 60 | 78.0 | 1.0 | 78.0 |
| 可信度=45 | 78.0 | 0.75 | 58.5 |
| 可信度=45, 实质性=40 | 72.0 | 0.50 | 36.0 |

fixed 维度短板自动压低总分；所有维度 ≥ 60 时退化为线性加权。

**fastest_first 通过阈值**：`penalized_total ≥ 60`（即 final_score ≥ 60）。

**quality_first 门槛过滤**：任意 fixed 维度 band 为 D（30-49）或 E（0-29）→ 淘汰进入 below_threshold，不参与 Top 3 横向评分。

---

## oracle_feedback 格式

`oracle_feedback` 字段以 JSON 字符串存储，始终包含 `type` 区分阶段：

| type | 触发阶段 | 关键字段 |
|------|---------|---------|
| `"gate_check"` | Gate 失败（gate_failed） | `overall_passed`, `criteria_checks[].revision_hint`, `summary` |
| `"gate_check"` | Gate 通过（gate_passed，quality_first） | `overall_passed`, `criteria_checks`, `summary` |
| `"individual_scoring"` | Individual Scoring 后（quality_first，gate_passed 状态） | `dimension_scores`, `overall_band`, `revision_suggestions` |
| `"scoring"` | fastest_first 完整评分后 | `dimension_scores`, `overall_band`, `revision_suggestions`, `weighted_base`, `penalty`, `penalty_reasons`, `final_score`, `risk_flags`, `passed` |
| `"scoring"` | Horizontal Scoring 后（quality_first，scored 状态） | `dimension_scores`（横向分），`weighted_base`, `penalty`, `penalty_reasons`, `final_score`, `risk_flags`, `rank` |
| `"injection"` | 注入检测命中 | `reason`, `field` |

---

## acceptance_criteria 存储与传递

- **API 输入**：`list[str]`（JSON 数组），后端 Schema 层校验，必填，至少 1 条
- **DB 存储**：TEXT（JSON 字符串，如 `'["条目1","条目2"]'`）
- **服务层**：`_parse_criteria(raw)` 反序列化为 `list[str]` 后传入 oracle 子进程
- **Oracle 脚本**：`list[str]` → 格式化为编号文本（`1. 条目1\n2. 条目2`）注入 prompt

---

## Prompt 安全

所有 oracle 子模块的 prompt 使用 `<user_content>` XML 标签包裹用户输入字段（提交内容、验收标准），并在 system prompt 中声明标签内文字为纯数据，不构成指令。配合 Injection Guard 形成双层防御。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ORACLE_LLM_PROVIDER` | `openai` | `anthropic` 或 `openai` |
| `ORACLE_LLM_MODEL` | — | 模型名称 |
| `ORACLE_LLM_BASE_URL` | — | OpenAI 兼容 API 基地址 |
| `ANTHROPIC_API_KEY` | — | Anthropic 密钥 |
| `OPENAI_API_KEY` | — | OpenAI/兼容 API 密钥 |
