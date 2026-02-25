---
name: e2e-test
description: 端到端集成测试。清理数据库，启动前后端服务，注册用户，依次测试 fastest_first 和 quality_first 完整生命周期（发布→提交→Gate Check→修订→评分→挑战窗口），验证 Oracle V2 全链路。
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

等待 3 秒后验证后端就绪：

```bash
curl -s http://localhost:8000/tasks  # 应返回 []
```

### 步骤三：注册测试用户

注册 1 个 publisher + 2-3 个 worker，记录返回的 ID。

```bash
# Publisher
curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname":"publisher1","wallet":"0xPublisher","role":"publisher"}'

# Workers
curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname":"Alice","wallet":"0xAlice","role":"worker"}'

curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname":"Bob","wallet":"0xBob","role":"worker"}'
```

保存每个用户返回的 `id` 字段供后续步骤使用。

### 步骤四：测试 fastest_first 流程

#### 4.1 发布任务

- `type`: `fastest_first`
- `threshold`: `0.8`
- `bounty`: `0`（免支付）
- `deadline`: 当前时间 + 10 分钟
- **必须包含 `acceptance_criteria`**，例如：`"1. 列出至少3种语言\n2. 每种包含名称和用途"`

```bash
DEADLINE=$(python3 -c "from datetime import datetime,timezone,timedelta; print((datetime.now(timezone.utc)+timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -d "{
    \"title\": \"列出3种编程语言\",
    \"description\": \"列出3种流行的编程语言及其主要用途\",
    \"type\": \"fastest_first\",
    \"threshold\": 0.8,
    \"max_revisions\": null,
    \"deadline\": \"$DEADLINE\",
    \"publisher_id\": \"<PUBLISHER_ID>\",
    \"bounty\": 0,
    \"acceptance_criteria\": \"1. 至少列出3种编程语言\\n2. 每种必须包含语言名称和主要用途\"
  }"
```

**验证点：**
- 返回中 `acceptance_criteria` 不为 null
- `scoring_dimensions` 为空（fastest_first 不生成维度）

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
- `deadline`: 当前时间 + **3 分钟**（便于快速测试）
- **必须包含 `acceptance_criteria`**

```bash
DEADLINE=$(python3 -c "from datetime import datetime,timezone,timedelta; print((datetime.now(timezone.utc)+timedelta(minutes=3)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -d "{
    \"title\": \"推荐5本科幻小说\",
    \"description\": \"推荐5本值得一读的科幻小说，每本需包含书名、作者、出版年份和50字以内推荐理由\",
    \"type\": \"quality_first\",
    \"threshold\": null,
    \"max_revisions\": 3,
    \"deadline\": \"$DEADLINE\",
    \"publisher_id\": \"<PUBLISHER_ID>\",
    \"bounty\": 0,
    \"acceptance_criteria\": \"1. 必须恰好推荐5本书\\n2. 每本必须包含书名、作者、出版年份\\n3. 每本必须有50字以内的推荐理由\\n4. 推荐的书必须是真实存在的科幻小说\"
  }"
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

等待 30-60 秒。

**验证点：**
- `status` = `gate_passed`（非 scored）
- `oracle_feedback` 类型为 `individual_scoring`
- 包含各维度分数（`dimension_scores`）和 `revision_suggestions`
- **分数此时对 API 不可见**（`score` 返回 null）

#### 5.4 第二个 worker 提交

用另一个 worker 提交不同内容。如果 Gate Check 失败则修订后重新提交。

#### 5.5 等待 Deadline + Batch Scoring

Deadline 过后 scheduler 每分钟运行一次。需等待两个 scheduler tick：
- **第1个 tick**: `open` → `scoring`，触发 `batch_score_submissions()`
- **第2个 tick**: `scoring` → `challenge_window`（所有提交已 scored）

预计等待 2-4 分钟（deadline 3分钟 + 2个 scheduler 周期）。

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

### 步骤七：清理

```bash
lsof -ti:8000 | xargs kill 2>/dev/null
lsof -ti:3000 | xargs kill 2>/dev/null
```

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `Task deadline has passed` | deadline 太短，来不及提交 | quality_first 至少设 3 分钟，fastest_first 至少 10 分钟 |
| submission 状态长时间 `pending` | Oracle LLM 调用慢 | 等待 30-60 秒，检查后端日志 |
| `Unable to acquire lock` | Next.js 锁文件残留 | `rm -f frontend/.next/dev/lock` |
| gate_check 判定不符预期 | LLM 判断有时有争议 | 属正常行为，可调整提交内容使结果更明确 |
| batch scoring 不触发 | scheduler 1分钟间隔 | deadline 过后最多等 2 分钟 |
| 需要全新环境 | 历史数据干扰测试 | 手动 `rm -f market.db` 后重启服务 |

## 测试报告模板

测试完成后输出如下摘要：

```
=== E2E 测试报告 ===

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
