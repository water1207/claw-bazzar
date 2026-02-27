# Task Schema 优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `acceptance_criteria` 改为必填 `list[str]`、`bounty` 设最低 0.1 USDC 并删除零赏金分支、从 API 响应中移除 `challenge_window_end`。

**Architecture:** Schema 层校验 + 序列化，业务逻辑层删除防护分支，Oracle 子进程适配列表格式，Alembic migration 清空旧数据，测试全量更新。

**Tech Stack:** FastAPI/Pydantic v2, SQLAlchemy, Alembic, pytest, Next.js/TypeScript

---

## Task 1: schemas.py — 三项 Schema 变更

**Files:**
- Modify: `app/schemas.py`

**Step 1: 写失败测试**

在 `tests/test_tasks.py` 末尾添加：

```python
def test_task_create_requires_acceptance_criteria_list(client):
    """acceptance_criteria 必须是列表，不能是字符串或缺失"""
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "fastest_first",
            "threshold": 0.6, "deadline": future(),
            "publisher_id": "pub", "bounty": 1.0,
            "acceptance_criteria": "纯字符串不行",
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 422

def test_task_create_requires_nonempty_criteria(client):
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "fastest_first",
            "threshold": 0.6, "deadline": future(),
            "publisher_id": "pub", "bounty": 1.0,
            "acceptance_criteria": [],
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 422

def test_task_create_bounty_minimum(client):
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "fastest_first",
            "threshold": 0.6, "deadline": future(),
            "publisher_id": "pub", "bounty": 0.05,
            "acceptance_criteria": ["条目1"],
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 422

def test_task_out_no_challenge_window_end(client):
    """TaskOut 不再暴露 challenge_window_end"""
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "quality_first",
            "deadline": future(), "publisher_id": "pub", "bounty": 1.0,
            "acceptance_criteria": ["条目1"],
            "challenge_duration": 3600,
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 201
    assert "challenge_window_end" not in resp.json()

def test_task_acceptance_criteria_roundtrip(client):
    """acceptance_criteria 以 list[str] 写入后读出保持一致"""
    criteria = ["至少5个产品", "每个含官网", "信息真实"]
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "quality_first",
            "deadline": future(), "publisher_id": "pub", "bounty": 1.0,
            "acceptance_criteria": criteria,
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["acceptance_criteria"] == criteria
```

**Step 2: 运行测试，确认全部失败**

```bash
pytest tests/test_tasks.py::test_task_create_requires_acceptance_criteria_list \
       tests/test_tasks.py::test_task_create_requires_nonempty_criteria \
       tests/test_tasks.py::test_task_create_bounty_minimum \
       tests/test_tasks.py::test_task_out_no_challenge_window_end \
       tests/test_tasks.py::test_task_acceptance_criteria_roundtrip -v
```

期望：全部 FAIL

**Step 3: 修改 `app/schemas.py`**

在文件顶部 import 区加：
```python
import json
from pydantic import field_validator
```

替换 `TaskCreate` 类：
```python
class TaskCreate(BaseModel):
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: datetime
    publisher_id: str
    bounty: float
    submission_deposit: Optional[float] = None
    challenge_duration: Optional[int] = None
    acceptance_criteria: list[str]

    @field_validator('acceptance_criteria')
    @classmethod
    def validate_criteria(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("acceptance_criteria must have at least one item")
        return v

    @field_validator('bounty')
    @classmethod
    def bounty_minimum(cls, v: float) -> float:
        if v < 0.1:
            raise ValueError("bounty must be at least 0.1 USDC")
        return v

    @model_validator(mode="after")
    def check_fastest_first_threshold(self) -> "TaskCreate":
        if self.type == TaskType.fastest_first and self.threshold is None:
            raise ValueError("fastest_first tasks require a threshold")
        return self
```

替换 `TaskOut` 类（删除 `challenge_window_end`，`acceptance_criteria` 改为 `list[str]`）：
```python
class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: UTCDatetime
    status: TaskStatus
    winner_submission_id: Optional[str] = None
    publisher_id: Optional[str] = None
    bounty: Optional[float] = None
    payment_tx_hash: Optional[str] = None
    payout_status: PayoutStatus = PayoutStatus.pending
    payout_tx_hash: Optional[str] = None
    payout_amount: Optional[float] = None
    submission_deposit: Optional[float] = None
    challenge_duration: Optional[int] = None
    acceptance_criteria: list[str] = []
    scoring_dimensions: List["ScoringDimensionPublic"] = []
    refund_amount: Optional[float] = None
    refund_tx_hash: Optional[str] = None
    escrow_tx_hash: Optional[str] = None
    created_at: UTCDatetime

    @model_validator(mode='before')
    @classmethod
    def parse_acceptance_criteria(cls, values):
        raw = values.get('acceptance_criteria') if isinstance(values, dict) else getattr(values, 'acceptance_criteria', None)
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                parsed = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                parsed = []
            if isinstance(values, dict):
                values['acceptance_criteria'] = parsed
            else:
                object.__setattr__(values, 'acceptance_criteria', parsed)
        return values

    model_config = {"from_attributes": True}
```

**Step 4: 运行测试，确认通过**

```bash
pytest tests/test_tasks.py::test_task_create_requires_acceptance_criteria_list \
       tests/test_tasks.py::test_task_create_requires_nonempty_criteria \
       tests/test_tasks.py::test_task_create_bounty_minimum \
       tests/test_tasks.py::test_task_out_no_challenge_window_end \
       tests/test_tasks.py::test_task_acceptance_criteria_roundtrip -v
```

期望：全部 PASS

**Step 5: Commit**

```bash
git add app/schemas.py tests/test_tasks.py
git commit -m "feat: acceptance_criteria list[str], bounty >= 0.1, remove challenge_window_end from API"
```

---

## Task 2: router — 序列化写入 + 删除零赏金分支

**Files:**
- Modify: `app/routers/tasks.py`

**Step 1: 修改 `create_task`**

将整个 `create_task` 函数替换为：

```python
import json as _json

@router.post("", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, request: Request, db: Session = Depends(get_db)):
    payment_header = request.headers.get("x-payment")
    if not payment_header:
        return JSONResponse(
            status_code=402,
            content=build_payment_requirements(data.bounty),
        )
    result = verify_payment(payment_header, data.bounty)
    if not result["valid"]:
        reqs = build_payment_requirements(data.bounty)
        reqs["error"] = result.get("reason", "payment verification failed")
        return JSONResponse(status_code=402, content=reqs)
    tx_hash = result.get("tx_hash")

    task_data = data.model_dump()
    task_data['acceptance_criteria'] = _json.dumps(data.acceptance_criteria, ensure_ascii=False)
    task = Task(**task_data, payment_tx_hash=tx_hash)
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        generate_dimensions(db, task)
    except Exception as e:
        print(f"[tasks] dimension generation failed: {e}", flush=True)

    dims = db.query(ScoringDimension).filter(ScoringDimension.task_id == task.id).all()
    result_out = TaskOut.model_validate(task)
    result_out.scoring_dimensions = [
        ScoringDimensionPublic(name=d.name, description=d.description) for d in dims
    ]
    return result_out
```

**Step 2: 运行已有 task 相关测试**

```bash
pytest tests/test_tasks.py -v
```

期望：新增的 5 个测试 PASS，其他测试可能因 `bounty=0` 或 `acceptance_criteria` 格式问题报错（下一步修复）

**Step 3: 删除零赏金测试用例**

在 `tests/test_tasks.py` 中删除整个 `test_create_task_zero_bounty_skips_payment` 函数（约第 136-147 行）。

**Step 4: Commit**

```bash
git add app/routers/tasks.py tests/test_tasks.py
git commit -m "refactor: router serializes acceptance_criteria, removes zero-bounty branch"
```

---

## Task 3: Oracle 服务层 — _parse_criteria 辅助函数

**Files:**
- Modify: `app/services/oracle.py`

**Step 1: 在文件顶部 import 后添加辅助函数**

找到 `app/services/oracle.py` 中 `import json` 或文件顶部 import 区，添加：

```python
def _parse_criteria(raw: str | None) -> list[str]:
    """将数据库中存储的 JSON 字符串反序列化为条目列表。"""
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, ValueError):
        return []
```

**Step 2: 替换三处 acceptance_criteria 传参**

在 `oracle.py` 中搜索所有：
```python
"acceptance_criteria": task.acceptance_criteria or "",
```

全部替换为：
```python
"acceptance_criteria": _parse_criteria(task.acceptance_criteria),
```

共 3 处（`generate_dimensions`、`give_feedback`、`batch_score_submissions` 附近）。

**Step 3: 运行 oracle 服务相关测试**

```bash
pytest tests/test_oracle_v2_service.py -v -x
```

期望：测试中直接构造 `Task(acceptance_criteria="字符串")` 的用例此时仍可运行（`_parse_criteria` 对非 JSON 字符串返回 `[]`），但后续 Task 4 会修正测试数据。

**Step 4: Commit**

```bash
git add app/services/oracle.py
git commit -m "refactor: oracle service uses _parse_criteria to deserialize acceptance_criteria"
```

---

## Task 4: Oracle 脚本 — 格式化列表为编号文本

**Files:**
- Modify: `oracle/gate_check.py`
- Modify: `oracle/dimension_gen.py`
- Modify: `oracle/injection_guard.py`

**Step 1: 修改 `oracle/gate_check.py`**

找到 `run_gate_check` 函数中使用 `acceptance_criteria` 的地方，将接收到的列表格式化为编号文本：

```python
# 在调用 LLM 之前
criteria_raw = input_data.get("acceptance_criteria", [])
if isinstance(criteria_raw, list):
    acceptance_criteria = "\n".join(f"{i+1}. {c}" for i, c in enumerate(criteria_raw))
else:
    acceptance_criteria = str(criteria_raw)
```

然后将 `acceptance_criteria` 传入 prompt template（替换原来的 `input_data.get("acceptance_criteria", "")`）。

**Step 2: 同样修改 `oracle/dimension_gen.py`**

相同逻辑，找到 `acceptance_criteria` 从 input_data 读取的位置，添加列表格式化。

**Step 3: 修改 `oracle/injection_guard.py`**

injection_guard 检测 `acceptance_criteria` 字段时，字段值现在是 `list[str]`，需要拼接后检测：

```python
# 找到 acceptance_criteria 字段的检测逻辑
# 将 list[str] 合并为单一字符串再检测
value = payload.get(field)
if isinstance(value, list):
    value = " ".join(str(v) for v in value)
```

**Step 4: 运行 oracle stub 测试**

```bash
pytest tests/test_oracle_stub.py -v
```

期望：PASS（oracle 脚本本身不变，只是格式化逻辑）

**Step 5: Commit**

```bash
git add oracle/gate_check.py oracle/dimension_gen.py oracle/injection_guard.py
git commit -m "refactor: oracle scripts format acceptance_criteria list to numbered text"
```

---

## Task 5: Scheduler 清理零赏金防护分支

**Files:**
- Modify: `app/scheduler.py`

共 6 处 `if task.bounty and task.bounty > 0:` 需要处理，规则：

- 如果 `if` 块内只有业务逻辑（如调用 `refund_publisher`、`_resolve_via_contract`、`create_challenge_onchain`）→ **删除 `if` 判断，直接执行内部代码**
- 如果有 `task.bounty or 0.0` 的用法 → 改为直接 `task.bounty`（bounty 已保证 >= 0.1）

具体位置（行号供参考，以实际文件为准）：

1. `scheduler.py:142` — `if task.bounty and task.bounty > 0: refund_publisher(...)` → 直接调用
2. `scheduler.py:207` — `if task.bounty and task.bounty > 0:` (escrow lock) → 直接执行
3. `scheduler.py:237` — `if task.bounty and task.bounty > 0 and has_subs:` → 改为 `if has_subs:`
4. `scheduler.py:261` — `if task.bounty and task.bounty > 0:` → 直接调用 `_resolve_via_contract`
5. `scheduler.py:372` — `if task.bounty and task.bounty > 0:` → 直接执行
6. `scheduler.py:499` — `if task.bounty and task.bounty > 0:` → 直接执行

同时将所有 `task.bounty or 0.0` 改为 `task.bounty`（7 处，用编辑器全局替换）。

**Step 1: 运行 scheduler 相关测试（改前基准）**

```bash
pytest tests/test_arbitration.py tests/test_escrow_settlement.py tests/test_refund.py -v
```

记录当前通过情况。

**Step 2: 执行上述修改**

**Step 3: 运行相同测试**

```bash
pytest tests/test_arbitration.py tests/test_escrow_settlement.py tests/test_refund.py -v
```

期望：结果不变或更好（`test_refund.py` 中 `bounty=0` 的用例会失败，下一 Task 修复）

**Step 4: Commit**

```bash
git add app/scheduler.py
git commit -m "refactor: remove zero-bounty guards from scheduler, bounty >= 0.1 guaranteed"
```

---

## Task 6: payout.py 清理零赏金防护

**Files:**
- Modify: `app/services/payout.py`

**Step 1: 修改 `refund_publisher`**

删除第 54 行的零赏金防护：
```python
# 删除这行：
if not task or not task.bounty or task.bounty <= 0:
    return
# 改为：
if not task:
    return
```

**Step 2: 修改 `pay_winner`**

第 80 行：
```python
# 改为：
if not task or not task.winner_submission_id or not task.bounty:
    return
# 保持不变（bounty None 检查保留，防止数据异常）
```

**Step 3: Commit**

```bash
git add app/services/payout.py
git commit -m "refactor: remove bounty <= 0 guard from refund_publisher"
```

---

## Task 7: Alembic Migration — 清空旧 acceptance_criteria 数据

**Files:**
- Create: `alembic/versions/<hash>_clear_acceptance_criteria.py`

**Step 1: 生成 migration**

```bash
alembic revision --autogenerate -m "clear_acceptance_criteria_old_data"
```

**Step 2: 编辑生成的 migration 文件**

在 `upgrade()` 中添加（`autogenerate` 可能生成空内容，手动补充）：

```python
def upgrade() -> None:
    op.execute("UPDATE tasks SET acceptance_criteria = NULL")

def downgrade() -> None:
    pass  # 不可逆，旧数据已清空
```

**Step 3: 应用 migration**

```bash
alembic upgrade head
```

**Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "migration: clear old text acceptance_criteria data"
```

---

## Task 8: 测试文件批量更新

**Files:**
- Modify: `tests/test_oracle_v2_service.py`
- Modify: `tests/test_oracle_v2_router.py`
- Modify: `tests/test_oracle_parallel.py`
- Modify: `tests/test_oracle_v2_integration.py`
- Modify: `tests/test_e2e_oracle_v3.py`
- Modify: `tests/test_refund.py`
- Modify: `tests/test_tasks.py`（policy_violation 测试中 `bounty=0.0`）

**规则 A：直接构造 ORM Task 对象的测试**

`acceptance_criteria="字符串"` → `acceptance_criteria=json.dumps(["字符串"])`

例：
```python
# 改前
Task(..., acceptance_criteria="至少覆盖10个产品", bounty=0, ...)
# 改后
import json
Task(..., acceptance_criteria=json.dumps(["至少覆盖10个产品"]), bounty=0.1, ...)
```

**规则 B：通过 HTTP client 调用 API 的测试**

`"acceptance_criteria": "字符串"` → `"acceptance_criteria": ["字符串"]`
`"bounty": 0` 或 `"bounty": 0.0` → `"bounty": 0.1`

**规则 C：`test_refund.py:239`**

```python
# 改前
task = make_expired_task(db, TaskType.quality_first, bounty=0)
# 改后
task = make_expired_task(db, TaskType.quality_first, bounty=0.1)
```

**Step 1: 更新所有文件（逐文件处理）**

每个文件改完后立即运行该文件的测试，确保无新失败。

**Step 2: 运行全量测试**

```bash
pytest -v
```

期望：全部通过（252 个测试）

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: update acceptance_criteria to list[str], bounty 0 -> 0.1"
```

---

## Task 9: 前端类型和 DevPanel 更新

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/DevPanel.tsx`

**Step 1: 更新 `frontend/lib/api.ts`**

```ts
// 改前
acceptance_criteria: string | null
challenge_window_end: string | null

// 改后（删除 challenge_window_end，acceptance_criteria 改类型）
acceptance_criteria: string[] | null
// challenge_window_end 行删除
```

`createTask` 函数签名中 `acceptance_criteria` 的类型同步更新为 `string[]`。

**Step 2: 更新 `frontend/components/DevPanel.tsx`**

提交时将 textarea 内容转数组：
```ts
// 找到 acceptance_criteria: acceptanceCriteria || null
// 替换为：
acceptance_criteria: acceptanceCriteria
  ? acceptanceCriteria.split('\n').map(s => s.trim()).filter(Boolean)
  : ["默认验收标准"],
```

移除 `challengeCountdown` 对 `challenge_window_end` 的依赖：
```ts
// 删除或注释：
// const challengeCountdown = useCountdown(publishedTask?.challenge_window_end)
```

找到渲染倒计时的 JSX（约第 973 行），删除该 `challenge_window_end` 相关展示块，或改为展示 `challenge_duration` 秒数。

**Step 3: 运行前端测试**

```bash
cd frontend && npm test
```

期望：22 个测试全部通过。

**Step 4: Commit**

```bash
git add frontend/lib/api.ts frontend/components/DevPanel.tsx
git commit -m "feat: frontend accepts acceptance_criteria as string[], removes challenge_window_end"
```

---

## Task 10: 全量验证

**Step 1: 后端全量测试**

```bash
pytest -v
```

期望：全部通过

**Step 2: 前端全量测试**

```bash
cd frontend && npm test && npm run lint
```

**Step 3: 手动冒烟测试（可选）**

启动两个服务：
```bash
uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

在 DevPanel 创建一个 quality_first 任务，`acceptance_criteria` 填多行，确认响应中为数组。

**Step 4: 最终 Commit（如有遗漏）**

```bash
git add -p  # 检查是否有遗漏
```
