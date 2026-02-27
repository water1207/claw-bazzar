# Task Schema 优化设计

日期：2026-02-27
分支：refactor/data-structure

## 背景

对任务发布数据结构进行三项优化：
1. `acceptance_criteria` 从纯文本改为结构化条目列表
2. `bounty` 设置最低下限 0.1 USDC，移除零赏金逻辑
3. `challenge_window_end` 从 API 层移除，仅作内部计算字段

---

## 一、acceptance_criteria 结构化

### 决策

- **存储层**：`models.py` 保持 `TEXT` 列不变，存储 JSON 字符串（`json.dumps(list[str])`）
- **Schema 层**：`TaskCreate.acceptance_criteria` 改为 `list[str]`，必填，至少 1 条
- **Schema 层**：`TaskOut.acceptance_criteria` 改为 `list[str]`，读出时反序列化
- **旧数据**：直接清空，不做兼容处理（migration 清除旧记录）
- **调用方**：Agent 直接传 JSON 数组；DevPanel 前端 textarea 按换行拆分后转数组

### 变更点

**`app/schemas.py`**
```python
class TaskCreate(BaseModel):
    acceptance_criteria: list[str]  # 必填，至少1条

    @field_validator('acceptance_criteria')
    @classmethod
    def validate_criteria(cls, v):
        if not v:
            raise ValueError("acceptance_criteria must have at least one item")
        return v
```

**`app/routers/tasks.py`** — 写库前序列化，读出时反序列化：
```python
import json

task_data = data.model_dump()
task_data['acceptance_criteria'] = json.dumps(data.acceptance_criteria, ensure_ascii=False)
task = Task(**task_data, payment_tx_hash=tx_hash)
```

**`app/schemas.py TaskOut`**
```python
class TaskOut(BaseModel):
    acceptance_criteria: list[str] = []

    @model_validator(mode='before')
    @classmethod
    def parse_criteria(cls, values):
        raw = values.get('acceptance_criteria') if isinstance(values, dict) else getattr(values, 'acceptance_criteria', None)
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(values, dict):
                    values['acceptance_criteria'] = parsed if isinstance(parsed, list) else []
                else:
                    values.acceptance_criteria = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                if isinstance(values, dict):
                    values['acceptance_criteria'] = []
                else:
                    values.acceptance_criteria = []
        return values
```

**`app/services/oracle.py`** — 三处传参改为反序列化后的列表：
```python
import json

def _parse_criteria(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, ValueError):
        return []

# 三处调用点改为：
"acceptance_criteria": _parse_criteria(task.acceptance_criteria),
```

**`oracle/gate_check.py` / `oracle/dimension_gen.py`** — prompt 格式化：
```python
# input_data["acceptance_criteria"] 现在是 list[str]
criteria = input_data.get("acceptance_criteria", [])
if isinstance(criteria, list):
    criteria_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(criteria))
else:
    criteria_text = criteria  # 降级
```

**`frontend/components/DevPanel.tsx`** — 提交时转数组：
```ts
acceptance_criteria: acceptanceCriteria
  .split('\n')
  .map(s => s.trim())
  .filter(Boolean),
```

**Alembic migration** — 清空旧数据：
```python
op.execute("UPDATE tasks SET acceptance_criteria = NULL")
```

---

## 二、bounty 下限 0.1 USDC

### 决策

- `TaskCreate` 加 validator，`bounty < 0.1` 直接报 422
- `routers/tasks.py` 删除 `if data.bounty and data.bounty > 0` 条件判断，所有任务强制走支付
- `scheduler.py` / `services/payout.py` 清除所有 `bounty <= 0` / `bounty and bounty > 0` 防护分支
- 测试中所有 `bounty=0` / `bounty=0.0` 改为 `bounty=0.1`，删除 `test_create_task_zero_bounty_skips_payment`

### 变更点

**`app/schemas.py`**
```python
class TaskCreate(BaseModel):
    bounty: float

    @field_validator('bounty')
    @classmethod
    def bounty_minimum(cls, v):
        if v < 0.1:
            raise ValueError("bounty must be at least 0.1 USDC")
        return v
```

**`app/routers/tasks.py`**
```python
# 删除：if data.bounty and data.bounty > 0:
# 改为直接执行支付逻辑（bounty 已由 validator 保证 >= 0.1）
payment_header = request.headers.get("x-payment")
if not payment_header:
    return JSONResponse(status_code=402, content=build_payment_requirements(data.bounty))
result = verify_payment(payment_header, data.bounty)
if not result["valid"]:
    ...
```

**`app/scheduler.py`** — 删除所有形如：
```python
if task.bounty and task.bounty > 0:   # 删除此判断，直接执行内部逻辑
```

**`app/services/payout.py`**
```python
# 删除：if not task or not task.bounty or task.bounty <= 0: return
# bounty 保证存在且 >= 0.1
```

---

## 三、challenge_window_end 从 API 移除

### 决策

- `Task` model 保留 `challenge_window_end` 列，供调度器内部读写
- `TaskCreate` 删除 `challenge_window_end` 字段（原本就没有，确认）
- `TaskOut` 删除 `challenge_window_end` 字段，不对外暴露
- `scheduler.py` 逻辑不变，继续写入 `task.challenge_window_end`
- `frontend/lib/api.ts` 的 `Task` 类型删除 `challenge_window_end` 字段
- `frontend/components/DevPanel.tsx` 中 `challengeCountdown` 依赖 `challenge_window_end`，需改为调用新增的 `/tasks/{id}/challenge-status` 接口或直接保留该字段仅供内部展示

> **注意**：`challenges.py` 路由中 `task.challenge_window_end` 用于判断挑战窗口是否开放，这是内部判断逻辑，直接读 model 字段，不受 Schema 变更影响。

### 变更点

**`app/schemas.py`**
```python
class TaskOut(BaseModel):
    # 删除：challenge_window_end: Optional[UTCDatetime] = None
```

**`frontend/lib/api.ts`**
```ts
// 删除：challenge_window_end: string | null
```

**`frontend/components/DevPanel.tsx`**
```ts
// challengeCountdown 依赖 challenge_window_end，需评估是否保留或改用其他方式
// 暂时移除倒计时显示，或改为 challenge_window_end 作为内部只读字段单独查询
```

---

## 影响范围汇总

| 文件 | 变更类型 |
|------|---------|
| `app/models.py` | 无变更 |
| `app/schemas.py` | acceptance_criteria 类型、bounty validator、删除 challenge_window_end |
| `app/routers/tasks.py` | 序列化/反序列化、删除零赏金分支 |
| `app/services/oracle.py` | _parse_criteria 辅助函数，3处传参 |
| `app/services/payout.py` | 删除 bounty <= 0 防护 |
| `app/scheduler.py` | 删除多处 bounty > 0 判断 |
| `oracle/gate_check.py` | acceptance_criteria 格式化 |
| `oracle/dimension_gen.py` | acceptance_criteria 格式化 |
| `oracle/injection_guard.py` | acceptance_criteria 检测适配 list |
| `alembic/versions/` | 新增 migration 清空旧 acceptance_criteria |
| `frontend/lib/api.ts` | 类型变更 |
| `frontend/components/DevPanel.tsx` | 提交转数组、移除 challenge_window_end 依赖 |
| `tests/` | bounty=0 → 0.1，删除零赏金测试，更新 acceptance_criteria 格式 |
