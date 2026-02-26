# Oracle 评分系统优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 重构 Oracle 评分管线——消除短板/长板效应、统一两条路径评分机制、删除 constraint_check、提升可解释性、并行化 dimension_score。

**Architecture:** 升级 score_individual 为 band-first + evidence 结构化输出（IR），新增"可信度"为第 3 个 fixed 维度吸收 constraint_check 职责，使用 penalized_total（非线性聚合）替代线性加权求和，fastest_first 改用 score_individual + penalized_total 阈值判断替代二元 constraint_check，dimension_score 并行化降低耗时。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Anthropic Claude SDK, ThreadPoolExecutor, pytest

**Design Doc:** `docs/plans/2026-02-27-oracle-scoring-optimization-design.md`

---

## Task 1: Thread-safe oracle logs

**Files:**
- Modify: `app/services/oracle.py:16-17` (add lock), `app/services/oracle.py:38-57` (use lock in _call_oracle)
- Test: `tests/test_oracle_logs_threadsafe.py`

**Step 1: Write the failing test**

```python
# tests/test_oracle_logs_threadsafe.py
"""Test thread-safety of oracle log writes."""
import threading
from app.services.oracle import _oracle_logs, _oracle_logs_lock, MAX_LOGS


def test_oracle_logs_lock_exists():
    """Verify the lock object exists and is a threading.Lock."""
    assert isinstance(_oracle_logs_lock, type(threading.Lock()))


def test_concurrent_log_writes_no_corruption():
    """Multiple threads appending to _oracle_logs should not corrupt the list."""
    import time
    from app.services.oracle import _oracle_logs, _oracle_logs_lock

    original = list(_oracle_logs)
    errors = []

    def writer(thread_id):
        try:
            for i in range(50):
                with _oracle_logs_lock:
                    _oracle_logs.append({"thread": thread_id, "i": i})
                    if len(_oracle_logs) > MAX_LOGS:
                        _oracle_logs[:] = _oracle_logs[-MAX_LOGS:]
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    # Cleanup
    _oracle_logs[:] = original
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_logs_threadsafe.py -v`
Expected: FAIL with `ImportError: cannot import name '_oracle_logs_lock'`

**Step 3: Write minimal implementation**

In `app/services/oracle.py`, add the lock after `_oracle_logs` and `MAX_LOGS`:

```python
import threading

_oracle_logs: list[dict] = []
MAX_LOGS = 200
_oracle_logs_lock = threading.Lock()
```

And update `_call_oracle` to use the lock when appending:

```python
    # In _call_oracle, replace the bare append block:
    if token_usage:
        # ... build log_entry ...
        with _oracle_logs_lock:
            _oracle_logs.append(log_entry)
            if len(_oracle_logs) > MAX_LOGS:
                _oracle_logs[:] = _oracle_logs[-MAX_LOGS:]
```

Also update `get_oracle_logs` to use the lock:

```python
def get_oracle_logs(limit: int = 50) -> list[dict]:
    with _oracle_logs_lock:
        return list(reversed(_oracle_logs))[:limit]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_logs_threadsafe.py -v`
Expected: PASS

**Step 5: Run existing tests to verify no regression**

Run: `pytest tests/test_oracle_service.py tests/test_oracle_v2_service.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_logs_threadsafe.py
git commit -m "feat(oracle): thread-safe oracle logs with _oracle_logs_lock"
```

---

## Task 2: penalized_total helper function

**Files:**
- Modify: `app/services/oracle.py` (add helper)
- Test: `tests/test_penalized_total.py`

**Step 1: Write the failing test**

```python
# tests/test_penalized_total.py
"""Tests for penalized_total scoring formula."""
from app.services.oracle import compute_penalized_total

THRESHOLD = 60


def test_all_above_threshold():
    """All fixed dims >= 60 → penalty = 1.0, final = base."""
    dim_scores = {
        "substantiveness": {"score": 80, "band": "B"},
        "credibility": {"score": 70, "band": "B"},
        "completeness": {"score": 75, "band": "B"},
        "tech_depth": {"score": 90, "band": "A"},
    }
    dims = [
        {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "tech_depth", "dim_type": "dynamic", "weight": 0.25},
    ]
    result = compute_penalized_total(dim_scores, dims)
    assert result["penalty"] == 1.0
    assert result["weighted_base"] == (80 + 70 + 75 + 90) * 0.25
    assert result["final_score"] == result["weighted_base"]
    assert result["penalty_reasons"] == []
    assert result["risk_flags"] == []


def test_one_fixed_below_threshold():
    """credibility=45 → penalty = 45/60 = 0.75."""
    dim_scores = {
        "substantiveness": {"score": 80, "band": "B"},
        "credibility": {"score": 45, "band": "D", "flag": "below_expected"},
        "completeness": {"score": 75, "band": "B"},
    }
    dims = [
        {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.4},
        {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.3},
        {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.3},
    ]
    result = compute_penalized_total(dim_scores, dims)
    base = 80 * 0.4 + 45 * 0.3 + 75 * 0.3
    assert result["weighted_base"] == base
    assert result["penalty"] == 45 / 60
    assert abs(result["final_score"] - base * (45 / 60)) < 0.01
    assert len(result["penalty_reasons"]) == 1
    assert "可信度" in result["penalty_reasons"][0] or "credibility" in result["penalty_reasons"][0]
    assert len(result["risk_flags"]) == 1


def test_two_fixed_below_threshold():
    """credibility=45, substantiveness=40 → penalty = (45/60)*(40/60) = 0.5."""
    dim_scores = {
        "substantiveness": {"score": 40, "band": "D"},
        "credibility": {"score": 45, "band": "D"},
        "completeness": {"score": 75, "band": "B"},
    }
    dims = [
        {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.33},
        {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.33},
        {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.34},
    ]
    result = compute_penalized_total(dim_scores, dims)
    expected_penalty = (40 / 60) * (45 / 60)
    assert abs(result["penalty"] - expected_penalty) < 0.01
    assert len(result["penalty_reasons"]) == 2
    assert len(result["risk_flags"]) == 2


def test_dynamic_dim_below_threshold_no_penalty():
    """Dynamic dims below threshold do NOT trigger penalty."""
    dim_scores = {
        "substantiveness": {"score": 80, "band": "B"},
        "credibility": {"score": 70, "band": "B"},
        "completeness": {"score": 75, "band": "B"},
        "tech_depth": {"score": 30, "band": "D"},
    }
    dims = [
        {"dim_id": "substantiveness", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "credibility", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "completeness", "dim_type": "fixed", "weight": 0.25},
        {"dim_id": "tech_depth", "dim_type": "dynamic", "weight": 0.25},
    ]
    result = compute_penalized_total(dim_scores, dims)
    assert result["penalty"] == 1.0
    assert result["penalty_reasons"] == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_penalized_total.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_penalized_total'`

**Step 3: Write minimal implementation**

Add to `app/services/oracle.py`:

```python
PENALTY_THRESHOLD = 60

# Mapping of fixed dim_ids to Chinese names for risk messages
FIXED_DIM_NAMES = {
    "substantiveness": "实质性",
    "credibility": "可信度",
    "completeness": "完整性",
}


def compute_penalized_total(
    dim_scores: dict[str, dict],
    dims: list[dict],
) -> dict:
    """Compute non-linear penalized total score.

    Args:
        dim_scores: {dim_id: {"score": int, "band": str, ...}}
        dims: [{"dim_id": str, "dim_type": str, "weight": float}]

    Returns:
        {"weighted_base", "penalty", "penalty_reasons", "final_score", "risk_flags"}
    """
    weighted_base = 0.0
    penalty = 1.0
    penalty_reasons = []
    risk_flags = []

    for dim in dims:
        dim_id = dim["dim_id"]
        weight = dim["weight"]
        score_entry = dim_scores.get(dim_id, {})
        score = score_entry.get("score", 0)
        weighted_base += score * weight

        if dim["dim_type"] == "fixed" and score < PENALTY_THRESHOLD:
            penalty *= score / PENALTY_THRESHOLD
            name = FIXED_DIM_NAMES.get(dim_id, dim_id)
            penalty_reasons.append(f"关键维度「{name}」低于预期")
            risk_flags.append(f"{name}偏低")

    final_score = round(weighted_base * penalty, 2)
    weighted_base = round(weighted_base, 2)
    penalty = round(penalty, 4)

    return {
        "weighted_base": weighted_base,
        "penalty": penalty,
        "penalty_reasons": penalty_reasons,
        "final_score": final_score,
        "risk_flags": risk_flags,
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_penalized_total.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/services/oracle.py tests/test_penalized_total.py
git commit -m "feat(oracle): add compute_penalized_total non-linear scoring formula"
```

---

## Task 3: Update dimension_gen — add "credibility" as 3rd fixed dimension

**Files:**
- Modify: `oracle/dimension_gen.py:22-36` (update prompt rules)
- Test: `tests/test_oracle_v2_router.py::test_dimension_gen_mode`

**Step 1: Write the failing test**

Add a new test in `tests/test_oracle_v2_router.py`:

```python
MOCK_DIMENSIONS_3FIXED = {
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "评估提交是否有实质内容", "weight": 0.25,
         "scoring_guidance": "高分: 有独到见解; 低分: 空洞堆砌"},
        {"id": "credibility", "name": "可信度", "type": "fixed",
         "description": "数据是否可信、有无编造", "weight": 0.25,
         "scoring_guidance": "高分: 数据可验证; 低分: 数据编造"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "评估覆盖度", "weight": 0.25,
         "scoring_guidance": "高分: 覆盖全面; 低分: 遗漏重要方面"},
        {"id": "data_precision", "name": "数据精度", "type": "dynamic",
         "description": "数据准确性", "weight": 0.25,
         "scoring_guidance": "高分: 数据可验证; 低分: 数据模糊"},
    ],
    "rationale": "根据任务需求生成"
}


def test_dimension_gen_prompt_includes_credibility():
    """dimension_gen prompt should include credibility as the 3rd fixed dimension."""
    import dimension_gen
    input_data = {
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "acceptance_criteria": "至少覆盖10个产品",
    }
    with patch.object(dimension_gen, "call_llm_json", return_value=(MOCK_DIMENSIONS_3FIXED, MOCK_USAGE)) as mock_llm:
        output = dimension_gen.run(input_data)
        # Verify prompt contains credibility as fixed dimension
        call_args = mock_llm.call_args
        prompt_text = call_args[0][0]
        assert "可信度" in prompt_text
        assert "credibility" in prompt_text

    assert len(output["dimensions"]) == 4
    fixed_dims = [d for d in output["dimensions"] if d["type"] == "fixed"]
    assert len(fixed_dims) == 3
    fixed_ids = {d["id"] for d in fixed_dims}
    assert fixed_ids == {"substantiveness", "credibility", "completeness"}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_router.py::test_dimension_gen_prompt_includes_credibility -v`
Expected: FAIL — prompt does not contain "可信度" or "credibility"

**Step 3: Update dimension_gen.py prompt**

Replace the rules section in `oracle/dimension_gen.py`:

```python
PROMPT_TEMPLATE = """## 你的任务
根据任务描述和验收标准，生成评分维度。

## 输入

### 任务标题
{task_title}

### 任务描述
{task_description}

### 验收标准
{acceptance_criteria}

## 规则

1. 固定维度（必须包含，且必须按此顺序出现）:
   - **实质性** (id: substantiveness): 评估提交是否提供了真正有价值的内容，且回应任务诉求，而非形式完整但实质空洞的堆砌。
   - **可信度** (id: credibility): 评估数据是否可信、有无编造，数据来源是否可追溯，不同数据点之间是否自洽。
   - **完整性** (id: completeness): 评估提交是否覆盖了任务描述中提及的所有方面和需求点，无重大遗漏。

2. 动态维度（根据任务推断，1-3个）:
   - 必须直接来源于任务描述中的显式或隐式需求
   - 维度之间不能有高度重叠
   - 每个维度必须有明确的评判标准描述

3. 权重分配:
   - 所有维度权重总和 = 1
   - 权重反映任务描述中各方面的重要程度
   - 验收标准中反复强调的方面应获得更高权重

4. 总维度数量: 4-6个（含3个固定维度）

## 输出格式 (严格JSON)

{{
  "dimensions": [
    {{
      "id": "substantiveness",
      "name": "实质性",
      "type": "fixed",
      "description": "...(根据具体任务定制描述)",
      "weight": 0.xx,
      "scoring_guidance": "...(什么样的提交得高分，什么样得低分)"
    }},
    {{
      "id": "credibility",
      "name": "可信度",
      "type": "fixed",
      "description": "...",
      "weight": 0.xx,
      "scoring_guidance": "..."
    }},
    {{
      "id": "completeness",
      "name": "完整性",
      "type": "fixed",
      "description": "...",
      "weight": 0.xx,
      "scoring_guidance": "..."
    }},
    {{
      "id": "dynamic_dim_1",
      "name": "...",
      "type": "dynamic",
      "description": "...",
      "weight": 0.xx,
      "scoring_guidance": "..."
    }}
  ],
  "rationale": "解释维度选择和权重分配的理由"
}}"""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_router.py::test_dimension_gen_prompt_includes_credibility tests/test_oracle_v2_router.py::test_dimension_gen_mode -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add oracle/dimension_gen.py tests/test_oracle_v2_router.py
git commit -m "feat(oracle): add credibility as 3rd fixed scoring dimension"
```

---

## Task 4: Upgrade score_individual — band-first + evidence + fixed 2 suggestions

**Files:**
- Modify: `oracle/score_individual.py` (complete rewrite of prompt and output format)
- Test: `tests/test_oracle_v2_router.py::test_score_individual` (update mock + assertions)

**Step 1: Write the failing test**

Update the existing test and add a new one in `tests/test_oracle_v2_router.py`:

```python
MOCK_INDIVIDUAL_SCORE_V2 = {
    "dimension_scores": {
        "substantiveness": {
            "band": "B",
            "score": 74,
            "evidence": "提交中关于 X 的分析引用了具体数据（第3段），但对 Y 的讨论停留在概念层面",
            "feedback": "内容有一定深度但 Y 部分缺乏支撑"
        },
        "credibility": {
            "band": "D",
            "score": 42,
            "evidence": "数据缺乏来源标注，多处数据过于精确但无引用",
            "feedback": "可信度不足",
            "flag": "below_expected"
        },
        "completeness": {
            "band": "B",
            "score": 72,
            "evidence": "覆盖了8/10个要求的方面",
            "feedback": "覆盖度良好"
        },
    },
    "overall_band": "C",
    "revision_suggestions": [
        {"problem": "数据缺乏来源", "suggestion": "补充数据来源或获取方式", "severity": "high"},
        {"problem": "结论逻辑跳跃", "suggestion": "补充推导过程", "severity": "medium"},
    ]
}


def test_score_individual_v2_band_first():
    """score_individual should return band-first IR with evidence and structured suggestions."""
    import score_individual
    input_data = {
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "dimensions": [
            {"id": "substantiveness", "name": "实质性", "description": "内容质量",
             "weight": 0.3, "scoring_guidance": "guide1"},
            {"id": "credibility", "name": "可信度", "description": "数据可信度",
             "weight": 0.3, "scoring_guidance": "guide2"},
            {"id": "completeness", "name": "完整性", "description": "覆盖度",
             "weight": 0.4, "scoring_guidance": "guide3"},
        ],
        "submission_payload": "调研报告内容...",
    }
    with patch.object(score_individual, "call_llm_json", return_value=(MOCK_INDIVIDUAL_SCORE_V2, MOCK_USAGE)) as mock_llm:
        output = score_individual.run(input_data)
        # Verify prompt contains band-first instructions
        prompt_text = mock_llm.call_args[0][0]
        assert "band" in prompt_text.lower() or "Band" in prompt_text or "档位" in prompt_text
        assert "evidence" in prompt_text.lower() or "证据" in prompt_text or "依据" in prompt_text

    # Verify output structure
    assert "dimension_scores" in output
    assert "overall_band" in output
    assert "revision_suggestions" in output

    # Each dimension has band, score, evidence, feedback
    sub_score = output["dimension_scores"]["substantiveness"]
    assert "band" in sub_score
    assert "score" in sub_score
    assert "evidence" in sub_score
    assert "feedback" in sub_score

    # credibility has flag
    cred_score = output["dimension_scores"]["credibility"]
    assert cred_score.get("flag") == "below_expected"

    # Exactly 2 structured suggestions
    assert len(output["revision_suggestions"]) == 2
    for sug in output["revision_suggestions"]:
        assert "problem" in sug
        assert "suggestion" in sug
        assert "severity" in sug
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_router.py::test_score_individual_v2_band_first -v`
Expected: FAIL — prompt doesn't contain band/evidence keywords

**Step 3: Rewrite score_individual.py**

Replace the entire content of `oracle/score_individual.py`:

```python
"""Individual scoring — band-first scoring with evidence for each dimension."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的质量评分 Oracle。对单个提交在各维度独立打分（band-first），强制引用证据，返回严格JSON。"

PROMPT_TEMPLATE = """## 你的任务
对单个提交在每个评分维度上独立打分，使用 Band-first 方法：先判定档位，再在档内给精确分数。
每个维度必须引用提交中的具体内容作为评分依据（evidence），不允许泛泛评价。
最后给出恰好 2 条修订建议，按严重程度排序。

## 任务信息

### 标题
{task_title}

### 描述
{task_description}

## 评分维度

{dimensions_text}

## 提交内容
{submission_payload}

## Band-first 评分流程

对每个维度：
1. 先判定落在哪个档位（Band）
2. 再在档内给精确分数
3. 引用提交中的具体内容作为 evidence
4. 如果某个 fixed 类型维度的分数低于 60，添加 "flag": "below_expected"

### 档位定义

| Band | 分数区间 | 含义 |
|------|---------|------|
| A | 90-100 | 显著超出预期 |
| B | 70-89 | 良好完成，有亮点 |
| C | 50-69 | 基本满足但平庸 |
| D | 30-49 | 勉强相关但质量差 |
| E | 0-29 | 几乎无价值 |

## 修订建议规则
- 恰好给出 2 条建议（不多不少）
- 按严重程度排序（high → medium → low）
- 聚焦最关键的问题
- 结构化为 {{"problem": "...", "suggestion": "...", "severity": "high/medium/low"}}

## 输出格式 (严格JSON)

{{
  "dimension_scores": {{
    "dim_id": {{
      "band": "A/B/C/D/E",
      "score": 0-100,
      "evidence": "引用提交中的具体内容作为评分依据",
      "feedback": "简要反馈"
    }}
  }},
  "overall_band": "A/B/C/D/E",
  "revision_suggestions": [
    {{ "problem": "具体问题", "suggestion": "改进建议", "severity": "high/medium/low" }},
    {{ "problem": "具体问题", "suggestion": "改进建议", "severity": "high/medium/low" }}
  ]
}}"""


def _format_dimensions(dimensions: list) -> str:
    lines = []
    for dim in dimensions:
        lines.append(f"### {dim['name']} (id: {dim['id']})")
        lines.append(f"描述: {dim['description']}")
        lines.append(f"评分指引: {dim['scoring_guidance']}")
        lines.append("")
    return "\n".join(lines)


def run(input_data: dict) -> dict:
    dimensions = input_data.get("dimensions", [])
    prompt = PROMPT_TEMPLATE.format(
        task_title=input_data.get("task_title", ""),
        task_description=input_data.get("task_description", ""),
        dimensions_text=_format_dimensions(dimensions),
        submission_payload=input_data.get("submission_payload", ""),
    )
    result, _usage = call_llm_json(prompt, system=SYSTEM_PROMPT)
    return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_oracle_v2_router.py::test_score_individual_v2_band_first tests/test_oracle_v2_router.py::test_score_individual -v`
Expected: Both PASS (the old test needs its mock updated — see Step 4a)

**Step 4a: Update old test mock data**

Update `MOCK_INDIVIDUAL_SCORE` in `tests/test_oracle_v2_router.py` to match new format:

```python
MOCK_INDIVIDUAL_SCORE = {
    "dimension_scores": {
        "substantiveness": {"band": "B", "score": 72, "evidence": "内容充实", "feedback": "内容充实但缺少深度分析"},
        "completeness": {"band": "C", "score": 65, "evidence": "覆盖了大部分", "feedback": "覆盖了大部分需求"},
        "data_precision": {"band": "B", "score": 80, "evidence": "数据精确", "feedback": "数据精确"},
    },
    "overall_band": "B",
    "revision_suggestions": [
        {"problem": "竞品对比不足", "suggestion": "建议增加竞品对比分析", "severity": "high"},
        {"problem": "数据来源缺失", "suggestion": "部分数据缺少来源标注", "severity": "medium"},
    ]
}
```

Update existing `test_score_individual` assertions:

```python
def test_score_individual():
    import score_individual
    input_data = {
        "mode": "score_individual",
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "dimensions": [
            {"id": "substantiveness", "name": "实质性", "description": "内容质量",
             "weight": 0.3, "scoring_guidance": "guide1"},
            {"id": "completeness", "name": "完整性", "description": "覆盖度",
             "weight": 0.3, "scoring_guidance": "guide2"},
            {"id": "data_precision", "name": "数据精度", "description": "准确性",
             "weight": 0.4, "scoring_guidance": "guide3"},
        ],
        "submission_payload": "调研报告内容...",
    }
    with patch.object(score_individual, "call_llm_json", return_value=(MOCK_INDIVIDUAL_SCORE, MOCK_USAGE)):
        output = score_individual.run(input_data)
    assert "dimension_scores" in output
    assert "revision_suggestions" in output
    assert output["dimension_scores"]["substantiveness"]["score"] == 72
    assert output["dimension_scores"]["substantiveness"]["band"] == "B"
    assert "overall_band" in output
    assert len(output["revision_suggestions"]) == 2
```

**Step 5: Run all oracle router tests**

Run: `pytest tests/test_oracle_v2_router.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add oracle/score_individual.py tests/test_oracle_v2_router.py
git commit -m "feat(oracle): score_individual band-first + evidence + 2 structured suggestions"
```

---

## Task 5: Simplify dimension_score — remove caps, add individual IR reference

**Files:**
- Modify: `oracle/dimension_score.py` (remove cap logic, add IR reference)
- Test: `tests/test_oracle_v2_router.py::test_dimension_score` (update mock + assertions)

**Step 1: Write the failing test**

Add new test in `tests/test_oracle_v2_router.py`:

```python
MOCK_DIM_SCORE_V2 = {
    "dimension_id": "substantiveness",
    "dimension_name": "实质性",
    "evaluation_focus": "内容深度和独到性",
    "comparative_analysis": "A优于B和C",
    "scores": [
        {"submission": "Submission_A", "raw_score": 85,
         "final_score": 85, "evidence": "深度分析到位"},
        {"submission": "Submission_B", "raw_score": 72,
         "final_score": 72, "evidence": "有价值但深度不足"},
        {"submission": "Submission_C", "raw_score": 60,
         "final_score": 60, "evidence": "基本满足"},
    ]
}


def test_dimension_score_v2_no_caps_with_ir():
    """dimension_score should accept individual_ir instead of constraint_caps."""
    import dimension_score
    input_data = {
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "dimension": {
            "id": "substantiveness", "name": "实质性",
            "description": "内容质量", "scoring_guidance": "guide",
        },
        "individual_ir": {
            "Submission_A": {"band": "B", "evidence": "较充实"},
            "Submission_B": {"band": "B", "evidence": "基本满足"},
            "Submission_C": {"band": "A", "evidence": "非常充实"},
        },
        "submissions": [
            {"label": "Submission_A", "payload": "content A"},
            {"label": "Submission_B", "payload": "content B"},
            {"label": "Submission_C", "payload": "content C"},
        ],
    }
    with patch.object(dimension_score, "call_llm_json", return_value=(MOCK_DIM_SCORE_V2, MOCK_USAGE)) as mock_llm:
        output = dimension_score.run(input_data)
        prompt_text = mock_llm.call_args[0][0]
        # Verify prompt contains individual IR reference
        assert "Individual Scoring" in prompt_text or "individual" in prompt_text.lower() or "仅供" in prompt_text
        # Verify NO constraint_caps in prompt
        assert "score_cap" not in prompt_text
        assert "cap" not in prompt_text.lower() or "仅供" in prompt_text

    assert output["dimension_id"] == "substantiveness"
    assert len(output["scores"]) == 3
    # No cap_applied field in output
    for score_entry in output["scores"]:
        assert "cap_applied" not in score_entry
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_router.py::test_dimension_score_v2_no_caps_with_ir -v`
Expected: FAIL — prompt still contains "cap", output still has "cap_applied"

**Step 3: Rewrite dimension_score.py**

Replace the entire content of `oracle/dimension_score.py`:

```python
"""Dimension scoring — horizontal comparison of submissions on a single dimension."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的质量评分 Oracle，当前对单一维度进行横向评分，返回严格JSON。"

PROMPT_TEMPLATE = """## 你的任务
在指定维度下，对所有提交进行横向比较并打分。只关注当前维度。

## 任务信息

### 标题
{task_title}

### 描述
{task_description}

## 当前评分维度

### 维度名称
{dim_name}

### 维度描述
{dim_description}

### 评分指引
{dim_scoring_guidance}

## Individual Scoring 参考（仅供锚定，不限制你的判断）

{individual_ir_text}

## 待评提交（已匿名化）

{submissions_text}

## 评分流程

### 1. 明确评判焦点
结合任务描述和维度定义，阐述该维度的评判重点。

### 2. 逐提交分析
对每个提交分析在该维度上的表现，具体引用提交中的内容作为 evidence。

### 3. 横向比较
将所有提交在该维度上的表现放在一起对比，说明排序理由。

### 4. 打分
0-100 分。

## 打分标准
- 90-100: 显著超出预期
- 70-89: 良好完成，有亮点
- 50-69: 基本满足但平庸
- 30-49: 勉强相关但质量差
- 0-29: 几乎无价值

## 输出格式 (严格JSON)

{{
  "dimension_id": "{dim_id}",
  "dimension_name": "{dim_name}",
  "evaluation_focus": "本次评判的具体焦点",
  "comparative_analysis": "横向比较说明",
  "scores": [
    {{
      "submission": "Submission_A",
      "raw_score": 85,
      "final_score": 85,
      "evidence": "核心评分依据"
    }}
  ]
}}"""


def _format_individual_ir(ir: dict) -> str:
    if not ir:
        return "无 individual scoring 参考"
    lines = []
    for label, data in ir.items():
        band = data.get("band", "?")
        evidence = data.get("evidence", "")
        lines.append(f"- {label}: band={band}, evidence=\"{evidence}\"")
    return "\n".join(lines)


def _format_submissions(submissions: list) -> str:
    lines = []
    for sub in submissions:
        lines.append(f"### {sub['label']}")
        lines.append(sub.get("payload", ""))
        lines.append("")
    return "\n".join(lines)


def run(input_data: dict) -> dict:
    dim = input_data.get("dimension", {})
    prompt = PROMPT_TEMPLATE.format(
        task_title=input_data.get("task_title", ""),
        task_description=input_data.get("task_description", ""),
        dim_id=dim.get("id", ""),
        dim_name=dim.get("name", ""),
        dim_description=dim.get("description", ""),
        dim_scoring_guidance=dim.get("scoring_guidance", ""),
        individual_ir_text=_format_individual_ir(input_data.get("individual_ir", {})),
        submissions_text=_format_submissions(input_data.get("submissions", [])),
    )
    result, _usage = call_llm_json(prompt, system=SYSTEM_PROMPT)
    return result
```

**Step 4: Update old test_dimension_score mock + assertions**

Update `MOCK_DIM_SCORE` and `test_dimension_score` in `tests/test_oracle_v2_router.py`:

```python
MOCK_DIM_SCORE = {
    "dimension_id": "substantiveness",
    "dimension_name": "实质性",
    "evaluation_focus": "内容深度和独到性",
    "comparative_analysis": "A优于B和C",
    "scores": [
        {"submission": "Submission_A", "raw_score": 85,
         "final_score": 85, "evidence": "深度分析到位"},
        {"submission": "Submission_B", "raw_score": 72,
         "final_score": 72, "evidence": "有价值但深度不足"},
        {"submission": "Submission_C", "raw_score": 60,
         "final_score": 60, "evidence": "基本满足"},
    ]
}


def test_dimension_score():
    import dimension_score
    input_data = {
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "dimension": {
            "id": "substantiveness", "name": "实质性",
            "description": "内容质量", "scoring_guidance": "guide",
        },
        "individual_ir": {
            "Submission_A": {"band": "B", "evidence": "较充实"},
            "Submission_B": {"band": "C", "evidence": "基本满足"},
            "Submission_C": {"band": "C", "evidence": "一般"},
        },
        "submissions": [
            {"label": "Submission_A", "payload": "content A"},
            {"label": "Submission_B", "payload": "content B"},
            {"label": "Submission_C", "payload": "content C"},
        ],
    }
    with patch.object(dimension_score, "call_llm_json", return_value=(MOCK_DIM_SCORE, MOCK_USAGE)):
        output = dimension_score.run(input_data)
    assert output["dimension_id"] == "substantiveness"
    assert len(output["scores"]) == 3
```

**Step 5: Run tests**

Run: `pytest tests/test_oracle_v2_router.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add oracle/dimension_score.py tests/test_oracle_v2_router.py
git commit -m "feat(oracle): dimension_score remove caps, add individual IR reference"
```

---

## Task 6: Delete constraint_check + remove from oracle.py

**Files:**
- Delete: `oracle/constraint_check.py`
- Modify: `oracle/oracle.py:32-33,38` (remove constraint_check import and registration)
- Modify: `tests/test_oracle_v2_router.py` (remove constraint_check tests)

**Step 1: Verify which tests reference constraint_check**

Run: `grep -rn "constraint_check" tests/`

**Step 2: Remove constraint_check from oracle.py V2_MODES**

In `oracle/oracle.py`, remove these lines:

```python
# Remove this import:
from constraint_check import run as constraint_check_run

# Remove this entry from V2_MODES dict:
"constraint_check": constraint_check_run,
```

**Step 3: Delete constraint_check.py**

```bash
rm oracle/constraint_check.py
```

**Step 4: Remove constraint_check tests from test_oracle_v2_router.py**

Delete `test_constraint_check_fastest_first()` and `test_constraint_check_quality_first()` functions and their associated mock data (`MOCK_CONSTRAINT_FF_PASS`, `MOCK_CONSTRAINT_QF`).

**Step 5: Run tests to verify**

Run: `pytest tests/test_oracle_v2_router.py tests/test_oracle_stub.py -v`
Expected: All remaining tests PASS

**Step 6: Commit**

```bash
git rm oracle/constraint_check.py
git add oracle/oracle.py tests/test_oracle_v2_router.py
git commit -m "refactor(oracle): delete constraint_check, absorbed by fixed dimensions"
```

---

## Task 7: Rewrite score_submission() for fastest_first path

**Files:**
- Modify: `app/services/oracle.py:164-218` (rewrite `score_submission`)
- Modify: `tests/test_oracle_v2_service.py` (update fastest_first tests)

**Step 1: Write the failing test**

Replace the existing fastest_first tests in `tests/test_oracle_v2_service.py`:

```python
MOCK_GATE_PASS = json.dumps({
    "overall_passed": True,
    "criteria_checks": [{"criteria": "AC1", "passed": True, "evidence": "ok"}],
    "summary": "通过"
})

MOCK_INDIVIDUAL_FF = json.dumps({
    "dimension_scores": {
        "substantiveness": {"band": "B", "score": 80, "evidence": "good content", "feedback": "好"},
        "credibility": {"band": "B", "score": 72, "evidence": "可信", "feedback": "可信"},
        "completeness": {"band": "B", "score": 75, "evidence": "完整", "feedback": "完整"},
    },
    "overall_band": "B",
    "revision_suggestions": [
        {"problem": "p1", "suggestion": "s1", "severity": "high"},
        {"problem": "p2", "suggestion": "s2", "severity": "medium"},
    ]
})

MOCK_INDIVIDUAL_FF_LOW = json.dumps({
    "dimension_scores": {
        "substantiveness": {"band": "D", "score": 40, "evidence": "弱", "feedback": "弱"},
        "credibility": {"band": "D", "score": 35, "evidence": "不可信", "feedback": "不可信"},
        "completeness": {"band": "C", "score": 55, "evidence": "勉强", "feedback": "勉强"},
    },
    "overall_band": "D",
    "revision_suggestions": [
        {"problem": "p1", "suggestion": "s1", "severity": "high"},
        {"problem": "p2", "suggestion": "s2", "severity": "medium"},
    ]
})


def test_score_submission_fastest_first_pass_v2(db):
    """fastest_first: gate pass + score_individual → penalized_total >= 60 → close task."""
    from app.services.oracle import score_submission

    task = Task(
        title="Test", description="Desc", type=TaskType.fastest_first,
        threshold=0.6, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=0,
        acceptance_criteria="AC",
    )
    db.add(task)
    db.commit()

    # Add dimensions
    for dim_id, name, dtype, w in [
        ("substantiveness", "实质性", "fixed", 0.34),
        ("credibility", "可信度", "fixed", 0.33),
        ("completeness", "完整性", "fixed", 0.33),
    ]:
        db.add(ScoringDimension(
            task_id=task.id, dim_id=dim_id, name=name,
            dim_type=dtype, description="d", weight=w, scoring_guidance="g"
        ))
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="good content")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    individual_result = type("R", (), {"stdout": MOCK_INDIVIDUAL_FF, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return gate_result if call_count == 1 else individual_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess), \
         patch("app.services.oracle.pay_winner"):
        score_submission(db, sub.id, task.id)

    db.refresh(sub)
    db.refresh(task)
    assert sub.status == SubmissionStatus.scored
    assert task.status == TaskStatus.closed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "scoring"
    assert "dimension_scores" in feedback
    assert "penalty" in feedback
    assert "final_score" in feedback
    assert feedback["final_score"] >= 60


def test_score_submission_fastest_first_low_score(db):
    """fastest_first: gate pass + score_individual → penalized_total < 60 → scored but not closed."""
    from app.services.oracle import score_submission

    task = Task(
        title="Test", description="Desc", type=TaskType.fastest_first,
        threshold=0.6, deadline=datetime(2026, 12, 31, tzinfo=timezone.utc), bounty=0,
        acceptance_criteria="AC",
    )
    db.add(task)
    db.commit()

    for dim_id, name, dtype, w in [
        ("substantiveness", "实质性", "fixed", 0.34),
        ("credibility", "可信度", "fixed", 0.33),
        ("completeness", "完整性", "fixed", 0.33),
    ]:
        db.add(ScoringDimension(
            task_id=task.id, dim_id=dim_id, name=name,
            dim_type=dtype, description="d", weight=w, scoring_guidance="g"
        ))
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="bad content")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    individual_result = type("R", (), {"stdout": MOCK_INDIVIDUAL_FF_LOW, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return gate_result if call_count == 1 else individual_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        score_submission(db, sub.id, task.id)

    db.refresh(sub)
    db.refresh(task)
    assert sub.status == SubmissionStatus.scored
    assert task.status == TaskStatus.open  # NOT closed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "scoring"
    assert feedback["final_score"] < 60
    assert len(feedback["risk_flags"]) > 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_oracle_v2_service.py::test_score_submission_fastest_first_pass_v2 tests/test_oracle_v2_service.py::test_score_submission_fastest_first_low_score -v`
Expected: FAIL

**Step 3: Rewrite score_submission() in app/services/oracle.py**

```python
def score_submission(db: Session, submission_id: str, task_id: str) -> None:
    """Score a single submission (fastest_first path): gate_check + score_individual + penalized_total."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not submission or not task:
        return

    sub_meta = {"task_id": task.id, "task_title": task.title,
                "submission_id": submission.id, "worker_id": submission.worker_id}

    # Step 1: Gate Check
    gate_payload = {
        "mode": "gate_check",
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
        "submission_payload": submission.content,
    }
    gate_result = _call_oracle(gate_payload, meta=sub_meta)

    if not gate_result.get("overall_passed", False):
        submission.oracle_feedback = json.dumps({
            "type": "scoring",
            "gate_check": gate_result,
            "passed": False,
        })
        submission.score = 0.0
        submission.status = SubmissionStatus.scored
        db.commit()
        return

    # Step 2: Score Individual (band-first + evidence)
    dimensions = db.query(ScoringDimension).filter(
        ScoringDimension.task_id == task_id
    ).all()

    if not dimensions:
        # V1 fallback — no dimensions available
        output = _call_oracle(_build_payload(task, submission, "score"), meta=sub_meta)
        submission.score = output.get("score", 0.0)
        submission.oracle_feedback = json.dumps({
            "type": "scoring",
            "passed": submission.score >= (task.threshold or 0),
            **output,
        })
        submission.status = SubmissionStatus.scored
        db.commit()
        if submission.score >= (task.threshold or 0):
            _apply_fastest_first(db, task, submission)
        return

    dims_data = [
        {"id": d.dim_id, "name": d.name, "description": d.description,
         "weight": d.weight, "scoring_guidance": d.scoring_guidance}
        for d in dimensions
    ]
    score_payload = {
        "mode": "score_individual",
        "task_title": task.title,
        "task_description": task.description,
        "dimensions": dims_data,
        "submission_payload": submission.content,
    }
    score_result = _call_oracle(score_payload, meta=sub_meta)

    # Step 3: Compute penalized_total
    dim_scores = score_result.get("dimension_scores", {})
    dims_for_penalty = [
        {"dim_id": d.dim_id, "dim_type": d.dim_type, "weight": d.weight}
        for d in dimensions
    ]
    penalty_result = compute_penalized_total(dim_scores, dims_for_penalty)

    final_score = penalty_result["final_score"]
    passed = final_score >= PENALTY_THRESHOLD

    submission.oracle_feedback = json.dumps({
        "type": "scoring",
        "dimension_scores": dim_scores,
        "overall_band": score_result.get("overall_band", ""),
        "revision_suggestions": score_result.get("revision_suggestions", []),
        "weighted_base": penalty_result["weighted_base"],
        "penalty": penalty_result["penalty"],
        "penalty_reasons": penalty_result["penalty_reasons"],
        "final_score": final_score,
        "risk_flags": penalty_result["risk_flags"],
        "passed": passed,
    })
    submission.score = final_score / 100.0
    submission.status = SubmissionStatus.scored
    db.commit()

    if passed:
        _apply_fastest_first(db, task, submission)
```

Also update `_apply_fastest_first` to compare against penalized score:

```python
def _apply_fastest_first(db: Session, task: Task, submission: Submission) -> None:
    if task.type.value != "fastest_first" or task.status != TaskStatus.open:
        return
    # threshold comparison: submission.score is final_score / 100
    if task.threshold is not None and submission.score >= task.threshold:
        task.winner_submission_id = submission.id
        task.status = TaskStatus.closed
        db.commit()
        pay_winner(db, task.id)
        from .trust import apply_event
        from ..models import TrustEventType, User
        if db.query(User).filter_by(id=task.publisher_id).first():
            apply_event(db, task.publisher_id, TrustEventType.publisher_completed,
                        task_bounty=task.bounty or 0.0, task_id=task.id)
```

**Step 4: Run tests**

Run: `pytest tests/test_oracle_v2_service.py -v`
Expected: All PASS (remove old `test_score_submission_fastest_first_pass` and `test_score_submission_fastest_first_constraint_fail` tests)

**Step 5: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_v2_service.py
git commit -m "feat(oracle): fastest_first uses score_individual + penalized_total"
```

---

## Task 8: Rewrite batch_score_submissions() for quality_first path

**Files:**
- Modify: `app/services/oracle.py:238-373` (rewrite `batch_score_submissions`)
- Modify: `tests/test_oracle_v2_service.py` (update batch_score tests)

**Step 1: Write the failing test**

Replace/add in `tests/test_oracle_v2_service.py`:

```python
MOCK_DIM_SCORE_SUB_V2 = json.dumps({
    "dimension_id": "substantiveness",
    "dimension_name": "实质性",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 85,
         "final_score": 85, "evidence": "good"},
        {"submission": "Submission_B", "raw_score": 70,
         "final_score": 70, "evidence": "ok"},
    ]
})

MOCK_DIM_SCORE_COMP_V2 = json.dumps({
    "dimension_id": "completeness",
    "dimension_name": "完整性",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 80,
         "final_score": 80, "evidence": "good"},
        {"submission": "Submission_B", "raw_score": 60,
         "final_score": 60, "evidence": "ok"},
    ]
})

MOCK_DIM_SCORE_CRED_V2 = json.dumps({
    "dimension_id": "credibility",
    "dimension_name": "可信度",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 75,
         "final_score": 75, "evidence": "credible"},
        {"submission": "Submission_B", "raw_score": 65,
         "final_score": 65, "evidence": "ok"},
    ]
})


def test_batch_score_no_constraint_check(db):
    """batch_score should NOT call constraint_check, should use penalized_total."""
    from app.services.oracle import batch_score_submissions

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="至少10个产品",
    )
    db.add(task)
    db.commit()

    for dim_id, name, dtype, w in [
        ("substantiveness", "实质性", "fixed", 0.34),
        ("credibility", "可信度", "fixed", 0.33),
        ("completeness", "完整性", "fixed", 0.33),
    ]:
        db.add(ScoringDimension(
            task_id=task.id, dim_id=dim_id, name=name,
            dim_type=dtype, description="d", weight=w, scoring_guidance="g"
        ))
    db.commit()

    # 2 gate_passed submissions with individual IR scores
    sub1 = Submission(
        task_id=task.id, worker_id="w1", content="content A",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 80, "evidence": "good", "feedback": "good"},
                "credibility": {"band": "B", "score": 75, "evidence": "ok", "feedback": "ok"},
                "completeness": {"band": "B", "score": 70, "evidence": "ok", "feedback": "ok"},
            },
            "overall_band": "B",
            "revision_suggestions": []
        })
    )
    sub2 = Submission(
        task_id=task.id, worker_id="w2", content="content B",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "C", "score": 60, "evidence": "basic", "feedback": "basic"},
                "credibility": {"band": "C", "score": 55, "evidence": "weak", "feedback": "weak"},
                "completeness": {"band": "C", "score": 50, "evidence": "incomplete", "feedback": "incomplete"},
            },
            "overall_band": "C",
            "revision_suggestions": []
        })
    )
    db.add_all([sub1, sub2])
    db.commit()

    # Mock: only dimension_score calls (NO constraint_check)
    responses = [
        type("R", (), {"stdout": MOCK_DIM_SCORE_SUB_V2, "returncode": 0})(),
        type("R", (), {"stdout": MOCK_DIM_SCORE_CRED_V2, "returncode": 0})(),
        type("R", (), {"stdout": MOCK_DIM_SCORE_COMP_V2, "returncode": 0})(),
    ]
    call_idx = 0
    payloads_sent = []
    def mock_subprocess(*args, **kwargs):
        nonlocal call_idx
        payload = json.loads(kwargs.get("input", args[0] if args else "{}"))
        payloads_sent.append(payload)
        result = responses[call_idx]
        call_idx += 1
        return result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        batch_score_submissions(db, task.id)

    # Verify NO constraint_check calls were made
    modes_called = [p.get("mode") for p in payloads_sent]
    assert "constraint_check" not in modes_called
    assert all(m == "dimension_score" for m in modes_called)

    db.refresh(sub1)
    db.refresh(sub2)
    assert sub1.status == SubmissionStatus.scored
    assert sub2.status == SubmissionStatus.scored

    feedback1 = json.loads(sub1.oracle_feedback)
    assert feedback1["type"] == "scoring"
    assert "penalty" in feedback1
    assert "weighted_base" in feedback1
    assert "risk_flags" in feedback1
    assert feedback1["rank"] == 1


def test_batch_score_threshold_filter(db):
    """Submissions with any fixed dim band < C should be filtered out."""
    from app.services.oracle import batch_score_submissions

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="至少10个产品",
    )
    db.add(task)
    db.commit()

    for dim_id, name, dtype, w in [
        ("substantiveness", "实质性", "fixed", 0.5),
        ("credibility", "可信度", "fixed", 0.25),
        ("completeness", "完整性", "fixed", 0.25),
    ]:
        db.add(ScoringDimension(
            task_id=task.id, dim_id=dim_id, name=name,
            dim_type=dtype, description="d", weight=w, scoring_guidance="g"
        ))
    db.commit()

    # sub1: good scores, all bands >= C
    sub1 = Submission(
        task_id=task.id, worker_id="w1", content="content A",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 80, "evidence": "g", "feedback": "g"},
                "credibility": {"band": "B", "score": 70, "evidence": "g", "feedback": "g"},
                "completeness": {"band": "B", "score": 75, "evidence": "g", "feedback": "g"},
            },
            "overall_band": "B",
            "revision_suggestions": []
        })
    )
    # sub2: credibility band D → filtered out
    sub2 = Submission(
        task_id=task.id, worker_id="w2", content="content B",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 72, "evidence": "g", "feedback": "g"},
                "credibility": {"band": "D", "score": 40, "evidence": "bad", "feedback": "bad"},
                "completeness": {"band": "C", "score": 55, "evidence": "g", "feedback": "g"},
            },
            "overall_band": "C",
            "revision_suggestions": []
        })
    )
    db.add_all([sub1, sub2])
    db.commit()

    # Only 1 sub enters horizontal scoring → 3 dimension_score calls
    dim_score_sub = json.dumps({"dimension_id": "substantiveness", "scores": [
        {"submission": "Submission_A", "raw_score": 85, "final_score": 85, "evidence": "g"}]})
    dim_score_cred = json.dumps({"dimension_id": "credibility", "scores": [
        {"submission": "Submission_A", "raw_score": 75, "final_score": 75, "evidence": "g"}]})
    dim_score_comp = json.dumps({"dimension_id": "completeness", "scores": [
        {"submission": "Submission_A", "raw_score": 80, "final_score": 80, "evidence": "g"}]})
    responses = [
        type("R", (), {"stdout": dim_score_sub, "returncode": 0})(),
        type("R", (), {"stdout": dim_score_cred, "returncode": 0})(),
        type("R", (), {"stdout": dim_score_comp, "returncode": 0})(),
    ]
    call_idx = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_idx
        result = responses[call_idx]
        call_idx += 1
        return result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        batch_score_submissions(db, task.id)

    db.refresh(sub1)
    db.refresh(sub2)
    assert sub1.status == SubmissionStatus.scored
    assert sub2.status == SubmissionStatus.scored
    # sub2 should be scored but marked as below_threshold
    assert sub2.score is not None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_oracle_v2_service.py::test_batch_score_no_constraint_check tests/test_oracle_v2_service.py::test_batch_score_threshold_filter -v`
Expected: FAIL

**Step 3: Rewrite batch_score_submissions()**

```python
BAND_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


def _get_individual_ir(submission: Submission) -> dict:
    """Extract individual scoring IR (band + evidence per dimension) from oracle_feedback."""
    if not submission.oracle_feedback:
        return {}
    try:
        feedback = json.loads(submission.oracle_feedback)
        if feedback.get("type") != "individual_scoring":
            return {}
        dim_scores = feedback.get("dimension_scores", {})
        return {
            dim_id: {"band": v.get("band", "?"), "evidence": v.get("evidence", "")}
            for dim_id, v in dim_scores.items()
        }
    except (json.JSONDecodeError, KeyError):
        return {}


def _passes_threshold_filter(submission: Submission, fixed_dim_ids: set) -> bool:
    """Check if any fixed dimension has band < C (i.e., D or E)."""
    if not submission.oracle_feedback:
        return False
    try:
        feedback = json.loads(submission.oracle_feedback)
        dim_scores = feedback.get("dimension_scores", {})
        for dim_id in fixed_dim_ids:
            entry = dim_scores.get(dim_id, {})
            band = entry.get("band", "E")
            if BAND_ORDER.get(band, 4) > BAND_ORDER["C"]:  # D or E
                return False
        return True
    except (json.JSONDecodeError, KeyError):
        return False


def batch_score_submissions(db: Session, task_id: str) -> None:
    """Score all gate_passed submissions after deadline: threshold filter + horizontal comparison."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    passed = db.query(Submission).filter(
        Submission.task_id == task_id,
        Submission.status == SubmissionStatus.gate_passed,
    ).all()

    # Backward compat with V1 tests
    if not passed:
        passed = db.query(Submission).filter(
            Submission.task_id == task_id,
            Submission.status == SubmissionStatus.pending,
        ).all()

    if not passed:
        return

    dimensions = db.query(ScoringDimension).filter(
        ScoringDimension.task_id == task_id
    ).all()

    task_meta = {"task_id": task.id, "task_title": task.title}

    # V1 fallback: no dimensions
    if not dimensions:
        for submission in passed:
            m = {**task_meta, "submission_id": submission.id, "worker_id": submission.worker_id}
            output = _call_oracle(_build_payload(task, submission, "score"), meta=m)
            submission.score = output.get("score", 0.0)
            submission.oracle_feedback = output.get("feedback", submission.oracle_feedback)
            submission.status = SubmissionStatus.scored
        db.commit()
        return

    dims_data = [
        {"id": d.dim_id, "name": d.name, "description": d.description,
         "weight": d.weight, "scoring_guidance": d.scoring_guidance}
        for d in dimensions
    ]
    fixed_dim_ids = {d.dim_id for d in dimensions if d.dim_type == "fixed"}

    # Step 1: Threshold filter — any fixed dim band < C → below_threshold
    eligible = []
    below_threshold = []
    for sub in passed:
        if _passes_threshold_filter(sub, fixed_dim_ids):
            eligible.append(sub)
        else:
            below_threshold.append(sub)

    # Mark below_threshold subs as scored with their individual score
    for sub in below_threshold:
        individual_total = _get_individual_weighted_total(sub, dimensions)
        dims_for_penalty = [{"dim_id": d.dim_id, "dim_type": d.dim_type, "weight": d.weight} for d in dimensions]
        ir = _get_individual_ir(sub)
        dim_scores_for_penalty = {}
        try:
            feedback = json.loads(sub.oracle_feedback)
            dim_scores_for_penalty = feedback.get("dimension_scores", {})
        except (json.JSONDecodeError, KeyError):
            pass
        penalty_result = compute_penalized_total(dim_scores_for_penalty, dims_for_penalty)
        sub.score = penalty_result["final_score"] / 100.0
        sub.status = SubmissionStatus.scored

    if not eligible:
        db.commit()
        return

    # Step 2: Sort by penalized_total from individual scores, take top 3
    def _get_penalized_total(sub):
        try:
            feedback = json.loads(sub.oracle_feedback)
            dim_scores = feedback.get("dimension_scores", {})
        except (json.JSONDecodeError, KeyError):
            dim_scores = {}
        dims_for_penalty = [{"dim_id": d.dim_id, "dim_type": d.dim_type, "weight": d.weight} for d in dimensions]
        return compute_penalized_total(dim_scores, dims_for_penalty)["final_score"]

    eligible.sort(key=_get_penalized_total, reverse=True)
    top_subs = eligible[:3]

    # Anonymize
    label_map = {}
    anonymized = []
    for i, sub in enumerate(top_subs):
        label = f"Submission_{chr(65 + i)}"
        label_map[label] = sub
        anonymized.append({"label": label, "payload": sub.content})

    # Build individual IR for dimension_score reference
    individual_ir_map = {}
    for anon in anonymized:
        sub = label_map[anon["label"]]
        ir = _get_individual_ir(sub)
        for dim_data in dims_data:
            dim_id = dim_data["id"]
            if dim_id not in individual_ir_map:
                individual_ir_map[dim_id] = {}
            individual_ir_map[dim_id][anon["label"]] = ir.get(dim_id, {"band": "?", "evidence": ""})

    # Step 3: Horizontal scoring per dimension
    all_scores = {}
    for dim_data in dims_data:
        dim_payload = {
            "mode": "dimension_score",
            "task_title": task.title,
            "task_description": task.description,
            "dimension": dim_data,
            "individual_ir": individual_ir_map.get(dim_data["id"], {}),
            "submissions": anonymized,
        }
        result = _call_oracle(dim_payload, meta=task_meta)
        all_scores[dim_data["id"]] = result

    # Step 4: Compute ranking with penalized_total
    ranking = []
    for anon in anonymized:
        label = anon["label"]
        dim_scores_for_ranking = {}
        breakdown = {}
        for dim_data in dims_data:
            dim_id = dim_data["id"]
            scores_list = all_scores[dim_id].get("scores", [])
            entry = next((s for s in scores_list if s["submission"] == label), None)
            if entry:
                breakdown[dim_id] = {
                    "raw_score": entry["raw_score"],
                    "final_score": entry["final_score"],
                    "evidence": entry.get("evidence", ""),
                }
                dim_scores_for_ranking[dim_id] = {"score": entry["final_score"]}

        dims_for_penalty = [{"dim_id": d.dim_id, "dim_type": d.dim_type, "weight": d.weight} for d in dimensions]
        penalty_result = compute_penalized_total(dim_scores_for_ranking, dims_for_penalty)

        ranking.append({
            "label": label,
            "dimension_breakdown": breakdown,
            **penalty_result,
        })

    ranking.sort(key=lambda x: x["final_score"], reverse=True)

    # Write back to submissions
    for rank_idx, entry in enumerate(ranking):
        sub = label_map[entry["label"]]
        sub.oracle_feedback = json.dumps({
            "type": "scoring",
            "dimension_scores": entry["dimension_breakdown"],
            "weighted_base": entry["weighted_base"],
            "penalty": entry["penalty"],
            "penalty_reasons": entry["penalty_reasons"],
            "final_score": entry["final_score"],
            "risk_flags": entry["risk_flags"],
            "rank": rank_idx + 1,
        })
        sub.score = entry["final_score"] / 100.0
        sub.status = SubmissionStatus.scored

    # Mark remaining eligible subs (outside top 3) as scored
    for sub in eligible:
        if sub not in [label_map[a["label"]] for a in anonymized]:
            sub.status = SubmissionStatus.scored
            if not sub.score:
                sub.score = _get_individual_weighted_total(sub, dimensions) / 100.0

    db.commit()
```

**Step 4: Run tests**

Run: `pytest tests/test_oracle_v2_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_v2_service.py
git commit -m "feat(oracle): batch_score removes constraint_check, adds threshold filter + penalized_total"
```

---

## Task 9: Parallelize dimension_score calls

**Files:**
- Modify: `app/services/oracle.py` (add ThreadPoolExecutor in batch_score_submissions)
- Test: `tests/test_oracle_parallel.py`

**Step 1: Write the failing test**

```python
# tests/test_oracle_parallel.py
"""Test that dimension_score calls are parallelized."""
import json
import time
import threading
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, ScoringDimension, TaskType, SubmissionStatus


def test_dimension_score_calls_run_in_parallel():
    """Verify multiple dimension_score calls execute concurrently via ThreadPoolExecutor."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    task = Task(
        title="Test", description="Desc", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria="AC",
    )
    db.add(task)
    db.commit()

    for dim_id, name, w in [("substantiveness", "实质性", 0.34),
                             ("credibility", "可信度", 0.33),
                             ("completeness", "完整性", 0.33)]:
        db.add(ScoringDimension(
            task_id=task.id, dim_id=dim_id, name=name,
            dim_type="fixed", description="d", weight=w, scoring_guidance="g"
        ))
    db.commit()

    sub = Submission(
        task_id=task.id, worker_id="w1", content="content",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 80, "evidence": "g", "feedback": "g"},
                "credibility": {"band": "B", "score": 70, "evidence": "g", "feedback": "g"},
                "completeness": {"band": "B", "score": 75, "evidence": "g", "feedback": "g"},
            },
            "overall_band": "B",
            "revision_suggestions": []
        })
    )
    db.add(sub)
    db.commit()

    concurrent_threads = []
    call_lock = threading.Lock()

    def make_dim_response(dim_id):
        return json.dumps({
            "dimension_id": dim_id, "scores": [
                {"submission": "Submission_A", "raw_score": 80, "final_score": 80, "evidence": "ok"}
            ]
        })

    def mock_subprocess(*args, **kwargs):
        with call_lock:
            concurrent_threads.append(threading.current_thread().name)
        payload = json.loads(kwargs.get("input", "{}"))
        dim_id = payload.get("dimension", {}).get("id", "substantiveness")
        time.sleep(0.05)  # Simulate LLM latency
        return type("R", (), {"stdout": make_dim_response(dim_id), "returncode": 0})()

    from app.services.oracle import batch_score_submissions
    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        start = time.monotonic()
        batch_score_submissions(db, task.id)
        elapsed = time.monotonic() - start

    # With 3 dims × 0.05s each:
    # Sequential: ~0.15s, Parallel: ~0.05s
    # We check that it's faster than sequential would be
    assert elapsed < 0.12, f"Expected parallel execution, but took {elapsed:.3f}s"

    # Verify multiple threads were used
    unique_threads = set(concurrent_threads)
    assert len(unique_threads) > 1, f"Expected multiple threads but got: {unique_threads}"

    db.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_parallel.py -v`
Expected: FAIL — sequential execution takes >0.12s

**Step 3: Add ThreadPoolExecutor to batch_score_submissions**

Add to imports in `app/services/oracle.py`:

```python
from concurrent.futures import ThreadPoolExecutor
```

Replace the sequential dimension_score loop in `batch_score_submissions` with:

```python
    # Step 3: Horizontal scoring per dimension (PARALLEL)
    all_scores = {}

    def _score_dimension(dim_data):
        dim_payload = {
            "mode": "dimension_score",
            "task_title": task.title,
            "task_description": task.description,
            "dimension": dim_data,
            "individual_ir": individual_ir_map.get(dim_data["id"], {}),
            "submissions": anonymized,
        }
        return dim_data["id"], _call_oracle(dim_payload, meta=task_meta)

    with ThreadPoolExecutor(max_workers=len(dims_data)) as executor:
        futures = [executor.submit(_score_dimension, d) for d in dims_data]
        for future in futures:
            dim_id, result = future.result()
            all_scores[dim_id] = result
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_parallel.py -v`
Expected: PASS

**Step 5: Run all oracle tests to verify no regression**

Run: `pytest tests/test_oracle_v2_service.py tests/test_oracle_service.py tests/test_oracle_logs_threadsafe.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_parallel.py
git commit -m "feat(oracle): parallelize dimension_score calls with ThreadPoolExecutor"
```

---

## Task 10: Update give_feedback() to use new IR format

**Files:**
- Modify: `app/services/oracle.py:103-161` (minor updates to give_feedback)
- Modify: `tests/test_oracle_v2_service.py` (update mock data)
- Modify: `tests/test_oracle_service.py` (update mock data)

**Step 1: Update mock data in test_oracle_v2_service.py**

Update `MOCK_INDIVIDUAL_SCORE` to new IR format:

```python
MOCK_INDIVIDUAL_SCORE = json.dumps({
    "dimension_scores": {
        "substantiveness": {"band": "B", "score": 72, "evidence": "内容较充实", "feedback": "较充实"},
        "completeness": {"band": "C", "score": 65, "evidence": "基本覆盖", "feedback": "基本覆盖"},
    },
    "overall_band": "B",
    "revision_suggestions": [
        {"problem": "对比分析不足", "suggestion": "建议增加对比分析", "severity": "high"},
        {"problem": "数据来源缺失", "suggestion": "补充数据来源", "severity": "medium"},
    ]
})
```

Update assertions in `test_give_feedback_gate_pass_then_individual_score`:

```python
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "individual_scoring"
    assert "revision_suggestions" in feedback
    assert len(feedback["revision_suggestions"]) == 2
    # Structured suggestions
    assert "problem" in feedback["revision_suggestions"][0]
    assert "suggestion" in feedback["revision_suggestions"][0]
```

**Step 2: Update mock data in test_oracle_service.py**

```python
FAKE_INDIVIDUAL = json.dumps({
    "dimension_scores": {
        "substantiveness": {"band": "B", "score": 72, "evidence": "ok", "feedback": "ok"},
    },
    "overall_band": "B",
    "revision_suggestions": [
        {"problem": "p1", "suggestion": "s1", "severity": "high"},
        {"problem": "p2", "suggestion": "s2", "severity": "medium"},
    ]
})
```

Update assertion in `test_give_feedback_gate_pass_sets_gate_passed`:

```python
    assert len(feedback["revision_suggestions"]) == 2
```

**Step 3: Run tests**

Run: `pytest tests/test_oracle_v2_service.py tests/test_oracle_service.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_oracle_v2_service.py tests/test_oracle_service.py
git commit -m "test(oracle): update mock data to new IR format (band + evidence + structured suggestions)"
```

---

## Task 11: Update integration tests

**Files:**
- Modify: `tests/test_oracle_v2_integration.py` (remove constraint_check mocks, update assertions)
- Modify: `tests/test_quality_lifecycle.py` (update mock data)

**Step 1: Update test_oracle_v2_integration.py**

Key changes:
- Individual score mocks use new IR format (band + evidence)
- Remove constraint_check responses from `responses` list
- Dimension_score mocks drop `cap_applied` field
- Assertions check for `penalty` and `risk_flags` in feedback

```python
    # T2 individual scores — new IR format
    individual_scores = [
        json.dumps({"dimension_scores": {"substantiveness": {"band": "A", "score": 85, "evidence": "好", "feedback": "好"},
                     "completeness": {"band": "B", "score": 80, "evidence": "好", "feedback": "好"}},
                     "overall_band": "A",
                     "revision_suggestions": [
                         {"problem": "p1", "suggestion": "s1", "severity": "high"},
                         {"problem": "p2", "suggestion": "s2", "severity": "medium"}
                     ]}),
        # ... similar for other submissions
    ]

    # T3 responses — NO constraint_check, only dimension_score
    responses = [
        type("R", (), {"stdout": dim_sub, "returncode": 0})(),    # dim: substantiveness
        type("R", (), {"stdout": dim_comp, "returncode": 0})(),   # dim: completeness
    ]

    # Updated dim_score mocks — no cap_applied
    dim_sub = json.dumps({"dimension_id": "substantiveness", "scores": [
        {"submission": "Submission_A", "raw_score": 90, "final_score": 90, "evidence": "best"},
        # ...
    ]})
```

**Step 2: Update test_quality_lifecycle.py**

Update `test_phase1_triggers_batch_scoring` and `test_lifecycle_phase1_scoring_with_gate_passed_subs`:
- Remove constraint_check mock responses
- Update individual score format to include band + evidence
- Update dimension_score mocks to drop cap_applied

**Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_oracle_v2_integration.py tests/test_quality_lifecycle.py
git commit -m "test(oracle): update integration tests for scoring optimization"
```

---

## Task 12: Update remaining test files + cleanup

**Files:**
- Modify: `tests/test_integration.py` (update oracle mocks if needed)
- Modify: `tests/test_submissions.py` (no changes expected)
- Verify: `tests/test_scheduler.py` (should still pass)

**Step 1: Run full test suite**

Run: `pytest tests/ -v`

**Step 2: Fix any remaining failures**

For each failure:
- If mock data format mismatch → update mock to new IR format
- If constraint_check reference → remove it
- If cap_applied assertion → remove it
- If weighted_total assertion → change to final_score

**Step 3: Run full suite again**

Run: `pytest tests/ -v`
Expected: All PASS (132+ tests)

**Step 4: Commit**

```bash
git add tests/
git commit -m "test(oracle): fix remaining test files for scoring optimization"
```

---

## Task 13: Alembic migration (if schema changes needed)

Note: This optimization does NOT change `app/models.py` — the `oracle_feedback` column is `Text` (JSON blob), and the scoring structure changes are all within JSON. No migration needed.

**Step 1: Verify no model changes**

Run: `alembic check` or `alembic revision --autogenerate -m "check" --dry-run`

**Step 2: If no migration needed, skip. Otherwise generate and commit.**

---

## Task 14: Final verification

**Step 1: Run full backend test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 2: Run frontend tests**

Run: `cd frontend && npm test`
Expected: All PASS (frontend doesn't parse oracle feedback structure directly)

**Step 3: Commit any final fixups**

```bash
git add -A
git commit -m "chore: final cleanup for oracle scoring optimization"
```

---

## Summary of Changes

| File | Action | Description |
|------|--------|-------------|
| `oracle/dimension_gen.py` | Modify | Add "可信度" as 3rd fixed dimension |
| `oracle/score_individual.py` | Rewrite | Band-first + evidence + 2 structured suggestions |
| `oracle/dimension_score.py` | Rewrite | Remove caps, add individual IR reference |
| `oracle/constraint_check.py` | **Delete** | Absorbed by fixed dimensions |
| `oracle/oracle.py` | Modify | Remove constraint_check from V2_MODES |
| `app/services/oracle.py` | Major rewrite | Thread-safe logs, penalized_total, score_submission rewrite, batch_score rewrite, parallelize dimension_score |
| `tests/test_oracle_logs_threadsafe.py` | **Create** | Thread-safety tests |
| `tests/test_penalized_total.py` | **Create** | Penalty formula tests |
| `tests/test_oracle_parallel.py` | **Create** | Parallelization tests |
| `tests/test_oracle_v2_router.py` | Modify | New IR format mocks, remove constraint_check tests |
| `tests/test_oracle_v2_service.py` | Modify | New fastest_first + batch_score tests |
| `tests/test_oracle_service.py` | Modify | Update mock data format |
| `tests/test_oracle_v2_integration.py` | Modify | Remove constraint_check, update assertions |
| `tests/test_quality_lifecycle.py` | Modify | Update mock data |
