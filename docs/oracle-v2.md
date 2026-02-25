# Oracle V2 — LLM 驱动评分机制

**版本**: 1.0
**日期**: 2026-02-25

---

## 一、概述

Oracle V2 用 LLM（大语言模型）替代 V1 的随机评分 stub，实现了智能化的多阶段评分管道。支持 Anthropic Claude 和 OpenAI 兼容 API（如 SiliconFlow DeepSeek）两种 LLM 提供商。

### 核心设计原则

- **多阶段管道**：先验收筛选（Gate Check），再独立评分，最后横向对比，层层过滤
- **维度锁定**：任务创建时生成评分维度，整个生命周期内不可变，确保评估标准一致
- **分数隐藏**：`open` / `scoring` 阶段分数对 API 不可见，防止锚定效应
- **匿名评比**：横向对比时匿名化（Submission_A / B / C），防止 LLM 偏好
- **Token 追踪**：每次 LLM 调用记录 token 消耗，可通过内部 API 查询

---

## 二、架构

### 进程模型

```
FastAPI Server (app/services/oracle.py)
    │
    ├─ subprocess.run("python oracle/oracle.py", stdin=JSON, timeout=120s)
    │       │
    │       ├─ oracle.py 路由到 V2 模块或 V1 fallback
    │       │   ├─ dimension_gen.py → call_llm_json()
    │       │   ├─ gate_check.py → call_llm_json()
    │       │   ├─ score_individual.py → call_llm_json()
    │       │   ├─ constraint_check.py → call_llm_json()
    │       │   └─ dimension_score.py → call_llm_json()
    │       │
    │       └─ stdout: JSON (结果 + _token_usage)
    │
    └─ 服务层提取 _token_usage → 记入内存日志
```

每次 Oracle 调用启动一个独立 subprocess，JSON-in/JSON-out 协议，120 秒超时。进程间无状态共享。

### 文件结构

```
oracle/
├── oracle.py               # 入口：模式路由 + V1 fallback
├── llm_client.py           # LLM API 封装 + Token 累加器
├── dimension_gen.py         # 维度生成
├── gate_check.py            # 验收标准 Gate Check
├── constraint_check.py      # 约束检查（相关性 + 真实性）
├── score_individual.py      # 按维度独立评分
└── dimension_score.py       # 逐维度横向对比

app/services/oracle.py       # 服务层编排（调用 subprocess，管理日志）
app/scheduler.py             # Scheduler（quality_first 生命周期推进）
```

---

## 三、LLM Client

### 提供商配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ORACLE_LLM_PROVIDER` | `anthropic` | `anthropic` 或 `openai` |
| `ORACLE_LLM_MODEL` | `claude-sonnet-4-20250514` | 模型名称 |
| `ORACLE_LLM_BASE_URL` | (空) | OpenAI 兼容 API 基地址 |
| `ANTHROPIC_API_KEY` | — | Anthropic API 密钥 |
| `OPENAI_API_KEY` | — | OpenAI/兼容 API 密钥 |

### 核心函数

```python
call_llm(prompt: str, system: str = None) -> (str, dict)
# 返回 (响应文本, usage_dict)

call_llm_json(prompt: str, system: str = None) -> (dict, dict)
# 返回 (解析后的 JSON dict, usage_dict)
# 自动剥离 LLM 返回的 markdown 代码围栏
```

### Token 累加器

每次 subprocess 启动时重置，所有 `call_llm` 调用累加 token 用量：

```python
_accumulated_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

reset_accumulated_usage()       # subprocess 启动时调用
get_accumulated_usage() -> dict  # oracle.py main() 结束时读取
```

一次 Oracle 调用（如 `dimension_gen`）可能内部调用 `call_llm_json` 一次或多次，累加器确保总用量被完整记录。

---

## 四、评分管道

### 4.1 维度生成（dimension_gen）

**触发时机**：quality_first 任务创建时，由 `generate_dimensions()` 调用。

**输入**：
```json
{
  "mode": "dimension_gen",
  "task_title": "推荐5本科幻小说",
  "task_description": "推荐5本值得一读的科幻小说...",
  "acceptance_criteria": "1. 必须恰好推荐5本书\n2. 每本必须包含书名、作者..."
}
```

**输出**：
```json
{
  "dimensions": [
    {
      "id": "substantiveness",
      "name": "实质性",
      "type": "fixed",
      "description": "内容质量与实际价值",
      "weight": 0.3,
      "scoring_guidance": "评估推荐理由的深度..."
    },
    {
      "id": "completeness",
      "name": "完整性",
      "type": "fixed",
      "description": "覆盖度与完整性",
      "weight": 0.3,
      "scoring_guidance": "检查是否涵盖所有要求字段..."
    },
    {
      "id": "domain_accuracy",
      "name": "领域准确性",
      "type": "dynamic",
      "description": "推荐的科幻小说是否真实存在",
      "weight": 0.4,
      "scoring_guidance": "验证书名、作者、年份的真实性..."
    }
  ],
  "rationale": "基于任务要求生成了2个固定维度和1个动态维度..."
}
```

**规则**：
- 固定维度（2个）：`substantiveness`（实质性）、`completeness`（完整性），所有 quality_first 任务共享
- 动态维度（1-3个）：根据 task_description 和 acceptance_criteria 推导
- 维度总数：3-5 个
- 权重之和 = 1.0

**存储**：写入 `scoring_dimensions` 表，与 task 关联，之后不可修改。

---

### 4.2 Gate Check（验收检查）

**触发时机**：每次提交时，quality_first 和 fastest_first 均使用。

**输入**：
```json
{
  "mode": "gate_check",
  "task_description": "推荐5本值得一读的科幻小说...",
  "acceptance_criteria": "1. 必须恰好推荐5本书\n2. ...",
  "submission_payload": "1. 《三体》刘慈欣 2006年..."
}
```

**输出**：
```json
{
  "overall_passed": false,
  "criteria_checks": [
    {
      "criteria": "必须恰好推荐5本书",
      "passed": false,
      "evidence": "提交仅包含3本书，未达到5本的要求",
      "revision_hint": "请补充至恰好5本科幻小说"
    },
    {
      "criteria": "每本必须包含书名、作者、出版年份",
      "passed": true,
      "evidence": "已列出的3本均包含完整信息"
    }
  ],
  "summary": "提交未满足第1条标准：要求5本但仅提供3本"
}
```

**判定原则**：
- 量化标准（"至少50条"、"恰好5本"）：严格计数验证
- 模糊标准（"必须有数据支撑"）：合理推断，偏向宽松
- **一条不满足 = 整体不通过**
- 边界情况偏向通过（质量差异留给后续评分阶段处理）

**后续流程**：
- **quality_first**：失败 → `gate_failed`，worker 可修订重交；通过 → `gate_passed`，进入 Individual Scoring
- **fastest_first**：失败 → `score = 0.0`，`status = scored`；通过 → 继续 Constraint Check

---

### 4.3 Individual Scoring（独立评分）

**触发时机**：quality_first 提交通过 Gate Check 后。

**输入**：
```json
{
  "mode": "score_individual",
  "task_title": "推荐5本科幻小说",
  "task_description": "...",
  "dimensions": [
    {"id": "substantiveness", "name": "实质性", "description": "...", "weight": 0.3, "scoring_guidance": "..."},
    {"id": "completeness", "name": "完整性", "description": "...", "weight": 0.3, "scoring_guidance": "..."},
    {"id": "domain_accuracy", "name": "领域准确性", "description": "...", "weight": 0.4, "scoring_guidance": "..."}
  ],
  "submission_payload": "1. 《三体》刘慈欣 2006年 ..."
}
```

**输出**：
```json
{
  "dimension_scores": {
    "substantiveness": {"score": 85, "feedback": "推荐理由具有深度..."},
    "completeness": {"score": 92, "feedback": "所有必填字段完整..."},
    "domain_accuracy": {"score": 98, "feedback": "所有推荐的书籍均真实存在..."}
  },
  "revision_suggestions": [
    "推荐理由可以更突出每本书的独特价值",
    "考虑涵盖更多不同年代的科幻作品"
  ]
}
```

**评分尺度**（0-100）：
| 分段 | 含义 |
|------|------|
| 90-100 | 明显超出预期 |
| 70-89 | 良好执行，有亮点 |
| 50-69 | 基本满足，表现平庸 |
| 30-49 | 勉强相关，质量低 |
| 0-29 | 几乎无价值 |

**加权总分计算**：
```
weighted_total = Σ(score × weight) / 100
```

此阶段的分数**对 API 不可见**，仅用于：
1. 为 worker 提供修订建议
2. 在 batch scoring 阶段选取 top 3

---

### 4.4 Constraint Check（约束检查）

**触发时机**：
- fastest_first：Gate Check 通过后立即执行
- quality_first：batch_score 阶段，对 top 3 提交执行

**两个约束维度**：

| 约束 | 说明 | quality_first 失败 cap |
|------|------|----------------------|
| Task Relevance（任务相关性）| 提交内容是否真正回答了任务要求 | 30 |
| Authenticity（真实性）| 数据是否可信，有无捏造迹象 | 40 |

#### fastest_first 模式

**输入**：
```json
{
  "mode": "constraint_check",
  "task_type": "fastest_first",
  "task_description": "...",
  "acceptance_criteria": "...",
  "submission_payload": "..."
}
```

**输出**：
```json
{
  "task_relevance": {"passed": true, "reason": "内容与任务要求一致"},
  "authenticity": {"passed": true, "reason": "数据来源可信"},
  "overall_passed": true,
  "rejection_reason": null
}
```

判定宽松，仅拦截明显的垃圾/恶意提交。

#### quality_first 模式

**输入**（附加 submission_label 用于匿名化）：
```json
{
  "mode": "constraint_check",
  "task_type": "quality_first",
  "task_title": "...",
  "task_description": "...",
  "acceptance_criteria": "...",
  "submission_payload": "...",
  "submission_label": "Submission_A"
}
```

**输出**：
```json
{
  "submission_label": "Submission_A",
  "task_relevance": {
    "passed": true,
    "analysis": "提交内容完全聚焦于任务要求",
    "score_cap": null
  },
  "authenticity": {
    "passed": false,
    "analysis": "部分数据缺乏来源支撑",
    "flagged_issues": ["第3本书的出版年份无法验证"],
    "score_cap": 40
  },
  "effective_cap": 40
}
```

`effective_cap` = min(各约束的 score_cap)，传递给后续 Horizontal Scoring 阶段。

---

### 4.5 Horizontal Scoring（横向对比评分）

**触发时机**：quality_first 任务 deadline 后，batch_score 阶段，逐维度调用。

**流程**：
1. 从 gate_passed 提交中按 individual 加权分选取 top 3
2. 匿名化为 Submission_A / B / C
3. 对每个维度分别调用一次 `dimension_score`

**输入**：
```json
{
  "mode": "dimension_score",
  "task_title": "推荐5本科幻小说",
  "task_description": "...",
  "dimension": {
    "id": "substantiveness",
    "name": "实质性",
    "description": "...",
    "weight": 0.3,
    "scoring_guidance": "..."
  },
  "constraint_caps": {
    "Submission_A": null,
    "Submission_B": 40,
    "Submission_C": null
  },
  "submissions": [
    {"label": "Submission_A", "payload": "..."},
    {"label": "Submission_B", "payload": "..."},
    {"label": "Submission_C", "payload": "..."}
  ]
}
```

**输出**：
```json
{
  "dimension_id": "substantiveness",
  "dimension_name": "实质性",
  "evaluation_focus": "推荐理由的深度与独特性",
  "comparative_analysis": "A 的推荐理由最具深度...",
  "scores": [
    {
      "submission": "Submission_A",
      "raw_score": 90,
      "cap_applied": false,
      "final_score": 90,
      "evidence": "推荐理由详细且有独到见解"
    },
    {
      "submission": "Submission_B",
      "raw_score": 75,
      "cap_applied": true,
      "final_score": 40,
      "evidence": "推荐理由基本合格但受 cap 限制"
    },
    {
      "submission": "Submission_C",
      "raw_score": 60,
      "cap_applied": false,
      "final_score": 60,
      "evidence": "推荐理由较浅"
    }
  ]
}
```

**Cap 应用**：`final_score = min(raw_score, effective_cap)`。约束检查中标记问题的提交，即使 LLM 评分高也会被 cap 压低。

---

## 五、完整评分流程

### 5.1 fastest_first 流程

```
提交 → Gate Check → 失败: score=0.0, scored
                  → 通过: Constraint Check → 失败: score=0.0, scored
                                           → 通过: score=1.0, scored
                                                   若 score >= threshold → 关闭任务, 打款
```

Oracle 调用序列：`gate_check` → `constraint_check`（共 2 次 LLM 调用）

### 5.2 quality_first 流程

```
任务创建 → dimension_gen（生成评分维度，写入 DB）

提交 → Gate Check → 失败: gate_failed（可修订重交）
                  → 通过: gate_passed → Individual Scoring（按维度评分，分数隐藏）
                          返回修订建议给 worker

Deadline 到期 → Scheduler Phase 1: open → scoring

Scheduler Phase 2: scoring → batch scoring
    ├── 选取 top 3（按 individual 加权分）
    ├── 匿名化 Submission_A / B / C
    ├── 对 top 3 分别执行 Constraint Check → 收集 effective_cap
    ├── 对每个维度执行 Horizontal Scoring（带 cap）→ 收集 final_score
    ├── 计算加权总分 → 排名
    └── 存储评分结果，标记所有提交为 scored

Scheduler Phase 2 (next tick): scoring → challenge_window
    ├── 选出 winner（排名第1）
    └── ChallengeEscrow 锁定 90% 赏金
```

Oracle 调用序列（以 2 个 worker、3 个维度为例）：
1. `dimension_gen` × 1
2. `gate_check` × 2-4（每次提交/修订各 1 次）
3. `score_individual` × 2（gate_passed 的提交各 1 次）
4. `constraint_check` × 2（top 2，不足 3 个时按实际数量）
5. `dimension_score` × 3（每维度 1 次）

---

## 六、Scheduler 生命周期

`quality_first_lifecycle()` 由 APScheduler 每分钟执行一次，推进 quality_first 任务的状态转换。

### Phase 1: open → scoring

```python
# 查找所有 deadline 已过的 open 任务
expired_open = query(Task).filter(status=open, deadline <= now)
for task in expired_open:
    task.status = scoring  # 仅转状态，不做评分
```

### Phase 2: scoring → challenge_window

```python
for task in query(Task).filter(status=scoring):
    pending = count(Submission, status=pending)
    has_gated = count(Submission, status in [gate_passed, gate_failed]) > 0

    if pending > 0 and has_gated:
        continue  # V2 模式: 还有提交在后台处理 oracle，等待

    unscored = count(Submission, status in [pending, gate_passed])
    if unscored > 0:
        batch_score_submissions(task.id)  # 调用 batch scoring
        continue  # 下一个 tick 再检查

    # 所有提交已 scored，选 winner
    best = query(Submission).order_by(score.desc).first()
    if best:
        task.winner_submission_id = best.id
        task.challenge_window_end = now + challenge_duration
        task.status = challenge_window
        create_challenge_onchain(...)  # 锁定赏金到合约
    else:
        task.status = closed  # 无合格提交
```

**V1 兼容**：如果所有提交都是 `pending` 且没有 `gate_passed` / `gate_failed`（说明是 V1 模式），直接执行 batch_score（不等待）。

### Phase 3: challenge_window → closed / arbitrating

```python
for task in query(Task).filter(status=challenge_window, window_end <= now):
    challenges = count(Challenge, task_id=task.id)
    if challenges == 0:
        refund_all_deposits()
        resolve_challenge_onchain(verdicts=[])  # 释放赏金
        task.status = closed
    else:
        task.status = arbitrating
        run_arbitration(task.id)
```

### Phase 4: arbitrating → closed

```python
for task in query(Task).filter(status=arbitrating):
    pending = count(Challenge, status=pending)
    if pending > 0:
        continue  # 等待仲裁完成
    settle_after_arbitration(task)
    task.status = closed
```

### 典型时间线

```
T+0:00  任务创建，dimension_gen 生成维度
T+0:01  Worker A 提交 → gate_check（30s）→ gate_passed → score_individual（30s）
T+0:02  Worker A 看到修订建议，修订提交 → gate_check → score_individual
T+0:03  Worker B 提交 → gate_check → gate_passed → score_individual
T+5:00  Deadline 到期
T+6:00  Scheduler Tick 1: open → scoring
T+7:00  Scheduler Tick 2: batch_score（constraint_check × N + dimension_score × M）
T+8:00  Scheduler Tick 3: scoring → challenge_window（选 winner，锁赏金）
T+8:00+ Challenge Window（默认 2 小时）
```

---

## 七、服务层编排

### generate_dimensions(db, task)

任务创建后由 `POST /tasks` 路由在 BackgroundTasks 中调用。

```python
payload = {"mode": "dimension_gen", "task_title": ..., "task_description": ..., "acceptance_criteria": ...}
result = _call_oracle(payload)
for dim in result["dimensions"]:
    db.add(ScoringDimension(task_id=task.id, dim_id=dim["id"], name=dim["name"], ...))
```

### give_feedback(db, sub_id, task_id)

quality_first 提交后由 BackgroundTasks 调用。

```python
# Step 1: Gate Check
gate_result = _call_oracle({"mode": "gate_check", ...})
if not gate_result["overall_passed"]:
    submission.status = gate_failed
    submission.oracle_feedback = json.dumps({"type": "gate_check", **gate_result})
    return

# 立即提交 gate_passed（防止 score_individual 失败时状态卡在 pending）
submission.status = gate_passed
submission.oracle_feedback = json.dumps({"type": "gate_check", **gate_result})
db.commit()

# Step 2: Individual Scoring
dimensions = db.query(ScoringDimension).filter(task_id=task.id).all()
score_result = _call_oracle({"mode": "score_individual", "dimensions": [...], ...})
submission.oracle_feedback = json.dumps({"type": "individual_scoring", **score_result})
db.commit()
```

### batch_score_submissions(db, task_id)

Scheduler Phase 2 调用。

```python
# 1. 收集 gate_passed 提交，按 individual 加权分排序，取 top 3
gate_passed_subs = query(Submission, status=gate_passed)
ranked = sort_by_individual_weighted_total(gate_passed_subs)
top3 = ranked[:3]

# 2. 匿名化
labels = {sub.id: f"Submission_{chr(65+i)}" for i, sub in enumerate(top3)}

# 3. Constraint Check (每个提交 1 次)
caps = {}
for sub in top3:
    result = _call_oracle({"mode": "constraint_check", "task_type": "quality_first", ...})
    caps[labels[sub.id]] = result["effective_cap"]

# 4. Horizontal Scoring (每个维度 1 次)
dimensions = query(ScoringDimension, task_id=task_id)
all_scores = {}
for dim in dimensions:
    result = _call_oracle({"mode": "dimension_score", "dimension": dim, "constraint_caps": caps, ...})
    for entry in result["scores"]:
        all_scores[entry["submission"]][dim.dim_id] = entry["final_score"]

# 5. 计算加权总分 + 排名
for label, scores in all_scores.items():
    weighted_total = sum(scores[d.dim_id] * d.weight for d in dimensions) / 100
    # ... 排名

# 6. 写入评分结果
for sub in top3:
    sub.score = weighted_total
    sub.status = scored
    sub.oracle_feedback = json.dumps({"type": "scoring", "rank": rank, "dimension_scores": {...}, ...})
```

---

## 八、oracle_feedback JSON 格式

`submission.oracle_feedback` 字段根据评分阶段存储不同类型的 JSON：

### Gate Check 失败（gate_failed）

```json
{
  "type": "gate_check",
  "overall_passed": false,
  "criteria_checks": [
    {"criteria": "...", "passed": false, "evidence": "...", "revision_hint": "..."},
    {"criteria": "...", "passed": true, "evidence": "..."}
  ],
  "summary": "..."
}
```

### Individual Scoring（gate_passed，open 阶段）

```json
{
  "type": "individual_scoring",
  "dimension_scores": {
    "substantiveness": {"score": 85, "feedback": "..."},
    "completeness": {"score": 92, "feedback": "..."}
  },
  "revision_suggestions": ["建议1", "建议2"]
}
```

### Batch Scoring（scored，deadline 后）

```json
{
  "type": "scoring",
  "constraint_cap": null,
  "dimension_scores": {
    "substantiveness": {"raw_score": 90, "final_score": 90, "cap_applied": false, "evidence": "..."},
    "completeness": {"raw_score": 85, "final_score": 85, "cap_applied": false, "evidence": "..."}
  },
  "weighted_total": 0.875,
  "rank": 1
}
```

### fastest_first 通过

```json
{
  "type": "fastest_first_scored",
  "gate_check": {"overall_passed": true, "criteria_checks": [...]},
  "constraint_check": {"overall_passed": true, "task_relevance": {...}, "authenticity": {...}}
}
```

---

## 九、Token 用量追踪

### 记录机制

每次 `_call_oracle()` 调用后，从返回 JSON 中提取 `_token_usage` 字段，附上元数据后存入模块级内存列表：

```python
_oracle_logs: list[dict] = []  # 最多保留 200 条
```

### 日志条目结构

```json
{
  "timestamp": "2026-02-25T10:30:45Z",
  "mode": "gate_check",
  "task_id": "abc-123",
  "task_title": "推荐5本科幻小说",
  "submission_id": "sub-456",
  "worker_id": "worker-789",
  "model": "claude-sonnet-4-20250514",
  "prompt_tokens": 1234,
  "completion_tokens": 567,
  "total_tokens": 1801,
  "duration_ms": 3200
}
```

### API 端点

```
GET /internal/oracle-logs?task_count=5&limit=200
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `task_count` | 5 | 返回最近 N 个不同 task 的日志 |
| `limit` | 200 | 最大返回条数 |

返回时自动解析 `worker_id` 为 `worker_nickname`（查 User 表）。

### 前端 DevPanel

`/dev` 页面底部 Oracle Logs 面板：
- 5 秒自动轮询
- 按 task_id 分组展示
- 表格列：时间、模式、Task、Worker、Token 用量、耗时

---

## 十、V1 Fallback

当 V2 模块不可用时（如缺少 LLM API 密钥），`oracle.py` 退回 V1 行为：

| mode | V1 行为 |
|------|--------|
| `score` | 随机返回 0.5–1.0 分 |
| `feedback` | 从预设列表随机抽取 3 条建议 |

V1 模式下不使用 gate_check、constraint_check 等阶段。Scheduler Phase 2 的 V1 兼容逻辑：如果所有提交都是 `pending`（没有 `gate_passed` / `gate_failed`），说明是 V1 模式，直接执行 batch_score 不等待。
