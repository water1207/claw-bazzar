---
name: e2e-test
description: 端到端集成测试。启动前后端服务，注册用户，依次测试 fastest_first 和 quality_first 完整生命周期（发布→提交→Gate Check→修订→评分→挑战窗口），验证 Oracle V2 全链路。
---

# E2E 集成测试技能

对 Claw Bazzar 平台进行端到端真实流程测试，覆盖两种任务类型的完整生命周期。

## 前置条件

- `.env` 文件中已配置 `ANTHROPIC_API_KEY`（或 SiliconFlow 等 OpenAI 兼容 API）
- `frontend/.env.local` 中有测试钱包私钥
- 依赖已安装（`pip install -e ".[dev]"` + `cd frontend && npm install`）

## 工作流程

### 步骤一：环境准备

1. 停止占用 8000/3000 端口的进程
2. 删除 Next.js 锁文件（如有残留）
3. **不要删除数据库** — 保留历史数据，oracle logs API 默认只返回最新 5 个任务的日志

```bash
lsof -ti:8000 | xargs kill 2>/dev/null
lsof -ti:3000 | xargs kill 2>/dev/null
rm -f frontend/.next/dev/lock
```

> 如需全新环境，可手动 `rm -f market.db`，但通常不需要。

### 步骤二：启动服务

后台启动后端和前端：

```bash
source .env && uvicorn app.main:app --port 8000  # 后台运行
cd frontend && npm run dev                        # 后台运行
```

等待 3-5 秒后验证**两个服务**均就绪：

```bash
# 后端
curl -s http://localhost:8000/tasks        # 应返回 JSON 数组
# 前端
curl -s -o /dev/null -w '%{http_code}' http://localhost:3000  # 应返回 200
```

### 步骤三：注册测试用户

注册 1 个 publisher + 2-3 个 worker，记录返回的 ID。

每次测试使用不同的 nickname 后缀（如 `_t1`、`_t2`），避免与历史数据冲突。

```bash
# Publisher
curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname":"pub_t1","wallet":"0xPub_t1","role":"publisher"}'

# Workers
curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname":"Alice_t1","wallet":"0xAlice_t1","role":"worker"}'

curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname":"Bob_t1","wallet":"0xBob_t1","role":"worker"}'
```

保存每个用户返回的 `id` 字段供后续步骤使用。

### 步骤四：测试 fastest_first 流程

#### 4.1 发布任务

- `type`: `fastest_first`
- `threshold`: `0.8`
- `bounty`: `0`（免支付）
- `deadline`: 当前时间 + 10 分钟
- **必须包含 `acceptance_criteria`**

**注意**: 使用 Python `urllib` 发送请求，避免 shell 转义 JSON 换行符的问题。

```python
python3 -c "
import json, urllib.request
data = {
    'title': '列出3种编程语言',
    'description': '列出3种流行的编程语言及其主要用途',
    'type': 'fastest_first',
    'threshold': 0.8,
    'max_revisions': None,
    'deadline': '<DEADLINE>',
    'publisher_id': '<PUBLISHER_ID>',
    'bounty': 0,
    'acceptance_criteria': '1. 至少列出3种编程语言\n2. 每种必须包含语言名称和主要用途'
}
req = urllib.request.Request('http://localhost:8000/tasks',
    data=json.dumps(data).encode(),
    headers={'Content-Type': 'application/json'}, method='POST')
resp = urllib.request.urlopen(req)
t = json.loads(resp.read())
print(json.dumps(t, indent=2, ensure_ascii=False))
"
```

**验证点：**
- 返回中 `acceptance_criteria` 不为 null
- `status` = `open`

#### 4.2 提交不合格内容

提交一个明显不满足 acceptance_criteria 的内容（如只列1种语言）。

等待 30-60 秒后检查 submission 状态。

**验证点：**
- `status` = `scored`，`score` = `0.0`
- `oracle_feedback` 包含 `gate_check` 结果，`overall_passed` = `false`
- gate_check 的 criteria_checks 中相应条目为 `passed: false`

#### 4.3 提交合格内容

用另一个 worker 提交满足所有 acceptance_criteria 的内容。

等待 30-60 秒后检查。

**验证点：**
- `status` = `scored`，`score` = `1.0`
- `oracle_feedback` 中 `gate_check.overall_passed` = `true`，`constraint_check.overall_passed` = `true`
- Task `status` 变为 `closed`，`winner_submission_id` 指向该提交

### 步骤五：测试 quality_first 流程

#### 5.1 发布任务

- `type`: `quality_first`
- `threshold`: null
- `max_revisions`: `3`
- `bounty`: `0`
- `deadline`: 当前时间 + **5 分钟**（给提交和 oracle 处理留足时间）
- **必须包含 `acceptance_criteria`**

```python
python3 -c "
import json, urllib.request
data = {
    'title': '推荐5本科幻小说',
    'description': '推荐5本值得一读的科幻小说，每本需包含书名、作者、出版年份和50字以内推荐理由',
    'type': 'quality_first',
    'threshold': None,
    'max_revisions': 3,
    'deadline': '<DEADLINE>',
    'publisher_id': '<PUBLISHER_ID>',
    'bounty': 0,
    'acceptance_criteria': '1. 必须恰好推荐5本书\n2. 每本必须包含书名、作者、出版年份\n3. 每本必须有50字以内的推荐理由\n4. 推荐的书必须是真实存在的科幻小说'
}
req = urllib.request.Request('http://localhost:8000/tasks',
    data=json.dumps(data).encode(),
    headers={'Content-Type': 'application/json'}, method='POST')
resp = urllib.request.urlopen(req)
t = json.loads(resp.read())
print(json.dumps(t, indent=2, ensure_ascii=False))
"
```

**验证点：**
- `acceptance_criteria` 已存储
- `scoring_dimensions` 非空（Oracle 自动生成 2+N 个维度）
- 维度中应包含 fixed 类型（如"实质性"、"完整性"）和 dynamic 类型

#### 5.2 提交不合格内容（Gate Check 拦截）

提交一个不满足 acceptance_criteria 的内容（如只推荐3本书）。

等待 30-60 秒后检查。

**验证点：**
- `status` = `gate_failed`
- `oracle_feedback` 类型为 `gate_check`，`overall_passed` = `false`
- criteria_checks 中指出具体哪条不满足，并提供 `revision_hint`

#### 5.3 修订提交（Gate Check 通过 + Individual Scoring）

同一 worker 提交修订版（满足全部 criteria），系统自动 revision +1。

等待 40-60 秒（gate_check + score_individual 两次 LLM 调用）。

**验证点：**
- `status` = `gate_passed`（非 scored）
- `oracle_feedback` 类型为 `individual_scoring`
- 包含各维度分数（`dimension_scores`）和 `revision_suggestions`
- **分数此时对 API 不可见**（`score` 返回 null）

#### 5.4 第二个 worker 提交

用另一个 worker 提交不同内容。如果 Gate Check 失败则修订后重新提交。

**重要**: 确保两个 worker 的提交都在 deadline 前完成 oracle 处理（状态变为 `gate_passed`）。如果 deadline 临近而 oracle 还在处理，可能触发竞态问题。

#### 5.5 等待 Deadline + Batch Scoring

Deadline 过后 scheduler 每分钟运行一次，需等待多个 tick：

- **Tick 1**: `open` → `scoring`（仅状态转换，不调 batch_score）
- **Tick 2**: Phase 2 检查 — 如果还有 `pending` submission 等待 oracle 处理则跳过；如果所有 oracle 处理完毕（`gate_passed` / `gate_failed`），调用 `batch_score_submissions()`
- **Tick 3**: 所有提交已 `scored`，选 winner → `challenge_window`

预计等待 5-8 分钟（deadline 5分钟 + 2-3 个 scheduler 周期）。

每 30 秒轮询任务状态直到变为 `challenge_window`。

**验证点：**
- 所有 `gate_passed` 提交变为 `scored`
- `oracle_feedback` 类型为 `scoring`，包含：
  - `constraint_cap`（可为 null）
  - `dimension_scores`（每维度 raw_score / final_score）
  - `weighted_total`（加权总分）
  - `rank`（排名）
- Task `winner_submission_id` 指向 rank 1 的提交
- Task `status` = `challenge_window`

### 步骤六：验证 Oracle Logs

```bash
# 默认返回最新 5 个任务的日志（无需手动清理历史）
curl -s 'http://localhost:8000/internal/oracle-logs'

# 只看最近 1 个任务的日志
curl -s 'http://localhost:8000/internal/oracle-logs?task_count=1'
```

**验证点：**
- 日志按时间倒序，自动过滤到最近 N 个任务
- 每条包含：`timestamp`、`mode`、`task_id`、`submission_id`、`worker_id`、`worker_nickname`、`total_tokens`、`duration_ms`
- quality_first 任务应有以下 mode 序列：
  1. `dimension_gen`（1次，任务创建时）
  2. `gate_check`（每次提交 1 次）
  3. `score_individual`（gate_passed 的提交各 1 次）
  4. `constraint_check`（batch scoring 阶段，top 3 各 1 次）
  5. `dimension_score`（batch scoring 阶段，每维度 1 次）
- fastest_first 任务应有：`gate_check` + `constraint_check`

### 步骤七：验证前端页面

打开浏览器访问或 curl 检查前端关键页面：

```bash
# 首页可访问
curl -s -o /dev/null -w '%{http_code}' http://localhost:3000

# DevPanel 可访问
curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/dev

# API 代理正常（前端 /api/* → 后端 :8000）
curl -s http://localhost:3000/api/tasks | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} tasks via frontend proxy')"
```

**验证点：**
- 首页和 DevPanel 均返回 200
- 前端 API 代理正常转发到后端

### 步骤八：清理

```bash
lsof -ti:8000 | xargs kill 2>/dev/null
lsof -ti:3000 | xargs kill 2>/dev/null
```

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `Task deadline has passed` | deadline 太短，来不及提交 | quality_first 至少设 5 分钟，fastest_first 至少 10 分钟 |
| submission 卡在 `pending` | Oracle LLM 调用慢或报错 | 等待 40-60 秒；如果 gate 已过但 score_individual 失败，Bug 已修复会自动标为 `gate_passed` |
| `Unable to acquire lock` | Next.js 锁文件残留 | `rm -f frontend/.next/dev/lock` |
| gate_check 判定不符预期 | LLM 判断有时有争议 | 属正常行为，可调整提交内容使结果更明确 |
| batch scoring 不触发 | scheduler 需等所有 oracle 处理完 | deadline 过后最多等 3 个 tick（3 分钟） |
| nickname 冲突 | 历史数据中已有同名用户 | 每次测试使用不同后缀（`_t1`、`_t2`） |
| JSON 换行符导致 curl 报错 | shell 转义 `\n` 问题 | 使用 Python `urllib` 发送请求而非 curl |
| 需要全新环境 | 历史数据干扰测试 | 手动 `rm -f market.db` 后重启服务 |

## Scheduler 生命周期说明

quality_first 任务在 deadline 后经过多个 scheduler tick 完成评分：

```
Tick 1: Phase 1 — open → scoring（仅转状态）
Tick 2: Phase 2 — 检查是否所有 oracle 后台任务完成
         ├─ 有 pending + 有 gated → 等待
         ├─ 有 gate_passed → 调用 batch_score
         └─ 全部 scored → 选 winner → challenge_window
Tick 3: 如 Tick 2 调了 batch_score → 再次检查 → 转 challenge_window
```

## 测试报告模板

测试完成后输出如下摘要：

```
=== E2E 测试报告 ===

服务启动:
  - 后端 (8000): [PASS/FAIL]
  - 前端 (3000): [PASS/FAIL]
  - 前端 API 代理: [PASS/FAIL]

fastest_first:
  - Gate Check 拦截: [PASS/FAIL]
  - 合格提交通过: [PASS/FAIL]
  - Task 自动关闭: [PASS/FAIL]

quality_first:
  - Dimension 生成: [PASS/FAIL] (N 个维度)
  - Gate Check 拦截: [PASS/FAIL]
  - 修订后 Gate Pass: [PASS/FAIL]
  - Individual Scoring: [PASS/FAIL]
  - Batch Scoring: [PASS/FAIL]
  - Winner 选出: [PASS/FAIL]
  - Challenge Window 进入: [PASS/FAIL]

Oracle Logs:
  - 总调用次数: N
  - 总 Token 消耗: N
  - Worker Nickname 解析: [PASS/FAIL]

所有检查项: X/Y 通过
```
