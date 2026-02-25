# Oracle V2 评分 Pipeline 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 Oracle V1 Stub 升级为基于 LLM 的真实评分系统，支持维度生成、Gate Check、底层约束检查、独立打分和横向比较评分。

**Architecture:** 保持 subprocess 架构，拆分 oracle 为多个独立脚本（dimension_gen、gate_check、constraint_check、score_individual、dimension_score），通过 oracle.py 路由入口分发。服务层编排 LLM 调用链，scheduler 处理 deadline 后横向评分。

**Tech Stack:** Python/FastAPI, SQLAlchemy/Alembic, Anthropic SDK (subprocess), pytest

**Design doc:** `docs/plans/2026-02-25-oracle-v2-scoring-pipeline-design.md`

---

## Task 1: 数据模型变更 — SubmissionStatus 扩展

**Files:**
- Modify: `app/models.py:21-23`

**Step 1: Write the failing test**

创建 `tests/test_oracle_v2_models.py`:

```python
"""Tests for Oracle V2 model changes."""
import pytest
from app.models import SubmissionStatus


def test_submission_status_has_gate_passed():
    assert SubmissionStatus.gate_passed == "gate_passed"


def test_submission_status_has_gate_failed():
    assert SubmissionStatus.gate_failed == "gate_failed"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_models.py -v`
Expected: FAIL with `AttributeError: gate_passed is not a member of SubmissionStatus`

**Step 3: Write minimal implementation**

In `app/models.py`, update `SubmissionStatus`:

```python
class SubmissionStatus(str, PyEnum):
    pending = "pending"
    gate_passed = "gate_passed"
    gate_failed = "gate_failed"
    scored = "scored"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_oracle_v2_models.py app/models.py
git commit -m "feat: add gate_passed/gate_failed to SubmissionStatus"
```

---

## Task 2: 数据模型变更 — Task.acceptance_criteria

**Files:**
- Modify: `app/models.py:57-78`
- Test: `tests/test_oracle_v2_models.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_models.py`:

```python
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_task_has_acceptance_criteria_column(db):
    task = Task(
        title="Test", description="Desc", type="quality_first",
        deadline="2026-12-31T00:00:00Z", bounty=10.0,
        acceptance_criteria="Must include 10 items"
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    assert task.acceptance_criteria == "Must include 10 items"


def test_task_acceptance_criteria_nullable(db):
    task = Task(
        title="Test", description="Desc", type="fastest_first",
        threshold=0.8, deadline="2026-12-31T00:00:00Z", bounty=5.0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    assert task.acceptance_criteria is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_models.py::test_task_has_acceptance_criteria_column -v`
Expected: FAIL with `TypeError: 'acceptance_criteria' is an invalid keyword argument`

**Step 3: Write minimal implementation**

In `app/models.py`, add to `Task` class after line 78 (`created_at`):

```python
    acceptance_criteria = Column(Text, nullable=True)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_models.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/models.py tests/test_oracle_v2_models.py
git commit -m "feat: add acceptance_criteria to Task model"
```

---

## Task 3: 数据模型变更 — ScoringDimension 表

**Files:**
- Modify: `app/models.py`
- Test: `tests/test_oracle_v2_models.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_models.py`:

```python
from app.models import ScoringDimension


def test_scoring_dimension_create(db):
    task = Task(
        title="Test", description="Desc", type="quality_first",
        deadline="2026-12-31T00:00:00Z", bounty=10.0,
    )
    db.add(task)
    db.commit()

    dim = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="评估提交是否有实质内容",
        weight=0.3, scoring_guidance="高分标准..."
    )
    db.add(dim)
    db.commit()
    db.refresh(dim)

    assert dim.dim_id == "substantiveness"
    assert dim.weight == 0.3
    assert dim.task_id == task.id


def test_task_dimensions_relationship(db):
    task = Task(
        title="Test", description="Desc", type="quality_first",
        deadline="2026-12-31T00:00:00Z", bounty=10.0,
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="desc1", weight=0.5, scoring_guidance="guide1"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="desc2", weight=0.5, scoring_guidance="guide2"
    )
    db.add_all([dim1, dim2])
    db.commit()
    db.refresh(task)

    assert len(task.dimensions) == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_models.py::test_scoring_dimension_create -v`
Expected: FAIL with `ImportError: cannot import name 'ScoringDimension'`

**Step 3: Write minimal implementation**

In `app/models.py`, add import at top:

```python
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
```

Add the `ScoringDimension` class after `Task`:

```python
class ScoringDimension(Base):
    __tablename__ = "scoring_dimensions"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    dim_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    dim_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    weight = Column(Float, nullable=False)
    scoring_guidance = Column(Text, nullable=False)

    task = relationship("Task", backref="dimensions")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_models.py -v`
Expected: All PASS

**Step 5: Run all existing tests to verify no regression**

Run: `pytest -v`
Expected: All existing tests PASS

**Step 6: Commit**

```bash
git add app/models.py tests/test_oracle_v2_models.py
git commit -m "feat: add ScoringDimension model with Task relationship"
```

---

## Task 4: Alembic 迁移

**Files:**
- Create: `alembic/versions/xxxx_add_oracle_v2_fields.py` (auto-generated)

**Step 1: Generate migration**

Run: `alembic revision --autogenerate -m "add oracle v2 fields"`

**Step 2: Review generated migration**

Check that it includes:
- `add_column('tasks', Column('acceptance_criteria', Text(), nullable=True))`
- `create_table('scoring_dimensions', ...)`
- New enum values `gate_passed`, `gate_failed` for `submissionstatus`

**Step 3: Apply migration**

Run: `alembic upgrade head`

**Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "chore: alembic migration for oracle v2 model changes"
```

---

## Task 5: Schema 变更 — TaskCreate + TaskOut

**Files:**
- Modify: `app/schemas.py:36-76`
- Test: `tests/test_oracle_v2_models.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_models.py`:

```python
from app.schemas import TaskCreate, TaskOut, ScoringDimensionPublic


def test_task_create_accepts_acceptance_criteria():
    data = TaskCreate(
        title="Test", description="Desc", type="quality_first",
        deadline="2026-12-31T00:00:00Z", publisher_id="p1", bounty=10.0,
        acceptance_criteria="Must include 10 items"
    )
    assert data.acceptance_criteria == "Must include 10 items"


def test_task_create_acceptance_criteria_optional():
    data = TaskCreate(
        title="Test", description="Desc", type="fastest_first",
        threshold=0.8, deadline="2026-12-31T00:00:00Z",
        publisher_id="p1", bounty=5.0,
    )
    assert data.acceptance_criteria is None


def test_scoring_dimension_public_schema():
    dim = ScoringDimensionPublic(name="实质性", description="评估内容质量")
    assert dim.name == "实质性"
    assert dim.description == "评估内容质量"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_models.py::test_task_create_accepts_acceptance_criteria -v`
Expected: FAIL with `ValidationError` (unexpected field)

**Step 3: Write minimal implementation**

In `app/schemas.py`:

1. Add to `TaskCreate`:
```python
    acceptance_criteria: Optional[str] = None
```

2. Add to `TaskOut`:
```python
    acceptance_criteria: Optional[str] = None
    scoring_dimensions: List["ScoringDimensionPublic"] = []
```

3. Add new schema class before `TaskOut`:
```python
class ScoringDimensionPublic(BaseModel):
    name: str
    description: str

    model_config = {"from_attributes": True}
```

4. Add rebuild at bottom:
```python
TaskOut.model_rebuild()
TaskDetail.model_rebuild()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_models.py -v`
Expected: All PASS

**Step 5: Run all tests**

Run: `pytest -v`
Expected: All PASS (existing tests unchanged)

**Step 6: Commit**

```bash
git add app/schemas.py tests/test_oracle_v2_models.py
git commit -m "feat: add acceptance_criteria and ScoringDimensionPublic schemas"
```

---

## Task 6: LLM Client — oracle/llm_client.py

**Files:**
- Create: `oracle/llm_client.py`
- Create: `tests/test_llm_client.py`

**Step 1: Write the failing test**

Create `tests/test_llm_client.py`:

```python
"""Tests for LLM client wrapper."""
import json
import pytest
from unittest.mock import patch, MagicMock


def test_call_llm_anthropic():
    """call_llm should use anthropic SDK and return text response."""
    import importlib
    import sys

    # We need to import from oracle directory
    sys.path.insert(0, "oracle")
    from llm_client import call_llm
    sys.path.pop(0)

    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"result": "test"}')]

    with patch.dict("os.environ", {"ORACLE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"}):
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            result = call_llm("test prompt", system="test system")

    assert result == '{"result": "test"}'
    MockClient.return_value.messages.create.assert_called_once()
    call_args = MockClient.return_value.messages.create.call_args
    assert call_args.kwargs["messages"] == [{"role": "user", "content": "test prompt"}]
    assert call_args.kwargs["system"] == "test system"


def test_call_llm_unsupported_provider():
    import sys
    sys.path.insert(0, "oracle")
    from llm_client import call_llm
    sys.path.pop(0)

    with patch.dict("os.environ", {"ORACLE_LLM_PROVIDER": "unknown"}):
        with pytest.raises(ValueError, match="Unsupported provider"):
            call_llm("test")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_client'`

**Step 3: Write minimal implementation**

Create `oracle/llm_client.py`:

```python
"""LLM API client wrapper. Default: Anthropic Claude. Configurable via env vars."""
import json
import os


def call_llm(prompt: str, system: str = None) -> str:
    """Call LLM API and return raw text response.

    Env vars:
        ORACLE_LLM_PROVIDER: "anthropic" (default)
        ORACLE_LLM_MODEL: model name (default "claude-sonnet-4-20250514")
        ANTHROPIC_API_KEY: API key for Anthropic
    """
    provider = os.environ.get("ORACLE_LLM_PROVIDER", "anthropic")
    model = os.environ.get("ORACLE_LLM_MODEL", "claude-sonnet-4-20250514")

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def call_llm_json(prompt: str, system: str = None) -> dict:
    """Call LLM and parse response as JSON. Strips markdown code fences if present."""
    raw = call_llm(prompt, system)
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_client.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add oracle/llm_client.py tests/test_llm_client.py
git commit -m "feat: add LLM client wrapper with Anthropic support"
```

---

## Task 7: Oracle 入口重构 — oracle/oracle.py

**Files:**
- Modify: `oracle/oracle.py`
- Test: `tests/test_oracle_stub.py` (verify existing tests still pass)

**Step 1: Write the failing test**

Create `tests/test_oracle_v2_router.py`:

```python
"""Tests for oracle.py mode routing."""
import json
import subprocess
import sys


def test_oracle_legacy_feedback_mode():
    """Existing feedback mode should still work."""
    payload = json.dumps({"mode": "feedback"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "suggestions" in output
    assert len(output["suggestions"]) == 3


def test_oracle_legacy_score_mode():
    """Existing score mode should still work."""
    payload = json.dumps({"mode": "score"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
    assert 0.5 <= output["score"] <= 1.0


def test_oracle_unknown_mode_falls_back_to_legacy():
    """Unknown modes should fall back to legacy score behavior."""
    payload = json.dumps({"mode": "nonexistent"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
```

**Step 2: Run test to verify current behavior**

Run: `pytest tests/test_oracle_v2_router.py -v`
Expected: All PASS (tests describe current behavior)

**Step 3: Refactor oracle.py to support routing**

Replace `oracle/oracle.py`:

```python
#!/usr/bin/env python3
"""Oracle V2 — mode router. Dispatches to sub-modules or falls back to V1 stub."""
import json
import random
import sys

FEEDBACK_SUGGESTIONS = [
    "建议加强代码注释，提高可读性",
    "考虑增加边界条件的处理逻辑",
    "可以优化算法时间复杂度",
    "建议补充单元测试覆盖",
    "接口设计可以更简洁明了",
    "错误处理逻辑需要完善",
    "变量命名建议更具描述性",
    "可以抽取公共逻辑为独立函数",
    "建议增加输入参数校验",
    "文档注释缺失，建议补全",
]

V2_MODES = {}

def _register_v2_modules():
    """Lazy-import V2 modules. Only loaded when needed."""
    global V2_MODES
    if V2_MODES:
        return
    try:
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from dimension_gen import run as dimension_gen_run
        from gate_check import run as gate_check_run
        from constraint_check import run as constraint_check_run
        from score_individual import run as score_individual_run
        from dimension_score import run as dimension_score_run
        V2_MODES = {
            "dimension_gen": dimension_gen_run,
            "gate_check": gate_check_run,
            "constraint_check": constraint_check_run,
            "score_individual": score_individual_run,
            "dimension_score": dimension_score_run,
        }
    except ImportError:
        pass  # V2 modules not yet available, fall back to legacy


def _legacy_handler(payload: dict) -> dict:
    """V1 stub behavior: feedback or score mode."""
    mode = payload.get("mode", "score")
    if mode == "feedback":
        suggestions = random.sample(FEEDBACK_SUGGESTIONS, 3)
        return {"suggestions": suggestions}
    else:
        score = round(random.uniform(0.5, 1.0), 2)
        return {"score": score, "feedback": f"Stub oracle: random score {score}"}


def main():
    payload = json.loads(sys.stdin.read())
    mode = payload.get("mode", "score")

    _register_v2_modules()

    if mode in V2_MODES:
        result = V2_MODES[mode](payload)
    else:
        result = _legacy_handler(payload)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify behavior preserved**

Run: `pytest tests/test_oracle_v2_router.py tests/test_oracle_stub.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add oracle/oracle.py tests/test_oracle_v2_router.py
git commit -m "refactor: oracle.py mode router with V1 fallback"
```

---

## Task 8: 维度生成脚本 — oracle/dimension_gen.py

**Files:**
- Create: `oracle/dimension_gen.py`
- Test: `tests/test_oracle_v2_router.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_router.py`:

```python
from unittest.mock import patch, MagicMock

MOCK_DIMENSIONS = {
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "评估提交是否有实质内容", "weight": 0.3,
         "scoring_guidance": "高分: 有独到见解; 低分: 空洞堆砌"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "评估覆盖度", "weight": 0.3,
         "scoring_guidance": "高分: 覆盖全面; 低分: 遗漏重要方面"},
        {"id": "data_precision", "name": "数据精度", "type": "dynamic",
         "description": "数据准确性", "weight": 0.4,
         "scoring_guidance": "高分: 数据可验证; 低分: 数据模糊"},
    ],
    "rationale": "根据任务需求生成"
}


def test_dimension_gen_mode():
    """dimension_gen mode should call LLM and return dimensions."""
    payload = json.dumps({
        "mode": "dimension_gen",
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "acceptance_criteria": "至少覆盖10个产品",
    })
    with patch("dimension_gen.call_llm_json", return_value=MOCK_DIMENSIONS):
        result = subprocess.run(
            [sys.executable, "oracle/oracle.py"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "dimensions" in output
    assert len(output["dimensions"]) == 3
    assert output["dimensions"][0]["id"] == "substantiveness"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_router.py::test_dimension_gen_mode -v`
Expected: FAIL (module not found or mode falls back to legacy)

**Step 3: Write implementation**

Create `oracle/dimension_gen.py`:

```python
"""Dimension generation — called once when a task is created."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的评分维度生成器。根据任务描述生成评分维度，返回严格JSON。"

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

1. 固定维度（必须包含）:
   - **实质性**: 评估提交是否提供了真正有价值的内容，而非形式完整但实质空洞的堆砌。
   - **完整性**: 评估提交是否覆盖了任务描述中提及的所有方面和需求点，无重大遗漏。

2. 动态维度（根据任务推断，1-3个）:
   - 必须直接来源于任务描述中的显式或隐式需求
   - 维度之间不能有高度重叠
   - 每个维度必须有明确的评判标准描述

3. 权重分配:
   - 所有维度权重总和 = 1
   - 权重反映任务描述中各方面的重要程度
   - 验收标准中反复强调的方面应获得更高权重

4. 总维度数量: 3-5个（含2个固定维度）

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


def run(input_data: dict) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        task_title=input_data.get("task_title", ""),
        task_description=input_data.get("task_description", ""),
        acceptance_criteria=input_data.get("acceptance_criteria", ""),
    )
    return call_llm_json(prompt, system=SYSTEM_PROMPT)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_router.py::test_dimension_gen_mode -v`
Expected: PASS

**Step 5: Commit**

```bash
git add oracle/dimension_gen.py tests/test_oracle_v2_router.py
git commit -m "feat: add dimension_gen oracle module"
```

---

## Task 9: Gate Check 脚本 — oracle/gate_check.py

**Files:**
- Create: `oracle/gate_check.py`
- Test: `tests/test_oracle_v2_router.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_router.py`:

```python
MOCK_GATE_PASS = {
    "overall_passed": True,
    "criteria_checks": [
        {"criteria": "至少覆盖10个产品", "passed": True, "evidence": "共计12个产品"}
    ],
    "summary": "已通过验收"
}

MOCK_GATE_FAIL = {
    "overall_passed": False,
    "criteria_checks": [
        {"criteria": "至少覆盖10个产品", "passed": False,
         "evidence": "仅8个", "revision_hint": "需补充至少2个产品"}
    ],
    "summary": "未通过验收"
}


def test_gate_check_pass():
    payload = json.dumps({
        "mode": "gate_check",
        "task_description": "调研竞品",
        "acceptance_criteria": "至少覆盖10个产品",
        "submission_payload": "共12个产品的调研报告...",
    })
    with patch("gate_check.call_llm_json", return_value=MOCK_GATE_PASS):
        result = subprocess.run(
            [sys.executable, "oracle/oracle.py"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["overall_passed"] is True


def test_gate_check_fail():
    payload = json.dumps({
        "mode": "gate_check",
        "task_description": "调研竞品",
        "acceptance_criteria": "至少覆盖10个产品",
        "submission_payload": "仅8个产品...",
    })
    with patch("gate_check.call_llm_json", return_value=MOCK_GATE_FAIL):
        result = subprocess.run(
            [sys.executable, "oracle/oracle.py"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["overall_passed"] is False
    assert output["criteria_checks"][0]["revision_hint"] is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_router.py::test_gate_check_pass -v`
Expected: FAIL

**Step 3: Write implementation**

Create `oracle/gate_check.py`:

```python
"""Gate Check — verify submission meets acceptance criteria."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的验收检查器。逐条检查提交是否满足验收标准，返回严格JSON。"

PROMPT_TEMPLATE = """## 你的任务
逐条检查提交是否满足发布者设定的验收标准。这是 pass/fail 判断，不涉及质量评分。

## 输入

### 任务描述
{task_description}

### 验收标准
{acceptance_criteria}

### 提交内容
{submission_payload}

## 规则

1. 对每一条验收标准独立判断 pass 或 fail
2. 判断时优先使用可量化的方式:
   - "不少于50条" → 直接计数
   - "每条必须包含邮箱" → 逐条检查字段存在性
3. 对模糊标准使用合理推断:
   - "要有数据支撑" → 检查是否存在量化数据、来源引用
   - "给出可操作建议" → 检查是否有具体执行步骤
4. 任何一条 fail = 整体 fail
5. 对每条判断给出 evidence
6. 对 fail 的条目给出 revision_hint

## 判断尺度
- 偏向宽松: 只要提交明显在尝试满足标准，即使有小瑕疵也 pass
- 边界情况倾向 pass，质量差异留给后续评分阶段区分

## 输出格式 (严格JSON)

{{
  "overall_passed": true/false,
  "criteria_checks": [
    {{
      "criteria": "原文验收标准",
      "passed": true/false,
      "evidence": "判断依据",
      "revision_hint": "（仅fail时）修订建议"
    }}
  ],
  "summary": "一句话总结"
}}"""


def run(input_data: dict) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        task_description=input_data.get("task_description", ""),
        acceptance_criteria=input_data.get("acceptance_criteria", ""),
        submission_payload=input_data.get("submission_payload", ""),
    )
    return call_llm_json(prompt, system=SYSTEM_PROMPT)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_router.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add oracle/gate_check.py tests/test_oracle_v2_router.py
git commit -m "feat: add gate_check oracle module"
```

---

## Task 10: 底层约束检查脚本 — oracle/constraint_check.py

**Files:**
- Create: `oracle/constraint_check.py`
- Test: `tests/test_oracle_v2_router.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_router.py`:

```python
MOCK_CONSTRAINT_FF_PASS = {
    "task_relevance": {"passed": True, "reason": "提交切题"},
    "authenticity": {"passed": True, "reason": "数据可信"},
    "overall_passed": True,
    "rejection_reason": None,
}

MOCK_CONSTRAINT_QF = {
    "submission_label": "Submission_A",
    "task_relevance": {"passed": True, "analysis": "切题", "score_cap": None},
    "authenticity": {"passed": False, "analysis": "数据疑似编造",
                     "flagged_issues": ["来源不可验证"], "score_cap": 40},
    "effective_cap": 40,
}


def test_constraint_check_fastest_first():
    payload = json.dumps({
        "mode": "constraint_check",
        "task_type": "fastest_first",
        "task_title": "Test", "task_description": "Desc",
        "acceptance_criteria": "AC",
        "submission_payload": "content",
    })
    with patch("constraint_check.call_llm_json", return_value=MOCK_CONSTRAINT_FF_PASS):
        result = subprocess.run(
            [sys.executable, "oracle/oracle.py"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
    output = json.loads(result.stdout)
    assert output["overall_passed"] is True


def test_constraint_check_quality_first():
    payload = json.dumps({
        "mode": "constraint_check",
        "task_type": "quality_first",
        "task_title": "Test", "task_description": "Desc",
        "acceptance_criteria": "AC",
        "submission_payload": "content",
        "submission_label": "Submission_A",
    })
    with patch("constraint_check.call_llm_json", return_value=MOCK_CONSTRAINT_QF):
        result = subprocess.run(
            [sys.executable, "oracle/oracle.py"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
    output = json.loads(result.stdout)
    assert output["effective_cap"] == 40
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_router.py::test_constraint_check_fastest_first -v`
Expected: FAIL

**Step 3: Write implementation**

Create `oracle/constraint_check.py`:

```python
"""Constraint check — task relevance + authenticity."""
from llm_client import call_llm_json

SHARED_CONSTRAINTS = """### 约束1: 任务契合度

检查要点:
- 提交的核心内容是否与任务描述的诉求对应
- 是否只满足了字面条件但偏离了任务的真实意图
- 是否只回答了问题的一小部分而忽略核心诉求
- 是否存在"格式正确但内容无关"的情况

判断标准:
- pass: 提交明确在回应任务诉求，即使角度或方式不同
- fail: 提交答非所问、严重偏题、或仅涉及任务边缘内容

### 约束2: 真实性

检查要点:
- 数据是否具体到可验证的程度
- 是否标注了数据来源或获取方式
- 不同数据点之间是否自相矛盾
- 是否存在过于精确但无来源的数据（编造特征）
- 格式正确但内容明显虚假的字段
- 大量数据高度雷同或模板化生成的迹象

判断标准:
- pass: 数据整体可信，即使部分数据无法验证但无明显编造痕迹
- fail: 存在明显编造、伪造、或大面积不可信内容"""

FF_SYSTEM = "你是 Agent Market 的快速验证 Oracle。判断提交是否存在恶意或低质量问题，返回严格JSON。"

FF_PROMPT = """## 你的任务
判断该提交是否存在恶意或低质量问题。这不是质量评分，只是合格性检查。

## 输入

### 任务描述
{task_description}

### 验收标准
{acceptance_criteria}

### 提交内容
{submission_payload}

## 检查项
{constraints}

## 判断尺度
- 偏向宽松: 只拦截明显的恶意/垃圾提交
- 质量平庸但诚实的提交应该 pass

## 输出格式 (严格JSON)

{{
  "task_relevance": {{ "passed": true/false, "reason": "..." }},
  "authenticity": {{ "passed": true/false, "reason": "..." }},
  "overall_passed": true/false,
  "rejection_reason": null
}}"""

QF_SYSTEM = "你是 Agent Market 的质量评分 Oracle，当前执行底层约束检查，返回严格JSON。"

QF_PROMPT = """## 你的任务
检查该提交是否存在任务契合度或真实性问题。你的判断将作为后续维度评分的约束条件。

## 输入

### 任务标题
{task_title}

### 任务描述
{task_description}

### 验收标准
{acceptance_criteria}

### 待检查提交
{submission_label}: {submission_payload}

## 检查项
{constraints}

## 触发后果
- 任务契合度 fail → 所有维度得分上限降至 30
- 真实性 fail → 相关维度得分上限降至 40
- 两者都 fail → 取更严格的上限（30）

## 判断尺度
- 不区分"好"和"更好"，只拦截明显有问题的提交
- 有疑虑但无确切证据时倾向 pass

## 输出格式 (严格JSON)

{{
  "submission_label": "{submission_label}",
  "task_relevance": {{
    "passed": true/false,
    "analysis": "详细分析...",
    "score_cap": null
  }},
  "authenticity": {{
    "passed": true/false,
    "analysis": "详细分析...",
    "flagged_issues": [],
    "score_cap": null
  }},
  "effective_cap": null
}}"""


def run(input_data: dict) -> dict:
    task_type = input_data.get("task_type", "fastest_first")

    if task_type == "fastest_first":
        prompt = FF_PROMPT.format(
            task_description=input_data.get("task_description", ""),
            acceptance_criteria=input_data.get("acceptance_criteria", ""),
            submission_payload=input_data.get("submission_payload", ""),
            constraints=SHARED_CONSTRAINTS,
        )
        return call_llm_json(prompt, system=FF_SYSTEM)
    else:
        label = input_data.get("submission_label", "Submission_A")
        prompt = QF_PROMPT.format(
            task_title=input_data.get("task_title", ""),
            task_description=input_data.get("task_description", ""),
            acceptance_criteria=input_data.get("acceptance_criteria", ""),
            submission_payload=input_data.get("submission_payload", ""),
            submission_label=label,
            constraints=SHARED_CONSTRAINTS,
        )
        return call_llm_json(prompt, system=QF_SYSTEM)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_router.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add oracle/constraint_check.py tests/test_oracle_v2_router.py
git commit -m "feat: add constraint_check oracle module"
```

---

## Task 11: 独立打分脚本 — oracle/score_individual.py

**Files:**
- Create: `oracle/score_individual.py`
- Test: `tests/test_oracle_v2_router.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_router.py`:

```python
MOCK_INDIVIDUAL_SCORE = {
    "dimension_scores": {
        "substantiveness": {"score": 72, "feedback": "内容充实但缺少深度分析"},
        "completeness": {"score": 65, "feedback": "覆盖了大部分需求"},
        "data_precision": {"score": 80, "feedback": "数据精确"},
    },
    "revision_suggestions": [
        "建议增加竞品对比分析",
        "部分数据缺少来源标注",
    ]
}


def test_score_individual():
    payload = json.dumps({
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
    })
    with patch("score_individual.call_llm_json", return_value=MOCK_INDIVIDUAL_SCORE):
        result = subprocess.run(
            [sys.executable, "oracle/oracle.py"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
    output = json.loads(result.stdout)
    assert "dimension_scores" in output
    assert "revision_suggestions" in output
    assert output["dimension_scores"]["substantiveness"]["score"] == 72
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_router.py::test_score_individual -v`
Expected: FAIL

**Step 3: Write implementation**

Create `oracle/score_individual.py`:

```python
"""Individual scoring — score a single submission on all dimensions + provide revision suggestions."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的质量评分 Oracle。对单个提交在各维度独立打分并给出修订建议，返回严格JSON。"

PROMPT_TEMPLATE = """## 你的任务
对单个提交在每个评分维度上独立打分（0-100），并给出修订建议帮助提交者改进。

## 任务信息

### 标题
{task_title}

### 描述
{task_description}

## 评分维度

{dimensions_text}

## 提交内容
{submission_payload}

## 评分流程
1. 对每个维度独立评分（0-100）
2. 给出每个维度的简要反馈
3. 综合所有维度给出2-3条修订建议

## 打分标准
- 90-100: 显著超出预期
- 70-89: 良好完成，有亮点
- 50-69: 基本满足但平庸
- 30-49: 勉强相关但质量差
- 0-29: 几乎无价值

## 输出格式 (严格JSON)

{{
  "dimension_scores": {{
    "dim_id": {{ "score": 0-100, "feedback": "简要反馈" }}
  }},
  "revision_suggestions": ["建议1", "建议2"]
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
    return call_llm_json(prompt, system=SYSTEM_PROMPT)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_router.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add oracle/score_individual.py tests/test_oracle_v2_router.py
git commit -m "feat: add score_individual oracle module"
```

---

## Task 12: 横向评分脚本 — oracle/dimension_score.py

**Files:**
- Create: `oracle/dimension_score.py`
- Test: `tests/test_oracle_v2_router.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_router.py`:

```python
MOCK_DIM_SCORE = {
    "dimension_id": "substantiveness",
    "dimension_name": "实质性",
    "evaluation_focus": "内容深度和独到性",
    "comparative_analysis": "A优于B和C",
    "scores": [
        {"submission": "Submission_A", "raw_score": 85, "cap_applied": False,
         "final_score": 85, "evidence": "深度分析到位"},
        {"submission": "Submission_B", "raw_score": 72, "cap_applied": True,
         "final_score": 40, "evidence": "有价值但真实性存疑"},
        {"submission": "Submission_C", "raw_score": 60, "cap_applied": False,
         "final_score": 60, "evidence": "基本满足"},
    ]
}


def test_dimension_score():
    payload = json.dumps({
        "mode": "dimension_score",
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "dimension": {
            "id": "substantiveness", "name": "实质性",
            "description": "内容质量", "scoring_guidance": "guide",
        },
        "constraint_caps": {
            "Submission_A": None, "Submission_B": 40, "Submission_C": None,
        },
        "submissions": [
            {"label": "Submission_A", "payload": "content A"},
            {"label": "Submission_B", "payload": "content B"},
            {"label": "Submission_C", "payload": "content C"},
        ],
    })
    with patch("dimension_score.call_llm_json", return_value=MOCK_DIM_SCORE):
        result = subprocess.run(
            [sys.executable, "oracle/oracle.py"],
            input=payload, capture_output=True, text=True, timeout=10,
        )
    output = json.loads(result.stdout)
    assert output["dimension_id"] == "substantiveness"
    assert len(output["scores"]) == 3
    assert output["scores"][1]["cap_applied"] is True
    assert output["scores"][1]["final_score"] == 40
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_router.py::test_dimension_score -v`
Expected: FAIL

**Step 3: Write implementation**

Create `oracle/dimension_score.py`:

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

## 底层约束结果（来自 Step 1）

以下提交存在约束上限，该维度得分不得超过 cap 值:
{constraint_caps_text}

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
0-100 分。如果该提交有 score_cap，最终得分不得超过 cap 值。

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
      "cap_applied": false,
      "final_score": 85,
      "evidence": "核心评分依据"
    }}
  ]
}}"""


def _format_caps(caps: dict) -> str:
    lines = []
    for label, cap in caps.items():
        if cap is not None:
            lines.append(f"- {label}: score_cap = {cap}")
        else:
            lines.append(f"- {label}: 无约束")
    return "\n".join(lines) if lines else "无约束"


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
        constraint_caps_text=_format_caps(input_data.get("constraint_caps", {})),
        submissions_text=_format_submissions(input_data.get("submissions", [])),
    )
    return call_llm_json(prompt, system=SYSTEM_PROMPT)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_router.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add oracle/dimension_score.py tests/test_oracle_v2_router.py
git commit -m "feat: add dimension_score oracle module for horizontal comparison"
```

---

## Task 13: 服务层 — 维度生成 + 任务创建集成

**Files:**
- Modify: `app/services/oracle.py`
- Modify: `app/routers/tasks.py`
- Test: `tests/test_oracle_v2_service.py`

**Step 1: Write the failing test**

Create `tests/test_oracle_v2_service.py`:

```python
"""Tests for Oracle V2 service layer."""
import json
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, ScoringDimension, TaskType, TaskStatus

MOCK_DIM_RESULT = json.dumps({
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "内容质量", "weight": 0.3, "scoring_guidance": "guide1"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "覆盖度", "weight": 0.3, "scoring_guidance": "guide2"},
        {"id": "data_precision", "name": "数据精度", "type": "dynamic",
         "description": "准确性", "weight": 0.4, "scoring_guidance": "guide3"},
    ],
    "rationale": "test"
})


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_generate_dimensions(db):
    from app.services.oracle import generate_dimensions

    task = Task(
        title="市场调研", description="调研竞品", type=TaskType.quality_first,
        deadline="2026-12-31T00:00:00Z", bounty=10.0,
        acceptance_criteria="至少覆盖10个产品",
    )
    db.add(task)
    db.commit()

    mock_result = type("R", (), {"stdout": MOCK_DIM_RESULT, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        dims = generate_dimensions(db, task)

    assert len(dims) == 3
    db_dims = db.query(ScoringDimension).filter(ScoringDimension.task_id == task.id).all()
    assert len(db_dims) == 3
    assert db_dims[0].dim_id in ["substantiveness", "completeness", "data_precision"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_service.py::test_generate_dimensions -v`
Expected: FAIL with `ImportError: cannot import name 'generate_dimensions'`

**Step 3: Write implementation**

Add to `app/services/oracle.py`:

```python
from ..models import Submission, Task, SubmissionStatus, TaskStatus, TaskType, ScoringDimension

def generate_dimensions(db: Session, task: Task) -> list:
    """Generate and lock scoring dimensions for a task via LLM."""
    payload = {
        "mode": "dimension_gen",
        "task_title": task.title,
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
    }
    output = _call_oracle(payload)
    dimensions = output.get("dimensions", [])

    for dim_data in dimensions:
        dim = ScoringDimension(
            task_id=task.id,
            dim_id=dim_data["id"],
            name=dim_data["name"],
            dim_type=dim_data["type"],
            description=dim_data["description"],
            weight=dim_data["weight"],
            scoring_guidance=dim_data["scoring_guidance"],
        )
        db.add(dim)
    db.commit()
    return dimensions
```

Update import at top of `app/services/oracle.py`:

```python
from ..models import Submission, Task, SubmissionStatus, TaskStatus, TaskType, ScoringDimension
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_v2_service.py
git commit -m "feat: add generate_dimensions service function"
```

---

## Task 14: 服务层 — fastest_first 提交 (gate_check + constraint_check)

**Files:**
- Modify: `app/services/oracle.py`
- Test: `tests/test_oracle_v2_service.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_service.py`:

```python
from app.models import Submission, SubmissionStatus

MOCK_GATE_PASS = json.dumps({
    "overall_passed": True,
    "criteria_checks": [{"criteria": "AC1", "passed": True, "evidence": "ok"}],
    "summary": "通过"
})

MOCK_CONSTRAINT_FF_PASS = json.dumps({
    "task_relevance": {"passed": True, "reason": "切题"},
    "authenticity": {"passed": True, "reason": "可信"},
    "overall_passed": True, "rejection_reason": None,
})

MOCK_CONSTRAINT_FF_FAIL = json.dumps({
    "task_relevance": {"passed": False, "reason": "偏题"},
    "authenticity": {"passed": True, "reason": "可信"},
    "overall_passed": False, "rejection_reason": "提交偏离任务主题",
})


def test_score_submission_fastest_first_pass(db):
    """fastest_first: gate pass + constraint pass → accepted + close task."""
    from app.services.oracle import score_submission

    task = Task(
        title="Test", description="Desc", type=TaskType.fastest_first,
        threshold=0.7, deadline="2026-12-31T00:00:00Z", bounty=0,
    )
    db.add(task)
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="good content")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    constraint_result = type("R", (), {"stdout": MOCK_CONSTRAINT_FF_PASS, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return gate_result
        return constraint_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        with patch("app.services.oracle.pay_winner"):
            score_submission(db, sub.id, task.id)

    db.refresh(sub)
    db.refresh(task)
    assert sub.status == SubmissionStatus.scored
    assert task.status == TaskStatus.closed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "fastest_first_check"
    assert feedback["passed"] is True


def test_score_submission_fastest_first_constraint_fail(db):
    """fastest_first: gate pass + constraint fail → rejected."""
    from app.services.oracle import score_submission

    task = Task(
        title="Test", description="Desc", type=TaskType.fastest_first,
        threshold=0.7, deadline="2026-12-31T00:00:00Z", bounty=0,
    )
    db.add(task)
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="bad content")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    constraint_result = type("R", (), {"stdout": MOCK_CONSTRAINT_FF_FAIL, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return gate_result
        return constraint_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        score_submission(db, sub.id, task.id)

    db.refresh(sub)
    db.refresh(task)
    assert sub.status == SubmissionStatus.scored
    assert task.status == TaskStatus.open  # Not closed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["passed"] is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_service.py::test_score_submission_fastest_first_pass -v`
Expected: FAIL (current score_submission uses single "score" mode)

**Step 3: Write implementation**

Refactor `score_submission` in `app/services/oracle.py`:

```python
def score_submission(db: Session, submission_id: str, task_id: str) -> None:
    """Score a single submission (fastest_first path): gate_check + constraint_check."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not submission or not task:
        return

    # Step 1: Gate Check
    gate_payload = {
        "mode": "gate_check",
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
        "submission_payload": submission.content,
    }
    gate_result = _call_oracle(gate_payload)

    if not gate_result.get("overall_passed", False):
        submission.oracle_feedback = json.dumps({
            "type": "fastest_first_check",
            "gate_check": gate_result,
            "constraint_check": None,
            "passed": False,
        })
        submission.score = 0.0
        submission.status = SubmissionStatus.scored
        db.commit()
        return

    # Step 2: Constraint Check
    constraint_payload = {
        "mode": "constraint_check",
        "task_type": "fastest_first",
        "task_title": task.title,
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
        "submission_payload": submission.content,
    }
    constraint_result = _call_oracle(constraint_payload)

    passed = constraint_result.get("overall_passed", False)
    submission.oracle_feedback = json.dumps({
        "type": "fastest_first_check",
        "gate_check": gate_result,
        "constraint_check": constraint_result,
        "passed": passed,
    })
    submission.score = 1.0 if passed else 0.0
    submission.status = SubmissionStatus.scored
    db.commit()

    if passed:
        _apply_fastest_first(db, task, submission)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_service.py -v`
Expected: All PASS

**Step 5: Run existing fastest_first tests**

Run: `pytest tests/test_oracle_service.py tests/test_integration.py -v`

Note: Existing tests may need mock adjustments since `score_submission` now calls oracle twice. Fix any failures by updating mocks.

**Step 6: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_v2_service.py
git commit -m "feat: refactor fastest_first to use gate_check + constraint_check"
```

---

## Task 15: 服务层 — quality_first 提交 (gate_check + score_individual)

**Files:**
- Modify: `app/services/oracle.py`
- Test: `tests/test_oracle_v2_service.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_service.py`:

```python
MOCK_GATE_FAIL = json.dumps({
    "overall_passed": False,
    "criteria_checks": [
        {"criteria": "至少10个产品", "passed": False,
         "evidence": "仅8个", "revision_hint": "补充2个"}
    ],
    "summary": "未通过验收"
})

MOCK_INDIVIDUAL_SCORE = json.dumps({
    "dimension_scores": {
        "substantiveness": {"score": 72, "feedback": "较充实"},
        "completeness": {"score": 65, "feedback": "基本覆盖"},
    },
    "revision_suggestions": ["建议增加对比分析", "补充数据来源"]
})


def test_give_feedback_gate_fail(db):
    """quality_first gate fail → gate_failed status, oracle_feedback has failure details."""
    from app.services.oracle import give_feedback

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline="2026-12-31T00:00:00Z", bounty=10.0,
        acceptance_criteria="至少覆盖10个产品",
    )
    db.add(task)
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="仅8个产品")
    db.add(sub)
    db.commit()

    mock_result = type("R", (), {"stdout": MOCK_GATE_FAIL, "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        give_feedback(db, sub.id, task.id)

    db.refresh(sub)
    assert sub.status == SubmissionStatus.gate_failed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "gate_check"
    assert feedback["overall_passed"] is False


def test_give_feedback_gate_pass_then_individual_score(db):
    """quality_first gate pass → score_individual → gate_passed, revision suggestions stored."""
    from app.services.oracle import give_feedback

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline="2026-12-31T00:00:00Z", bounty=10.0,
        acceptance_criteria="至少覆盖10个产品",
    )
    db.add(task)
    db.commit()

    # Create dimensions for the task
    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="内容质量", weight=0.5, scoring_guidance="guide"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="覆盖度", weight=0.5, scoring_guidance="guide"
    )
    db.add_all([dim1, dim2])
    db.commit()

    sub = Submission(task_id=task.id, worker_id="w1", content="12个产品调研")
    db.add(sub)
    db.commit()

    gate_result = type("R", (), {"stdout": MOCK_GATE_PASS, "returncode": 0})()
    individual_result = type("R", (), {"stdout": MOCK_INDIVIDUAL_SCORE, "returncode": 0})()

    call_count = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return gate_result
        return individual_result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        give_feedback(db, sub.id, task.id)

    db.refresh(sub)
    assert sub.status == SubmissionStatus.gate_passed
    feedback = json.loads(sub.oracle_feedback)
    assert feedback["type"] == "individual_scoring"
    assert "revision_suggestions" in feedback
    assert len(feedback["revision_suggestions"]) == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_service.py::test_give_feedback_gate_fail -v`
Expected: FAIL

**Step 3: Write implementation**

Refactor `give_feedback` in `app/services/oracle.py`:

```python
def give_feedback(db: Session, submission_id: str, task_id: str) -> None:
    """quality_first submission: gate_check → score_individual (if pass)."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not submission or not task:
        return

    # Step 1: Gate Check
    gate_payload = {
        "mode": "gate_check",
        "task_description": task.description,
        "acceptance_criteria": task.acceptance_criteria or "",
        "submission_payload": submission.content,
    }
    gate_result = _call_oracle(gate_payload)

    if not gate_result.get("overall_passed", False):
        submission.oracle_feedback = json.dumps({
            "type": "gate_check",
            **gate_result,
        })
        submission.status = SubmissionStatus.gate_failed
        db.commit()
        return

    # Step 2: Individual scoring (score hidden, revision suggestions returned)
    dimensions = db.query(ScoringDimension).filter(
        ScoringDimension.task_id == task_id
    ).all()
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
    score_result = _call_oracle(score_payload)

    submission.oracle_feedback = json.dumps({
        "type": "individual_scoring",
        **score_result,
    })
    submission.status = SubmissionStatus.gate_passed
    db.commit()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_v2_service.py
git commit -m "feat: refactor quality_first to use gate_check + score_individual"
```

---

## Task 16: 服务层 — batch_score_submissions 横向评分

**Files:**
- Modify: `app/services/oracle.py`
- Test: `tests/test_oracle_v2_service.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_service.py`:

```python
MOCK_CONSTRAINT_QF_CLEAN = json.dumps({
    "submission_label": "Submission_A",
    "task_relevance": {"passed": True, "analysis": "ok", "score_cap": None},
    "authenticity": {"passed": True, "analysis": "ok", "flagged_issues": [], "score_cap": None},
    "effective_cap": None,
})

MOCK_DIM_SCORE_SUB = json.dumps({
    "dimension_id": "substantiveness",
    "dimension_name": "实质性",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 85, "cap_applied": False,
         "final_score": 85, "evidence": "good"},
        {"submission": "Submission_B", "raw_score": 70, "cap_applied": False,
         "final_score": 70, "evidence": "ok"},
    ]
})

MOCK_DIM_SCORE_COMP = json.dumps({
    "dimension_id": "completeness",
    "dimension_name": "完整性",
    "evaluation_focus": "focus",
    "comparative_analysis": "A > B",
    "scores": [
        {"submission": "Submission_A", "raw_score": 80, "cap_applied": False,
         "final_score": 80, "evidence": "good"},
        {"submission": "Submission_B", "raw_score": 60, "cap_applied": False,
         "final_score": 60, "evidence": "ok"},
    ]
})


def test_batch_score_submissions_horizontal(db):
    """After deadline: top 3 → constraint check → horizontal scoring → ranking."""
    from app.services.oracle import batch_score_submissions

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline="2026-01-01T00:00:00Z", bounty=10.0,
        acceptance_criteria="至少10个产品",
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="内容质量", weight=0.5, scoring_guidance="guide"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="覆盖度", weight=0.5, scoring_guidance="guide"
    )
    db.add_all([dim1, dim2])
    db.commit()

    # Create 2 gate_passed submissions with individual scores
    sub1 = Submission(
        task_id=task.id, worker_id="w1", content="content A",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"score": 80, "feedback": "good"},
                "completeness": {"score": 75, "feedback": "ok"},
            },
            "revision_suggestions": []
        })
    )
    sub2 = Submission(
        task_id=task.id, worker_id="w2", content="content B",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"score": 60, "feedback": "basic"},
                "completeness": {"score": 55, "feedback": "incomplete"},
            },
            "revision_suggestions": []
        })
    )
    db.add_all([sub1, sub2])
    db.commit()

    # Mock: constraint_check for each sub, then dimension_score for each dim
    responses = [
        type("R", (), {"stdout": MOCK_CONSTRAINT_QF_CLEAN, "returncode": 0})(),  # constraint sub1
        type("R", (), {"stdout": MOCK_CONSTRAINT_QF_CLEAN, "returncode": 0})(),  # constraint sub2
        type("R", (), {"stdout": MOCK_DIM_SCORE_SUB, "returncode": 0})(),        # dim: substantiveness
        type("R", (), {"stdout": MOCK_DIM_SCORE_COMP, "returncode": 0})(),       # dim: completeness
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

    feedback1 = json.loads(sub1.oracle_feedback)
    feedback2 = json.loads(sub2.oracle_feedback)
    assert feedback1["type"] == "scoring"
    assert feedback1["rank"] == 1
    assert feedback2["rank"] == 2
    assert feedback1["weighted_total"] > feedback2["weighted_total"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_service.py::test_batch_score_submissions_horizontal -v`
Expected: FAIL

**Step 3: Write implementation**

Refactor `batch_score_submissions` in `app/services/oracle.py`:

```python
def _get_individual_weighted_total(submission: Submission, dimensions: list) -> float:
    """Calculate weighted total from individual scoring stored in oracle_feedback."""
    if not submission.oracle_feedback:
        return 0.0
    try:
        feedback = json.loads(submission.oracle_feedback)
        if feedback.get("type") != "individual_scoring":
            return 0.0
        dim_scores = feedback.get("dimension_scores", {})
        total = 0.0
        for dim in dimensions:
            score_entry = dim_scores.get(dim.dim_id, {})
            total += score_entry.get("score", 0) * dim.weight
        return total
    except (json.JSONDecodeError, KeyError):
        return 0.0


def batch_score_submissions(db: Session, task_id: str) -> None:
    """Score all gate_passed submissions after deadline: constraint check + horizontal comparison."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    # Collect gate_passed submissions
    passed = db.query(Submission).filter(
        Submission.task_id == task_id,
        Submission.status == SubmissionStatus.gate_passed,
    ).all()

    if not passed:
        # Also check pending (backward compat with V1 tests)
        passed = db.query(Submission).filter(
            Submission.task_id == task_id,
            Submission.status == SubmissionStatus.pending,
        ).all()

    if not passed:
        return

    dimensions = db.query(ScoringDimension).filter(
        ScoringDimension.task_id == task_id
    ).all()

    # If no dimensions (V1 mode / backward compat), fall back to legacy scoring
    if not dimensions:
        for submission in passed:
            output = _call_oracle(_build_payload(task, submission, "score"))
            submission.score = output.get("score", 0.0)
            submission.oracle_feedback = output.get("feedback", submission.oracle_feedback)
            submission.status = SubmissionStatus.scored
        db.commit()
        return

    # Select top 3 by individual score
    scored_subs = sorted(
        passed,
        key=lambda s: _get_individual_weighted_total(s, dimensions),
        reverse=True,
    )[:3]

    # Anonymize
    label_map = {}
    anonymized = []
    for i, sub in enumerate(scored_subs):
        label = f"Submission_{chr(65 + i)}"
        label_map[label] = sub
        anonymized.append({"label": label, "payload": sub.content})

    # Step 1: Constraint check for each submission
    caps = {}
    for anon in anonymized:
        constraint_payload = {
            "mode": "constraint_check",
            "task_type": "quality_first",
            "task_title": task.title,
            "task_description": task.description,
            "acceptance_criteria": task.acceptance_criteria or "",
            "submission_payload": anon["payload"],
            "submission_label": anon["label"],
        }
        result = _call_oracle(constraint_payload)
        caps[anon["label"]] = result.get("effective_cap")

    # Step 2: Horizontal scoring per dimension
    all_scores = {}
    dims_data = [
        {"id": d.dim_id, "name": d.name, "description": d.description,
         "weight": d.weight, "scoring_guidance": d.scoring_guidance}
        for d in dimensions
    ]
    for dim_data in dims_data:
        dim_payload = {
            "mode": "dimension_score",
            "task_title": task.title,
            "task_description": task.description,
            "dimension": dim_data,
            "constraint_caps": caps,
            "submissions": anonymized,
        }
        result = _call_oracle(dim_payload)
        all_scores[dim_data["id"]] = result

    # Step 3: Compute ranking
    ranking = []
    for anon in anonymized:
        label = anon["label"]
        breakdown = {}
        weighted_total = 0.0
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
                weighted_total += entry["final_score"] * dim_data["weight"]
        ranking.append({
            "label": label,
            "dimension_breakdown": breakdown,
            "weighted_total": round(weighted_total, 2),
        })

    ranking.sort(key=lambda x: x["weighted_total"], reverse=True)

    # Write back to submissions
    for rank_idx, entry in enumerate(ranking):
        sub = label_map[entry["label"]]
        sub.oracle_feedback = json.dumps({
            "type": "scoring",
            "constraint_cap": caps.get(entry["label"]),
            "dimension_scores": entry["dimension_breakdown"],
            "weighted_total": entry["weighted_total"],
            "rank": rank_idx + 1,
        })
        sub.score = entry["weighted_total"] / 100.0
        sub.status = SubmissionStatus.scored

    # Mark any remaining gate_passed subs (outside top 3) as scored without horizontal eval
    for sub in passed:
        if sub not in [label_map[a["label"]] for a in anonymized]:
            sub.status = SubmissionStatus.scored
            if not sub.score:
                sub.score = _get_individual_weighted_total(sub, dimensions) / 100.0

    db.commit()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_service.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/services/oracle.py tests/test_oracle_v2_service.py
git commit -m "feat: batch_score_submissions with horizontal comparison for top 3"
```

---

## Task 17: Router 变更 — 任务创建集成维度生成

**Files:**
- Modify: `app/routers/tasks.py`
- Modify: `app/schemas.py`
- Test: `tests/test_oracle_v2_api.py`

**Step 1: Write the failing test**

Create `tests/test_oracle_v2_api.py`:

```python
"""API tests for Oracle V2 features."""
import json
from unittest.mock import patch
from tests.conftest import *  # reuse conftest fixtures

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}

MOCK_DIM_GEN_STDOUT = json.dumps({
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "内容质量", "weight": 0.4, "scoring_guidance": "guide1"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "覆盖度", "weight": 0.3, "scoring_guidance": "guide2"},
        {"id": "precision", "name": "精度", "type": "dynamic",
         "description": "数据准确", "weight": 0.3, "scoring_guidance": "guide3"},
    ],
    "rationale": "test"
})


def test_create_task_with_acceptance_criteria(client):
    """Creating a task with acceptance_criteria should trigger dimension generation."""
    mock_result = type("R", (), {"stdout": MOCK_DIM_GEN_STDOUT, "returncode": 0})()
    with PAYMENT_MOCK, \
         patch("app.services.oracle.subprocess.run", return_value=mock_result):
        resp = client.post("/tasks", json={
            "title": "调研", "description": "调研竞品",
            "type": "quality_first", "deadline": "2026-12-31T00:00:00Z",
            "publisher_id": "p1", "bounty": 10.0,
            "acceptance_criteria": "至少覆盖10个产品",
        }, headers=PAYMENT_HEADERS)

    assert resp.status_code == 201
    data = resp.json()
    assert data["acceptance_criteria"] == "至少覆盖10个产品"
    assert len(data["scoring_dimensions"]) == 3
    assert data["scoring_dimensions"][0]["name"] == "实质性"
    # weight and scoring_guidance should NOT be in public response
    assert "weight" not in data["scoring_dimensions"][0]
    assert "scoring_guidance" not in data["scoring_dimensions"][0]


def test_create_task_without_acceptance_criteria(client):
    """Tasks without acceptance_criteria should still work (no dimensions generated)."""
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "Test", "description": "Desc",
            "type": "fastest_first", "threshold": 0.8,
            "deadline": "2026-12-31T00:00:00Z",
            "publisher_id": "p1", "bounty": 5.0,
        }, headers=PAYMENT_HEADERS)

    assert resp.status_code == 201
    data = resp.json()
    assert data["acceptance_criteria"] is None
    assert data["scoring_dimensions"] == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_api.py::test_create_task_with_acceptance_criteria -v`
Expected: FAIL

**Step 3: Write implementation**

Update `app/routers/tasks.py`:

```python
from ..services.oracle import generate_dimensions
from ..models import Task, TaskStatus, TaskType, Submission, ScoringDimension
from ..schemas import TaskCreate, TaskOut, TaskDetail, SubmissionOut, ScoringDimensionPublic
```

In `create_task`, after `db.refresh(task)`:

```python
    # Generate scoring dimensions if acceptance_criteria provided
    if task.acceptance_criteria:
        try:
            generate_dimensions(db, task)
        except Exception as e:
            print(f"[tasks] dimension generation failed: {e}", flush=True)

    # Attach dimensions to response
    dims = db.query(ScoringDimension).filter(ScoringDimension.task_id == task.id).all()
    result = TaskOut.model_validate(task)
    result.scoring_dimensions = [
        ScoringDimensionPublic(name=d.name, description=d.description) for d in dims
    ]
    return result
```

Update `get_task` to include dimensions:

```python
    dims = db.query(ScoringDimension).filter(ScoringDimension.task_id == task_id).all()
    result.scoring_dimensions = [
        ScoringDimensionPublic(name=d.name, description=d.description) for d in dims
    ]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_api.py -v`
Expected: All PASS

**Step 5: Run all existing tests**

Run: `pytest -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add app/routers/tasks.py app/schemas.py tests/test_oracle_v2_api.py
git commit -m "feat: integrate dimension generation into task creation API"
```

---

## Task 18: Scheduler 适配 — quality_first lifecycle 更新

**Files:**
- Modify: `app/scheduler.py:53-101`
- Test: `tests/test_oracle_v2_service.py`

**Step 1: Write the failing test**

Add to `tests/test_oracle_v2_service.py`:

```python
from app.scheduler import quality_first_lifecycle
from app.models import TaskStatus


def test_lifecycle_phase1_scoring_with_gate_passed_subs(db):
    """Phase 1: deadline expired → scoring, should use gate_passed subs."""
    from datetime import datetime, timezone

    task = Task(
        title="调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2025, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        status=TaskStatus.open,
        acceptance_criteria="至少10个产品",
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="内容质量", weight=0.5, scoring_guidance="guide"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="覆盖度", weight=0.5, scoring_guidance="guide"
    )
    db.add_all([dim1, dim2])
    db.commit()

    sub = Submission(
        task_id=task.id, worker_id="w1", content="content",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"score": 80, "feedback": "good"},
                "completeness": {"score": 70, "feedback": "ok"},
            },
            "revision_suggestions": []
        })
    )
    db.add(sub)
    db.commit()

    # Mock constraint + dimension scoring calls
    constraint_resp = json.dumps({
        "submission_label": "Submission_A",
        "task_relevance": {"passed": True, "analysis": "ok", "score_cap": None},
        "authenticity": {"passed": True, "analysis": "ok", "flagged_issues": [], "score_cap": None},
        "effective_cap": None,
    })
    dim_score_resp = json.dumps({
        "dimension_id": "substantiveness",
        "scores": [{"submission": "Submission_A", "raw_score": 85,
                     "cap_applied": False, "final_score": 85, "evidence": "good"}]
    })
    dim_score_resp2 = json.dumps({
        "dimension_id": "completeness",
        "scores": [{"submission": "Submission_A", "raw_score": 75,
                     "cap_applied": False, "final_score": 75, "evidence": "ok"}]
    })
    responses = [
        type("R", (), {"stdout": constraint_resp, "returncode": 0})(),
        type("R", (), {"stdout": dim_score_resp, "returncode": 0})(),
        type("R", (), {"stdout": dim_score_resp2, "returncode": 0})(),
    ]
    call_idx = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_idx
        result = responses[call_idx]
        call_idx += 1
        return result

    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess), \
         patch("app.services.escrow.create_challenge_onchain", return_value="0xtx"):
        quality_first_lifecycle(db=db)

    db.refresh(task)
    db.refresh(sub)
    assert task.status in (TaskStatus.scoring, TaskStatus.challenge_window)
    assert sub.status == SubmissionStatus.scored
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle_v2_service.py::test_lifecycle_phase1_scoring_with_gate_passed_subs -v`
Expected: FAIL (current lifecycle expects `pending` status submissions)

**Step 3: Write implementation**

In `app/scheduler.py`, update Phase 2 (`scoring → challenge_window`). Change the `pending_count` query to also check for `gate_passed`:

```python
            pending_count = db.query(Submission).filter(
                Submission.task_id == task.id,
                Submission.status.in_([SubmissionStatus.pending, SubmissionStatus.gate_passed]),
            ).count()
```

Note: `batch_score_submissions` already handles both `gate_passed` and `pending` (backward compat). The scheduler just needs to check both statuses.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle_v2_service.py -v`
Expected: All PASS

**Step 5: Run all scheduler tests**

Run: `pytest tests/test_scheduler.py tests/test_quality_lifecycle.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add app/scheduler.py tests/test_oracle_v2_service.py
git commit -m "feat: scheduler supports gate_passed submissions in lifecycle"
```

---

## Task 19: 修复现有测试适配

**Files:**
- Modify: Various test files as needed
- Run: `pytest -v`

**Step 1: Run full test suite**

Run: `pytest -v`

Identify any failures caused by:
- `score_submission` now calling oracle twice (gate_check + constraint_check)
- `give_feedback` now setting `gate_passed`/`gate_failed` instead of `pending`
- `batch_score_submissions` new flow for submissions with dimensions

**Step 2: Fix each failure**

Common fixes:
- Update oracle subprocess mocks to return gate_check JSON format
- Update status assertions from `pending` to `gate_passed`/`gate_failed`
- Add second mock response for constraint_check in fastest_first tests

**Step 3: Run full test suite again**

Run: `pytest -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/
git commit -m "fix: update existing tests for Oracle V2 flow"
```

---

## Task 20: 端到端集成测试

**Files:**
- Create: `tests/test_oracle_v2_integration.py`

**Step 1: Write integration test — quality_first full lifecycle**

```python
"""End-to-end integration test for Oracle V2 quality_first lifecycle."""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, ScoringDimension,
    TaskType, TaskStatus, SubmissionStatus,
)
from app.services.oracle import generate_dimensions, give_feedback, batch_score_submissions
from app.scheduler import quality_first_lifecycle


def test_quality_first_full_lifecycle():
    """T0 create → T1 dimensions → T2 submissions + gate + individual score → T3 horizontal score."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # T0: Create task
    task = Task(
        title="市场调研", description="调研竞品", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=100.0,
        acceptance_criteria="至少覆盖10个产品", max_revisions=3,
    )
    db.add(task)
    db.commit()

    # T1: Generate dimensions
    dim_gen_result = type("R", (), {"stdout": json.dumps({
        "dimensions": [
            {"id": "substantiveness", "name": "实质性", "type": "fixed",
             "description": "内容质量", "weight": 0.5, "scoring_guidance": "guide"},
            {"id": "completeness", "name": "完整性", "type": "fixed",
             "description": "覆盖度", "weight": 0.5, "scoring_guidance": "guide"},
        ], "rationale": "test"
    }), "returncode": 0})()
    with patch("app.services.oracle.subprocess.run", return_value=dim_gen_result):
        generate_dimensions(db, task)
    assert db.query(ScoringDimension).filter(ScoringDimension.task_id == task.id).count() == 2

    # T2: Submit 3 submissions
    gate_pass = json.dumps({
        "overall_passed": True,
        "criteria_checks": [{"criteria": "AC", "passed": True, "evidence": "ok"}],
        "summary": "通过"
    })
    individual_scores = [
        json.dumps({"dimension_scores": {"substantiveness": {"score": 85, "feedback": "好"},
                     "completeness": {"score": 80, "feedback": "好"}}, "revision_suggestions": ["建议A"]}),
        json.dumps({"dimension_scores": {"substantiveness": {"score": 70, "feedback": "中"},
                     "completeness": {"score": 65, "feedback": "中"}}, "revision_suggestions": ["建议B"]}),
        json.dumps({"dimension_scores": {"substantiveness": {"score": 60, "feedback": "弱"},
                     "completeness": {"score": 55, "feedback": "弱"}}, "revision_suggestions": ["建议C"]}),
    ]

    subs = []
    for i in range(3):
        sub = Submission(task_id=task.id, worker_id=f"w{i}", content=f"content {i}", revision=1)
        db.add(sub)
        db.commit()

        call_count = 0
        def mock_sub(*args, idx=i, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return type("R", (), {"stdout": gate_pass, "returncode": 0})()
            return type("R", (), {"stdout": individual_scores[idx], "returncode": 0})()

        with patch("app.services.oracle.subprocess.run", side_effect=mock_sub):
            give_feedback(db, sub.id, task.id)
        db.refresh(sub)
        assert sub.status == SubmissionStatus.gate_passed
        subs.append(sub)

    # T3: Deadline passes → horizontal scoring
    task.deadline = datetime(2025, 1, 1, tzinfo=timezone.utc)
    task.status = TaskStatus.open
    db.commit()

    constraint_clean = json.dumps({
        "submission_label": "X", "effective_cap": None,
        "task_relevance": {"passed": True, "analysis": "ok", "score_cap": None},
        "authenticity": {"passed": True, "analysis": "ok", "flagged_issues": [], "score_cap": None},
    })
    dim_sub = json.dumps({"dimension_id": "substantiveness", "scores": [
        {"submission": "Submission_A", "raw_score": 90, "cap_applied": False, "final_score": 90, "evidence": "best"},
        {"submission": "Submission_B", "raw_score": 70, "cap_applied": False, "final_score": 70, "evidence": "mid"},
        {"submission": "Submission_C", "raw_score": 55, "cap_applied": False, "final_score": 55, "evidence": "low"},
    ]})
    dim_comp = json.dumps({"dimension_id": "completeness", "scores": [
        {"submission": "Submission_A", "raw_score": 85, "cap_applied": False, "final_score": 85, "evidence": "best"},
        {"submission": "Submission_B", "raw_score": 65, "cap_applied": False, "final_score": 65, "evidence": "mid"},
        {"submission": "Submission_C", "raw_score": 50, "cap_applied": False, "final_score": 50, "evidence": "low"},
    ]})

    responses = [
        type("R", (), {"stdout": constraint_clean, "returncode": 0})(),  # constraint sub0
        type("R", (), {"stdout": constraint_clean, "returncode": 0})(),  # constraint sub1
        type("R", (), {"stdout": constraint_clean, "returncode": 0})(),  # constraint sub2
        type("R", (), {"stdout": dim_sub, "returncode": 0})(),           # dim: substantiveness
        type("R", (), {"stdout": dim_comp, "returncode": 0})(),          # dim: completeness
    ]
    call_idx = 0
    def mock_batch(*args, **kwargs):
        nonlocal call_idx
        r = responses[call_idx]
        call_idx += 1
        return r

    with patch("app.services.oracle.subprocess.run", side_effect=mock_batch), \
         patch("app.services.escrow.create_challenge_onchain", return_value="0xtx"):
        quality_first_lifecycle(db=db)

    db.refresh(task)
    for s in subs:
        db.refresh(s)

    assert task.status in (TaskStatus.scoring, TaskStatus.challenge_window)
    assert subs[0].status == SubmissionStatus.scored
    feedback = json.loads(subs[0].oracle_feedback)
    assert feedback["type"] == "scoring"
    assert feedback["rank"] == 1

    db.close()
```

**Step 2: Run integration test**

Run: `pytest tests/test_oracle_v2_integration.py -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/test_oracle_v2_integration.py
git commit -m "test: end-to-end integration test for Oracle V2 quality_first lifecycle"
```

---

## Task 21: CLAUDE.md 更新

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

Add new env vars, update oracle description, add new submission statuses.

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for Oracle V2"
```

---

## Summary

| Task | Description | Estimated LLM Calls | Dependencies |
|------|-------------|---------------------|--------------|
| 1-3 | Data model changes | 0 | None |
| 4 | Alembic migration | 0 | 1-3 |
| 5 | Schema changes | 0 | 1-3 |
| 6 | LLM client | 0 | None |
| 7 | Oracle entry refactor | 0 | None |
| 8 | dimension_gen script | 0 | 6, 7 |
| 9 | gate_check script | 0 | 6, 7 |
| 10 | constraint_check script | 0 | 6, 7 |
| 11 | score_individual script | 0 | 6, 7 |
| 12 | dimension_score script | 0 | 6, 7 |
| 13 | Service: dimension gen | 0 | 1-3, 8 |
| 14 | Service: fastest_first | 0 | 9, 10 |
| 15 | Service: quality_first | 0 | 9, 11 |
| 16 | Service: batch scoring | 0 | 10, 12 |
| 17 | Router: task creation | 0 | 5, 13 |
| 18 | Scheduler adaptation | 0 | 16 |
| 19 | Fix existing tests | 0 | 14, 15 |
| 20 | Integration test | 0 | All above |
| 21 | CLAUDE.md update | 0 | All above |

**Parallelizable groups:**
- Tasks 1-3 (models) + Tasks 6-7 (oracle infra) can run in parallel
- Tasks 8-12 (oracle modules) can all run in parallel after 6-7
- Tasks 13-16 (service layer) can partially parallelize (13 independent of 14-16)
