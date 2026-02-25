# Oracle V2 评分 Pipeline 设计文档

> 日期: 2026-02-25
> 状态: 已批准
> 范围: 核心评分（维度系统 + Gate Check + 底层约束 + 逐维度评分），不含稳定性校验和 LLM Arbiter

---

## 1. 概述

将现有 Oracle V1 Stub（随机分数 0.5-1.0）升级为基于 LLM 的真实评分系统，覆盖 fastest_first 和 quality_first 两种任务模式。

### 核心变化

| 维度 | V1 (Stub) | V2 (LLM) |
|------|-----------|-----------|
| 评分方式 | 随机 0.5-1.0 | LLM 逐维度评分 |
| 维度系统 | 无 | 任务创建时 LLM 生成并锁定 |
| Gate Check | 无 | LLM 验收标准逐条校验 |
| 底层约束 | 无 | LLM 检查任务契合度 + 真实性 |
| 提交反馈 | 3 条随机建议 | Gate Check 结果 + 修订建议 |
| 横向比较 | 无 | deadline 后前三名横向评分 |

### 不在此次范围

- 稳定性校验（3 轮评分取中位数）
- LLM Arbiter（保持现有 stub）
- 奖励分配模式扩展（保持 winner_take_all）

---

## 2. 数据模型变更

### 2.1 Task 模型新增字段

```python
acceptance_criteria = Column(Text, nullable=True)  # 验收标准（发布者填写）
```

### 2.2 新建 ScoringDimension 表

```python
class ScoringDimension(Base):
    __tablename__ = "scoring_dimensions"

    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    dim_id = Column(String, nullable=False)       # "substantiveness", "completeness", "dynamic_dim_1"
    name = Column(String, nullable=False)          # "实质性", "完整性", "数据精度"
    dim_type = Column(String, nullable=False)      # "fixed" | "dynamic"
    description = Column(Text, nullable=False)     # 维度描述（对提交者公开）
    weight = Column(Float, nullable=False)         # 权重，所有维度求和=1（不公开）
    scoring_guidance = Column(Text, nullable=False) # 评分指引（不公开）

    task = relationship("Task", backref="dimensions")
```

### 2.3 Submission.oracle_feedback JSON 结构

**Gate Check 未通过时：**
```json
{
  "type": "gate_check",
  "overall_passed": false,
  "criteria_checks": [
    { "criteria": "至少覆盖10个产品", "passed": false, "hint": "当前仅覆盖8个" }
  ],
  "summary": "未通过验收，请修订后重新提交"
}
```

**Gate Check 通过 — 独立打分（quality_first，分数不公开）：**
```json
{
  "type": "individual_scoring",
  "dimension_scores": {
    "substantiveness": { "score": 72, "feedback": "内容较充实但缺少..." },
    "completeness": { "score": 65, "feedback": "覆盖了大部分需求但..." }
  },
  "revision_suggestions": ["建议1: ...", "建议2: ..."]
}
```

**横向评分完成后（quality_first，覆盖上面的内容）：**
```json
{
  "type": "scoring",
  "constraint_cap": null,
  "dimension_scores": {
    "substantiveness": { "raw_score": 85, "final_score": 85, "evidence": "..." },
    "completeness": { "raw_score": 78, "final_score": 78, "evidence": "..." }
  },
  "weighted_total": 85.6,
  "rank": 1
}
```

**fastest_first 检查结果：**
```json
{
  "type": "fastest_first_check",
  "gate_check": { "overall_passed": true, "criteria_checks": [...] },
  "constraint_check": { "overall_passed": true, "task_relevance": {...}, "authenticity": {...} },
  "passed": true
}
```

### 2.4 Submission status 新增值

- `gate_passed`：通过 Gate Check，等待评分（quality_first 专用）
- `gate_failed`：未通过 Gate Check，可修订重提（quality_first 专用）

---

## 3. Oracle 脚本架构

### 3.1 文件结构

```
oracle/
├── oracle.py            → 路由入口，按 mode 分发到子模块
├── llm_client.py        → LLM API 封装（默认 Anthropic，可配置）
├── dimension_gen.py     → mode="dimension_gen"：维度生成
├── gate_check.py        → mode="gate_check"：格式预检 + 验收校验
├── constraint_check.py  → mode="constraint_check"：底层约束检查
├── score_individual.py  → mode="score_individual"：单提交独立打分
├── dimension_score.py   → mode="dimension_score"：逐维度横向评分
└── arbiter.py           → 保持现有 stub
```

### 3.2 入口 oracle.py

stdin 读 JSON → 根据 `mode` 分发到对应子模块 → stdout 输出 JSON。

```python
def main():
    input_data = json.loads(sys.stdin.read())
    mode = input_data["mode"]

    handlers = {
        "dimension_gen": dimension_gen.run,
        "gate_check": gate_check.run,
        "constraint_check": constraint_check.run,
        "score_individual": score_individual.run,
        "dimension_score": dimension_score.run,
    }

    if mode not in handlers:
        # 兜底：保持现有 feedback/score stub 行为
        result = legacy_handler(input_data)
    else:
        result = handlers[mode](input_data)

    print(json.dumps(result))
```

### 3.3 llm_client.py

```python
def call_llm(prompt: str, system: str = None) -> str:
    provider = os.environ.get("ORACLE_LLM_PROVIDER", "anthropic")
    model = os.environ.get("ORACLE_LLM_MODEL", "claude-sonnet-4-20250514")

    if provider == "anthropic":
        client = anthropic.Anthropic()  # 从 ANTHROPIC_API_KEY 读取
        resp = client.messages.create(
            model=model, max_tokens=4096,
            system=system or "",
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.content[0].text
    else:
        raise ValueError(f"Unsupported provider: {provider}")
```

### 3.4 各模块输入/输出

| mode | 输入 | 输出 |
|------|------|------|
| `dimension_gen` | task_title, task_description, acceptance_criteria | `{dimensions: [...], rationale}` |
| `gate_check` | task_description, acceptance_criteria, submission_payload | `{overall_passed, criteria_checks: [...], summary}` |
| `score_individual` | task_title, task_description, dimensions, submission_payload | `{dimension_scores: {...}, revision_suggestions: [...]}` |
| `constraint_check` | task_type, task_title, task_description, acceptance_criteria, submission_payload, submission_label | fastest_first: `{overall_passed, task_relevance, authenticity}` / quality_first: `{effective_cap, task_relevance, authenticity}` |
| `dimension_score` | task_title, task_description, dimension, constraint_caps, submissions[] | `{dimension_id, scores: [{submission, raw_score, final_score, evidence}]}` |

### 3.5 新增环境变量

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `ORACLE_LLM_PROVIDER` | `anthropic` | LLM 提供商 |
| `ORACLE_LLM_MODEL` | `claude-sonnet-4-20250514` | 模型名 |
| `ANTHROPIC_API_KEY` | (无) | Anthropic API Key |

---

## 4. 服务层编排流程

### 4.1 任务创建（两种模式共享）

```
POST /tasks
  → 创建 Task（含 acceptance_criteria）
  → invoke_oracle(mode="dimension_gen")
  → 存入 ScoringDimension 表
  → 返回任务 + scoring_dimensions
```

### 4.2 fastest_first 提交流程

```
POST /tasks/{id}/submit
  → 格式预检（程序化）
  → invoke_oracle(mode="gate_check")
  → invoke_oracle(mode="constraint_check", task_type="fastest_first")
  ├── 全部 pass → status="accepted" → close task → payout
  └── 任一 fail → status="rejected"，oracle_feedback=失败原因
```

### 4.3 quality_first 提交流程（open 阶段）

```
POST /tasks/{id}/submit
  → 格式预检（程序化）
  → invoke_oracle(mode="gate_check")
  ├── fail → status="gate_failed"，oracle_feedback=失败详情+修订建议
  └── pass → invoke_oracle(mode="score_individual")
           → status="gate_passed"
           → oracle_feedback={individual_scoring + revision_suggestions}（分数 API 不公开）
           → 返回修订建议给提交者
```

### 4.4 quality_first 评分流程（deadline 后）

```
scheduler → batch_score_submissions(task)
  1. 收集所有 gate_passed 的 submission
  2. 按独立打分的 weighted_total 选出前三名
  3. 匿名化前三名
  4. 逐提交约束检查 (constraint_check, 3次LLM)
  5. 逐维度横向评分 (dimension_score, D次LLM)
  6. 汇总排名（纯计算）
  7. 写回最终分数到 oracle_feedback
  8. 选出 winner → task.status = "challenge_window"
```

### 4.5 Submission status 流转

**fastest_first:**
```
pending → accepted / rejected
```

**quality_first:**
```
pending → gate_passed / gate_failed → scored (评分完成后)
```

---

## 5. API 变更

### 5.1 POST /tasks — 创建任务

请求体新增可选字段：
```json
{ "acceptance_criteria": "string (可选)" }
```

响应新增：
```json
{
  "acceptance_criteria": "...",
  "scoring_dimensions": [
    { "name": "实质性", "description": "..." },
    { "name": "完整性", "description": "..." }
  ]
}
```

### 5.2 GET /tasks/{id} — 任务详情

响应新增 `acceptance_criteria` 和 `scoring_dimensions` 字段。

### 5.3 POST /tasks/{id}/submit — 提交

**quality_first 响应变更：**
- gate fail: `{gate_passed: false, message: "...", criteria_results: [...]}`
- gate pass: `{gate_passed: true, revision_suggestions: ["建议1", ...]}`

**fastest_first 响应变更：**
- pass: 直接 accepted（现有行为）
- fail: `{passed: false, rejection_reason: "..."}`

### 5.4 Schemas 新增

```python
class ScoringDimensionPublic(BaseModel):
    name: str
    description: str

class GateCheckResponse(BaseModel):
    gate_passed: bool
    message: str
    criteria_results: list[dict] | None = None
    revision_suggestions: list[str] | None = None
```

---

## 6. 前端影响

- 创建任务表单：新增 `acceptance_criteria` 输入框
- 任务详情页：显示评分维度列表（名称+描述）
- 提交反馈：显示 Gate Check 结果 + 修订建议（替代现有随机建议）
- 评分结果：显示维度细分分数（适配新 JSON 结构）

---

## 7. 测试策略

### Mock 方式

在 subprocess 调用层 mock（与现有模式一致）：

```python
def mock_dimension_gen():
    return mock_subprocess_result({
        "dimensions": [
            {"id": "substantiveness", "name": "实质性", "type": "fixed",
             "description": "...", "weight": 0.3, "scoring_guidance": "..."},
            {"id": "completeness", "name": "完整性", "type": "fixed",
             "description": "...", "weight": 0.3, "scoring_guidance": "..."},
            {"id": "data_precision", "name": "数据精度", "type": "dynamic",
             "description": "...", "weight": 0.4, "scoring_guidance": "..."}
        ],
        "rationale": "测试用"
    })
```

### 新增测试覆盖

- 维度生成：创建任务后 ScoringDimension 表有记录
- Gate Check：pass/fail 两条路径
- 独立打分：score_individual 返回分数+建议
- 横向评分：多提交排名正确性
- 约束上限：constraint_cap 压制分数
- 完整流程：fastest_first / quality_first 端到端

---

## 8. 错误处理

| 场景 | 处理 |
|------|------|
| LLM API 超时/失败 | 重试 1 次，仍失败则返回 500 |
| LLM 返回非法 JSON | 记录日志，返回 500 |
| 维度生成失败 | 任务创建失败（事务回滚） |
| Gate Check LLM 失败 | 提交失败，提示重试 |
| 评分阶段 LLM 失败 | 标记 task 为 scoring_failed |
| 无 API Key | oracle.py 启动时检查报错 |
