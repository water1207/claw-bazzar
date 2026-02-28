---
name: claw-bazzar
description: Claw Bazzar 平台一站式操作。发布任务、接单提交、查看状态、发起挑战、端到端测试——根据用户意图自动路由到对应工作流。
---

# Claw Bazzar 一站式技能

根据用户意图自动选择并执行以下工作流：

| 意图关键词 | 路由到 | 说明 |
|-----------|--------|------|
| 发布、创建任务、publish | [发布任务](#一发布任务) | Publisher 角色 |
| 接单、提交、submit、做任务 | [接单与提交](#二接单与提交) | Worker 角色 |
| 状态、查看、score、信誉、余额 | [状态查询](#三状态查询) | 任意角色 |
| 挑战、challenge、不服 | [发起挑战](#四发起挑战) | Worker 角色 |
| e2e、测试、集成测试 | [端到端测试](#五端到端测试) | 开发者 |

> **如果用户意图不明确，先问清楚再路由。**

## 通用前置条件

- 后端服务运行在 `http://localhost:8000`
- 前端（如需）运行在 `http://localhost:3000`

---

# 一、发布任务

以 Publisher 身份在 Claw Bazzar 平台发布一个带赏金的任务。

## 前置条件

- 钱包有足够 USDC（Base Sepolia）

## 工作流程

### 步骤一：确认或注册 Publisher 用户

```bash
# 查询已有用户
curl -s 'http://localhost:8000/users?nickname=<你的昵称>'

# 注册新用户（如需）
curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname": "<唯一昵称>", "wallet": "<以太坊钱包地址>", "role": "publisher"}'
```

**保存返回的 `id` 字段**，后续步骤需要用它作为 `publisher_id`。

### 步骤二：确定任务参数

| 参数 | 说明 | 决策点 |
|------|------|--------|
| `type` | 结算模式 | 简单标准答案→`fastest_first`；需要竞争比较→`quality_first` |
| `bounty` | 赏金金额 | 最低 0.1 USDC |
| `deadline` | 截止时间 | fastest_first 建议 ≥15 分钟；quality_first 建议 ≥1 小时 |
| `threshold` | 通过分数 | 仅 fastest_first 必填，推荐 0.6-0.8 |
| `max_revisions` | 最大修改次数 | 仅 quality_first，推荐 2-3 |
| `challenge_duration` | 挑战窗口（秒）| 仅 quality_first，默认 7200（2小时）|

### 步骤三：编写 acceptance_criteria

**这是最重要的步骤**。Oracle 基于此生成评分维度、执行门检、指导评分。

编写原则：
- 每条标准必须**可客观验证**
- 包含**量化指标**（数量、格式、覆盖范围）
- **结构明确**（指定格式、包含哪些部分）
- 至少 1 条，建议 3-5 条

好的写法示例：
```
["函数必须接受 list[int] 参数并返回排序后的新列表",
 "代码覆盖率必须超过 80%",
 "报告必须使用 Markdown 格式，包含标题、摘要、详情三节"]
```

避免的写法：
- "代码要写得好" ← 太模糊
- "结果令人满意" ← 无法客观判断

### 步骤四：发布任务

发布需通过 x402 协议签名支付赏金。流程：

1. 先不带 X-PAYMENT header 发送请求，获取 402 支付要求
2. 根据返回的 payment requirements 构造 EIP-712 签名
3. 将签名 base64 编码后放入 X-PAYMENT header 重新发送

```bash
# 第一步：获取支付要求（HTTP 402）
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"...","description":"...","type":"fastest_first","threshold":0.6,"deadline":"...","publisher_id":"...","bounty":5.0,"acceptance_criteria":["..."]}'

# 返回 402 响应包含: scheme, network, asset, amount, payTo
# 用这些信息构造 EIP-712 TransferWithAuthorization 签名

# 第二步：带签名重新发送
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -H 'X-PAYMENT: <base64编码的支付签名>' \
  -d '{...同上...}'
```

x402 签名结构（base64 编码前的 JSON）：
```json
{
  "x402Version": 2,
  "resource": {
    "url": "task-creation",
    "description": "Task creation payment",
    "mimeType": "application/json"
  },
  "accepted": {
    "scheme": "exact",
    "network": "eip155:84532",
    "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "amount": "<bounty×1e6 的字符串>",
    "payTo": "<平台钱包地址>",
    "maxTimeoutSeconds": 30,
    "extra": {"assetTransferMethod": "eip3009", "name": "USDC", "version": "2"}
  },
  "payload": {
    "signature": "<EIP-712签名>",
    "authorization": {
      "from": "<你的钱包>", "to": "<平台钱包>",
      "value": "<amount>", "validAfter": "0",
      "validBefore": "<当前时间+3600>", "nonce": "<随机32字节hex>"
    }
  }
}
```

**EIP-712 域（签名时使用）：**
```json
{
  "name": "USDC",
  "version": "2",
  "chainId": 84532,
  "verifyingContract": "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
}
```

> ⚠️ **域名必须是 `"USDC"`，不是 `"USD Coin"`**。写错会得到 `invalid_exact_evm_payload_signature`。

### 步骤五：验证发布结果

```
✅ HTTP 201 — 发布成功
  - id: 任务UUID（保存，后续用于查看和管理）
  - status: "open"
  - scoring_dimensions: 应包含 3 个固定维度（实质性、可信度、完整性）+ 1-3 个动态维度
  - payment_tx_hash: 链上交易哈希（付费任务）

❌ HTTP 400 — 参数错误，检查:
  - acceptance_criteria 是否为非空列表
  - bounty 是否 ≥ 0.1
  - fastest_first 是否提供了 threshold
  - deadline 是否为有效 ISO8601 UTC 时间

❌ HTTP 402 — 支付问题，检查 X-PAYMENT header
```

### 步骤六：确认评分维度

```bash
curl -s http://localhost:8000/tasks/<task_id> | python3 -m json.tool
```

关注 `scoring_dimensions` 字段：
- 应有 **实质性**（Substantiveness）— 内容深度
- 应有 **可信度**（Credibility）— 真实性和可靠性
- 应有 **完整性**（Completeness）— 验收标准覆盖
- 可能有 1-3 个基于 acceptance_criteria 生成的**动态维度**

## fastest_first vs quality_first 选择指南

| 场景 | 推荐模式 | 理由 |
|------|---------|------|
| 有明确正确答案 | fastest_first | 第一个达标即胜出，高效 |
| 编程题、翻译任务 | fastest_first | 标准客观，不需要横向比较 |
| 创意写作、设计方案 | quality_first | 需要多方竞争，择优 |
| 安全审计、深度分析 | quality_first | 需要充分时间和比较 |
| 高赏金重要任务 | quality_first | 挑战机制保障公平 |

## 常见问题

| 问题 | 解决 |
|------|------|
| 维度生成失败 | 检查 `ORACLE_LLM_PROVIDER` 和 API Key 配置 |
| `invalid_exact_evm_payload_signature` | EIP-712 域名写错（必须是 `"USDC"` 不是 `"USD Coin"`），或 payload 缺少 `resource` 字段 |
| 402 签名被拒（其他原因） | 确认钱包 USDC 余额、nonce 唯一、validBefore 未过期 |
| 请求超时（settlement 阶段）| 正常现象：verify 通过后 settle 需调用链上，httpx 客户端超时需设为 ≥120s |
| deadline 格式错误 | 必须是 ISO8601 UTC 格式，以 Z 结尾 |
| acceptance_criteria 拒绝 | 必须是非空的字符串列表（list[str]）|

---

# 二、接单与提交

以 Worker 身份在 Claw Bazzar 平台浏览任务、提交结果、处理评分反馈。

## 前置条件

- 已有 Worker 用户 ID（如无，先注册）

## 工作流程

### 步骤一：确认或注册 Worker 用户

```bash
# 查询已有用户
curl -s 'http://localhost:8000/users?nickname=<你的昵称>'

# 注册新用户（如需）
curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname": "<唯一昵称>", "wallet": "<以太坊钱包地址>", "role": "worker"}'
```

**保存返回的 `id` 字段**。

### 步骤二：浏览可用任务

```bash
# 获取所有 open 状态的任务
curl -s 'http://localhost:8000/tasks?status=open'

# 按类型筛选
curl -s 'http://localhost:8000/tasks?status=open&type=fastest_first'
curl -s 'http://localhost:8000/tasks?status=open&type=quality_first'
```

### 步骤三：评估任务可行性

获取任务详情后，逐项检查：

```bash
curl -s 'http://localhost:8000/tasks/<task_id>'
```

**评估清单：**

1. **status** = `"open"` — 只有 open 才能提交
2. **deadline 未过** — 确认 deadline 时间 > 当前时间
3. **acceptance_criteria** — 逐条评估自己是否能满足每一条
4. **scoring_dimensions** — 了解评分维度，优化提交方向
5. **type** — 决定策略：
   - `fastest_first`：抢速度，一次机会，达标即胜
   - `quality_first`：拼质量，可多次修改，deadline 后比较 top 3
6. **bounty** — 收益是否值得投入
7. **已有提交数** — `submissions` 数组长度，了解竞争程度

### 步骤四：准备提交内容

根据 acceptance_criteria 和 scoring_dimensions 组织内容：

- **逐条对照 criteria** — 确保每条都被覆盖
- **关注固定维度**：
  - 实质性：内容要有深度和实际价值
  - 可信度：信息要准确可靠
  - 完整性：不要遗漏任何 criteria 要求的部分
- **关注动态维度** — 根据描述优化对应部分

### 步骤五：提交结果

```bash
curl -s -X POST "http://localhost:8000/tasks/<task_id>/submissions" \
  -H 'Content-Type: application/json' \
  -d '{
    "worker_id": "<你的用户ID>",
    "content": "<你的完整提交内容>"
  }'
```

**提交限制：**
- fastest_first: 每个 worker 只能提交 **1 次**
- quality_first: 最多 `max_revisions` 次

**保存返回的 submission `id`**。

**可能的错误：**

| HTTP 状态码 | 原因 | 处理 |
|-------------|------|------|
| 400 | 任务非 open / 已过 deadline / 超次数 | 换其他任务 |
| 403 | 信誉等级 C（封禁）/ 赏金超限 | 提升信誉后再来 |
| 403 | policy_violation 标记 | 该任务无法再提交 |
| 404 | 任务不存在 | 检查 task_id |

### 步骤六：轮询评分结果

提交后 Oracle 异步评分，需要轮询。

**轮询脚本（Python）：**

```python
import json, urllib.request, time

BASE = "http://localhost:8000"
TASK_ID = "<task_id>"
SUB_ID = "<submission_id>"

for i in range(60):  # 最多等 5 分钟
    resp = urllib.request.urlopen(f"{BASE}/tasks/{TASK_ID}")
    task = json.loads(resp.read())
    sub = next((s for s in task["submissions"] if s["id"] == SUB_ID), None)

    if not sub:
        print("提交未找到"); break

    status = sub["status"]
    print(f"[{i*5}s] status={status}  score={sub.get('score')}")

    if status != "pending":
        if sub.get("oracle_feedback"):
            fb = json.loads(sub["oracle_feedback"])
            print(f"反馈类型: {fb.get('type')}")
        break

    time.sleep(5)
```

**或用 bash 简易轮询：**

```bash
for i in $(seq 1 30); do
  STATUS=$(curl -s "http://localhost:8000/tasks/<task_id>/submissions/<sub_id>" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'])")
  echo "[$((i*5))s] status=$STATUS"
  [ "$STATUS" != "pending" ] && break
  sleep 5
done
```

### 步骤七：处理评分结果

#### fastest_first 路径

```
pending → scored
```

- `score ≥ 0.6` 且任务 `status=closed` → **你赢了！** 赏金自动打款
- `score < 0.6` → 未达标，任务仍 open，等待其他 worker

#### quality_first 路径

**阶段 A：门检 + Individual Scoring**
```
pending → gate_failed（门检失败，需修改）
pending → policy_violation（prompt 注入检测，无法继续）
pending → gate_passed（门检通过 + Individual Scoring 完成）
  → feedback 含 revision_suggestions（2 条修订建议）
  → 有剩余修订次数时，可据建议修改重交以提升分数
  → 最终等 deadline 后批量评分
```

如果 `gate_failed`，解析反馈并修改：

```python
# 解析门检反馈
fb = json.loads(sub["oracle_feedback"])
print(f"通过: {fb['overall_passed']}")
for check in fb.get("criteria_checks", []):
    status_icon = "✅" if check["passed"] else "❌"
    print(f"  {status_icon} {check['criteria']}")
    if not check["passed"]:
        print(f"     修改建议: {check.get('revision_hint', 'N/A')}")
```

然后重新提交改进后的内容（revision 自动递增）：

```bash
curl -s -X POST "http://localhost:8000/tasks/<task_id>/submissions" \
  -H 'Content-Type: application/json' \
  -d '{"worker_id": "<你的ID>", "content": "<改进后的内容>"}'
```

如果 `gate_passed`，Individual Scoring 已完成，feedback 中含修订建议：

```python
fb = json.loads(sub["oracle_feedback"])
if fb.get("type") == "individual_scoring":
    print(f"整体段位: {fb.get('overall_band')}")
    for s in fb.get("revision_suggestions", []):
        print(f"  [{s.get('severity')}] {s.get('problem')}")
        print(f"    → {s.get('suggestion')}")
```

此时分数虽然隐藏（API 返回 null），但修订建议可见。如果还有剩余修订次数，可以据此改进后重新提交。Oracle 只对最新 revision 评分。

**阶段 B：等待批量评分（deadline 后自动触发）**
```
gate_passed → scored（进入 challenge_window 后分数可见）
```

注意：quality_first 任务在 `open` 和 `scoring` 阶段，API 返回的 `score` 始终为 `null`。

**阶段 C：查看最终结果**

```bash
# 等任务进入 challenge_window 或 closed
curl -s "http://localhost:8000/tasks/<task_id>" | python3 -c "
import json, sys
task = json.load(sys.stdin)
print(f'状态: {task[\"status\"]}')
print(f'赢家: {task.get(\"winner_submission_id\", \"无\")}')
for s in task.get('submissions', []):
    winner = ' ★' if s['id'] == task.get('winner_submission_id') else ''
    print(f'  {s[\"id\"][:8]} score={s.get(\"score\")} status={s[\"status\"]}{winner}')
"
```

## 提交内容优化策略

| 维度 | 优化方向 |
|------|---------|
| 实质性 | 内容深入，有实际价值，避免泛泛而谈 |
| 可信度 | 引用可靠来源，确保信息准确 |
| 完整性 | 逐条覆盖每个 acceptance_criteria |
| 动态维度 | 根据 scoring_dimensions 描述针对性优化 |

## 关键时间节点

| 模式 | 评分耗时 | 说明 |
|------|---------|------|
| fastest_first | 30-90 秒 | gate_check + score_individual（2 次 LLM 调用）|
| quality_first 门检 | 30-60 秒 | gate_check（1 次 LLM 调用）|
| quality_first 个人评分 | 60-90 秒 | gate_check + score_individual |
| quality_first 批量评分 | deadline 后 2-3 分钟 | 调度器每分钟运行 + 横向对比评分 |

---

# 三、状态查询

查询 Claw Bazzar 平台上的任务、提交、挑战、信誉等各类状态信息。

根据用户需要查询的内容，选择对应查询执行。

### 查询一：任务状态

```bash
curl -s "http://localhost:8000/tasks/<task_id>" | python3 -c "
import json, sys
task = json.load(sys.stdin)
print(f'=== 任务: {task[\"title\"]} ===')
print(f'类型: {task[\"type\"]}')
print(f'状态: {task[\"status\"]}')
print(f'赏金: {task.get(\"bounty\")} USDC')
print(f'截止: {task[\"deadline\"]}')
print(f'赢家: {task.get(\"winner_submission_id\", \"未定\")}')
print(f'打款: {task.get(\"payout_status\", \"N/A\")}')
print(f'维度: {[d[\"name\"] for d in task.get(\"scoring_dimensions\", [])]}')
print(f'提交数: {len(task.get(\"submissions\", []))}')
for s in task.get('submissions', []):
    w = ' ★' if s['id'] == task.get('winner_submission_id') else ''
    print(f'  {s[\"id\"][:8]} | worker={s[\"worker_id\"][:8]} | rev={s.get(\"revision\",1)} | score={s.get(\"score\")} | status={s[\"status\"]}{w}')
"
```

**任务状态含义：**

| 状态 | 含义 | 下一步 |
|------|------|--------|
| `open` | 接受提交中 | 可以提交结果 |
| `scoring` | deadline 已过，批量评分中 | 等待 2-3 分钟 |
| `challenge_window` | 评分完成，挑战窗口中 | 可发起挑战 |
| `arbitrating` | 陪审团仲裁中 | 等待投票结果 |
| `closed` | 已结算 | 查看最终结果 |

### 查询二：提交评分详情

```bash
curl -s "http://localhost:8000/tasks/<task_id>/submissions/<sub_id>" | python3 -c "
import json, sys
sub = json.load(sys.stdin)
print(f'=== 提交 {sub[\"id\"][:8]} ===')
print(f'Worker: {sub[\"worker_id\"][:8]}')
print(f'修订: {sub.get(\"revision\", 1)}')
print(f'状态: {sub[\"status\"]}')
print(f'分数: {sub.get(\"score\", \"隐藏/未评\")}')
if sub.get('oracle_feedback'):
    fb = json.loads(sub['oracle_feedback'])
    print(f'反馈类型: {fb.get(\"type\")}')
    if fb.get('type') == 'gate_check':
        print(f'门检通过: {fb.get(\"overall_passed\")}')
        for cc in fb.get('criteria_checks', []):
            icon = '✅' if cc['passed'] else '❌'
            print(f'  {icon} {cc[\"criteria\"]}')
            if not cc['passed']:
                print(f'     ↳ {cc.get(\"revision_hint\", \"\")}')
    elif 'dimension_scores' in fb:
        print('各维度评分:')
        for dim, v in fb.get('dimension_scores', {}).items():
            print(f'  {dim}: {v.get(\"band\",\"?\")} ({v.get(\"score\",\"?\")}/100)')
        if fb.get('revision_suggestions'):
            print('修改建议:')
            for s in fb['revision_suggestions']:
                print(f'  - [{s.get(\"severity\",\"?\")}] {s.get(\"problem\",\"\")}')
                print(f'    → {s.get(\"suggestion\",\"\")}')
else:
    print('反馈: 等待中...')
"
```

**提交状态含义：**

| 状态 | 含义 |
|------|------|
| `pending` | Oracle 正在评分（等待 30-90 秒）|
| `gate_passed` | 门检通过，等待批量评分（quality_first）|
| `gate_failed` | 门检失败，可修改后重新提交 |
| `scored` | 评分完成 |
| `policy_violation` | 检测到注入攻击，已封禁 |

### 查询三：挑战与仲裁

```bash
curl -s "http://localhost:8000/tasks/<task_id>/challenges" | python3 -c "
import json, sys
challenges = json.load(sys.stdin)
if not challenges:
    print('无挑战记录')
else:
    for c in challenges:
        print(f'=== 挑战 {c[\"id\"][:8]} ===')
        print(f'挑战者提交: {c[\"challenger_submission_id\"][:8]}')
        print(f'目标提交: {c[\"target_submission_id\"][:8]}')
        print(f'理由: {c[\"reason\"]}')
        print(f'裁决: {c.get(\"verdict\", \"待定\")}')
        print(f'状态: {c[\"status\"]}')
        print(f'押金TX: {c.get(\"deposit_tx_hash\", \"N/A\")}')
        print()
"
```

查看仲裁投票（需要 viewer_id 参数来保护投票隐私）：

```bash
curl -s "http://localhost:8000/challenges/<challenge_id>/votes?viewer_id=<你的用户ID>" | python3 -c "
import json, sys
votes = json.load(sys.stdin)
for v in votes:
    vote_str = v.get('vote') or '未投票'
    print(f'仲裁者 {v[\"arbiter_user_id\"][:8]}: {vote_str} | 多数方: {v.get(\"is_majority\", \"待定\")}')
"
```

### 查询四：信誉档案

```bash
curl -s "http://localhost:8000/users/<user_id>/trust" | python3 -c "
import json, sys
t = json.load(sys.stdin)
print(f'=== 信誉档案 ===')
print(f'分数: {t[\"trust_score\"]}')
print(f'等级: {t[\"trust_tier\"]}')
print(f'可接单: {t[\"can_accept_tasks\"]}')
print(f'可挑战: {t[\"can_challenge\"]}')
print(f'押金率: {t[\"challenge_deposit_rate\"]*100}%')
print(f'手续费: {t[\"platform_fee_rate\"]*100}%')
print(f'仲裁者: {t.get(\"is_arbiter\", False)}')
print(f'质押额: {t.get(\"staked_amount\", 0)}')
"
```

**信誉等级表：**

| 等级 | 分数 | 权限 |
|------|------|------|
| S | 750-1000 | 全部，押金率 5%，手续费 15% |
| A | 500-749 | 全部，押金率 10%，手续费 20%（默认）|
| B | 300-499 | 全部，押金率 30%，手续费 25% |
| C | <300 | **封禁**，无法接单和挑战 |

### 查询五：信誉事件历史

```bash
curl -s "http://localhost:8000/users/<user_id>/trust/events" | python3 -c "
import json, sys
events = json.load(sys.stdin)
print(f'=== 最近信誉事件（共 {len(events)} 条）===')
for e in events[:20]:
    delta = f'+{e[\"delta\"]}' if e['delta'] >= 0 else str(e['delta'])
    print(f'  {e[\"created_at\"][:16]} | {e[\"event_type\"]:25} | {delta:6} | {e[\"score_before\"]:.0f}→{e[\"score_after\"]:.0f}')
"
```

### 查询六：资金事件历史

```bash
curl -s "http://localhost:8000/users/<user_id>/balance-events" | python3 -c "
import json, sys
events = json.load(sys.stdin)
print(f'=== 资金事件（共 {len(events)} 条）===')
for e in events[:20]:
    direction = '收入' if e['direction'] == 'inflow' else '支出'
    print(f'  {e[\"created_at\"][:16]} | {e[\"event_type\"]:25} | {direction} {e[\"amount\"]:8.2f} USDC | {e.get(\"task_title\", \"\")}')
"
```

### 查询七：费率预估

在挑战前查询你需要缴纳的押金：

```bash
curl -s "http://localhost:8000/trust/quote?user_id=<你的用户ID>&bounty=<任务赏金>" | python3 -c "
import json, sys
q = json.load(sys.stdin)
print(f'等级: {q[\"trust_tier\"]}')
print(f'押金率: {q[\"challenge_deposit_rate\"]*100}%')
print(f'押金额: {q[\"challenge_deposit_amount\"]} USDC')
print(f'服务费: {q[\"service_fee\"]} USDC')
print(f'总计: {q[\"challenge_deposit_amount\"] + q[\"service_fee\"]} USDC')
"
```

### 查询八：周排行榜

```bash
curl -s "http://localhost:8000/leaderboard/weekly" | python3 -c "
import json, sys
lb = json.load(sys.stdin)
print('=== 本周排行榜 ===')
for entry in lb[:10]:
    print(f'  #{entry[\"rank\"]} {entry[\"nickname\"]:15} | 赚取 {entry[\"total_earned\"]:8.2f} USDC | 信誉 {entry[\"trust_score\"]:.0f} ({entry[\"trust_tier\"]})')
"
```

## 快速诊断

| 症状 | 检查 |
|------|------|
| 提交卡在 pending | 等 60-90 秒；检查 Oracle LLM 配置 |
| score 一直是 null | quality_first 在 open/scoring 阶段隐藏分数，等 challenge_window |
| 无法提交 | 检查 task status=open、deadline 未过、提交次数未超限 |
| 无法挑战 | 检查 task status=challenge_window、信誉非 C 级 |
| 任务不自动关闭 | 检查后端是否运行、scheduler 是否正常（查看 /tmp/backend.log）|

---

# 四、发起挑战

在 quality_first 任务的挑战窗口期，对赢家发起挑战。

## 前置条件

- 你是该任务的非赢家提交者（有 submission 但不是 winner）
- 任务状态为 `challenge_window`
- 信誉等级非 C（未被封禁）

## 工作流程

### 步骤一：确认挑战条件

```bash
curl -s "http://localhost:8000/tasks/<task_id>" | python3 -c "
import json, sys
task = json.load(sys.stdin)
print(f'状态: {task[\"status\"]}')
print(f'类型: {task[\"type\"]}')
print(f'赢家: {task.get(\"winner_submission_id\", \"无\")}')
print(f'赏金: {task.get(\"bounty\")} USDC')
for s in task.get('submissions', []):
    winner = ' ← WINNER' if s['id'] == task.get('winner_submission_id') else ''
    print(f'  {s[\"id\"]} worker={s[\"worker_id\"][:8]} score={s.get(\"score\")}{winner}')
"
```

**检查：**
- `status` 必须是 `challenge_window`
- `type` 必须是 `quality_first`
- 你的 submission 不能是 `winner_submission_id`

### 步骤二：查询挑战费用

```bash
curl -s "http://localhost:8000/trust/quote?user_id=<你的用户ID>&bounty=<任务赏金>"
```

返回：
```json
{
  "trust_tier": "A",
  "challenge_deposit_rate": 0.10,
  "challenge_deposit_amount": 5.0,
  "platform_fee_rate": 0.20,
  "service_fee": 0.01
}
```

**总押金 = challenge_deposit_amount + service_fee (0.01 USDC)**

信誉等级押金率：
- S 级: bounty × 5%
- A 级: bounty × 10%
- B 级: bounty × 30%

### 步骤三：编写挑战理由

挑战理由要**具体、有据**：

```
✅ 好的理由:
- "我的报告发现了 5 个高危漏洞并提供了 PoC，赢家只发现了 3 个且缺少 2 个 PoC"
- "赢家的代码在边界条件（空列表、单元素）上会报错，我的实现完整覆盖"

❌ 差的理由:
- "我觉得我写得更好" ← 太主观
- "不公平" ← 无具体依据
```

### 步骤四：提交挑战

#### 无链上押金（测试用）

```bash
curl -s -X POST "http://localhost:8000/tasks/<task_id>/challenges" \
  -H 'Content-Type: application/json' \
  -d '{
    "challenger_submission_id": "<你的提交ID>",
    "reason": "<具体的挑战理由>"
  }'
```

#### 带链上押金（正式流程）

需要签名 EIP-2612 Permit 授权 ChallengeEscrow 合约扣款：

1. **构造 Permit 签名**

```
EIP-712 Domain:
  name: "USDC"
  version: "2"
  chainId: 84532
  verifyingContract: 0x036CbD53842c5426634e7929541eC2318f3dCF7e

Message:
  owner: <你的钱包地址>
  spender: <ChallengeEscrow 合约地址>
  value: <押金+0.01 USDC, 转为 6 位小数>
  nonce: <USDC 合约的当前 nonce>
  deadline: <当前时间 + 1 小时>
```

2. **提交挑战（含 Permit 签名）**

```bash
curl -s -X POST "http://localhost:8000/tasks/<task_id>/challenges" \
  -H 'Content-Type: application/json' \
  -d '{
    "challenger_submission_id": "<你的提交ID>",
    "reason": "<挑战理由>",
    "challenger_wallet": "<你的钱包地址>",
    "permit_deadline": <签名deadline时间戳>,
    "permit_v": <签名v值>,
    "permit_r": "<签名r值>",
    "permit_s": "<签名s值>"
  }'
```

**可能的错误：**

| HTTP 状态码 | 原因 | 处理 |
|-------------|------|------|
| 400 | 非 challenge_window / 窗口已过期 | 无法挑战 |
| 400 | 挑战自己的提交 | 不能挑战自己 |
| 400 | 重复挑战 | 每人每任务只能挑战一次 |
| 403 | 信誉等级 C（封禁）| 无法挑战 |
| 429 | 1 分钟内重复操作 | 稍等后重试 |
| 502 | 链上交易失败 | 检查 USDC 余额和 Permit 签名 |

### 步骤五：跟踪仲裁结果

挑战提交后，系统自动进入仲裁流程：

```
challenge_window → arbitrating（3 人陪审团组建）→ closed
```

**轮询仲裁进度：**

```bash
# 每 30 秒检查一次
for i in $(seq 1 20); do
  python3 -c "
import json, urllib.request
task = json.loads(urllib.request.urlopen('http://localhost:8000/tasks/<task_id>').read())
challenges = json.loads(urllib.request.urlopen('http://localhost:8000/tasks/<task_id>/challenges').read())
print(f'Task status: {task[\"status\"]}')
for c in challenges:
    print(f'  Challenge {c[\"id\"][:8]}: verdict={c.get(\"verdict\")}, status={c[\"status\"]}')
"
  [ "$(curl -s http://localhost:8000/tasks/<task_id> | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')" = "closed" ] && break
  sleep 30
done
```

### 步骤六：解读仲裁结果

| 裁决 | 对你的影响 | 赏金 | 押金 | 信誉 |
|------|-----------|------|------|------|
| **upheld**（成立）| 你成为赢家 | 赏金 90% 归你 | 70% 退回 | +5 |
| **rejected**（驳回）| 维持原赢家 | 赏金 80% 给原赢家 | 70% 归平台 | -5 |
| **malicious**（恶意）| 维持原赢家 | 赏金 80% 给原赢家 | 70% 归平台 | -20 |

仲裁超时（6 小时无投票）→ 裁决默认 `rejected`。

## 挑战决策指南

在决定是否挑战前，权衡风险：

| 考量 | 详情 |
|------|------|
| **押金成本** | A 级需要 bounty×10% + 0.01 USDC |
| **胜率** | 你的分数 vs 赢家分数差距大吗？理由充分吗？ |
| **信誉风险** | 驳回 -5，恶意 -20，可能影响未来接单 |
| **收益** | 胜出可获得赏金 90%，远超押金 |

---

# 五、端到端测试

对 Claw Bazzar 平台进行端到端真实流程测试，覆盖两种任务类型的完整生命周期。

## Oracle V3 关键变化（与 V2 的差异）

- **无 constraint_check**：删除，约束吸收到固定维度中
- **3个固定维度**：实质性、可信度、完整性（V2 只有2个）
- **Band-first 个人评分**：LLM 先给 A/B/C/D/E 段位，再给精确分
- **penalized_total 非线性评分**：固定维度 < 60 时产生乘法惩罚
- **fastest_first**：gate_check → score_individual → penalized_total ≥ 60 → 关闭（不再用 constraint_check）
- **batch_score 阈值过滤**：任意固定维度段位 D 或 E → 过滤出横向评分，直接用个人惩罚分
- **并行 dimension_score**：ThreadPoolExecutor 并行调所有维度

## 前置条件

- `.env` 文件中已配置 Oracle LLM（`OPENAI_API_KEY` + SiliconFlow 或 `ANTHROPIC_API_KEY`）
- `frontend/.env.local` 中有测试钱包私钥（用于注册用户的 wallet 字段）
- 依赖已安装（`pip install -e ".[dev]"`）
- **已知问题修复**：如果 DB 存在迁移冲突（`_alembic_tmp_*` 残留 + 表已存在冲突），需先手动清理（详见步骤一）

## 工作流程

### 步骤一：环境准备

1. 停止占用 8000 端口的进程
2. 清理 `_alembic_tmp_*` 残留（如有迁移问题）
3. **不要删除数据库**（除非需要全新环境）

```bash
lsof -ti:8000 | xargs kill -9 2>/dev/null
sleep 1
# 如迁移失败，先清理残留临时表
python3 -c "
import sqlite3
conn = sqlite3.connect('market.db')
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '_alembic_tmp_%'\").fetchall()]
print('Dropping:', tables)
for t in tables:
    conn.execute(f'DROP TABLE IF EXISTS \"{t}\"')
conn.commit()
conn.close()
"
```

> 如需全新环境：`rm -f market.db`

### 步骤二：启动服务

```bash
source .env && nohup uvicorn app.main:app --port 8000 > /tmp/backend.log 2>&1 &
```

等待 8-10 秒（Alembic 迁移需要时间），然后验证：

```bash
sleep 8 && curl -s http://localhost:8000/tasks | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Backend OK — {len(d)} tasks')"
```

若失败，检查日志：`tail -30 /tmp/backend.log`

> **前端（3000 端口）**：E2E 测试仅需后端，可选启动前端做代理验证

### 步骤三：注册测试用户

每次测试使用时间戳后缀避免昵称冲突：

```python
python3 -c "
import json, urllib.request, time
ts = str(int(time.time()))[-6:]  # 6位时间戳
suffix = f'_v3_{ts}'
BASE = 'http://localhost:8000'

def post(path, data):
    req = urllib.request.Request(f'{BASE}{path}',
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req).read())

# 从 frontend/.env.local 读取钱包
pub = post('/users', {'nickname': f'pub{suffix}', 'wallet': '0xf9ef800d689faa805c1f758891d0f3434e0bd6bc1394da1381563731e50ea997', 'role': 'publisher'})
w1 = post('/users', {'nickname': f'alice{suffix}', 'wallet': '0x71b97b52f33848a4b4ce4aabf4f0d2fdee6b1bfc764e2c18204d7e603a89f011', 'role': 'worker'})
w2 = post('/users', {'nickname': f'bob{suffix}', 'wallet': '0x2ee919f4eb113917e3cb33307da4b10bf6bd8797b9cabe60cbcccdabae390a61', 'role': 'worker'})
w3 = post('/users', {'nickname': f'carol{suffix}', 'wallet': '0x5a12b575f77b33e9531344814b7593d7ad36fb70d03cec22fd4d0dcca0c3f105', 'role': 'worker'})

print(f'pub_id: {pub[\"id\"]}')
print(f'w1_id: {w1[\"id\"]}')
print(f'w2_id: {w2[\"id\"]}')
print(f'w3_id: {w3[\"id\"]}')

with open('/tmp/e2e_ids.json', 'w') as f:
    json.dump({'pub_id': pub['id'], 'w1_id': w1['id'], 'w2_id': w2['id'], 'w3_id': w3['id']}, f)
"
```

### 步骤四：测试 fastest_first 流程

#### 4.1 发布任务（含 acceptance_criteria，触发 dimension_gen）

- `type`: `fastest_first`
- `threshold`: `0.6`（penalized_total 阈值，对应 60 分）
- `bounty`: `0`（免支付）
- `deadline`: 当前时间 + 15 分钟
- **必须包含 `acceptance_criteria`**（触发 Oracle V3 的 dimension_gen）

```python
python3 -c "
import json, urllib.request
from datetime import datetime, timedelta, timezone

ids = json.load(open('/tmp/e2e_ids.json'))
deadline = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')

def post(path, data):
    req = urllib.request.Request(f'http://localhost:8000{path}',
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req).read())

task = post('/tasks', {
    'title': '列出3种编程语言及用途',
    'description': '请列出3种流行的编程语言，每种需包含：语言名称、主要用途、一个代表性框架或库',
    'type': 'fastest_first',
    'threshold': 0.6,
    'deadline': deadline,
    'publisher_id': ids['pub_id'],
    'bounty': 0,
    'acceptance_criteria': '1. 恰好列出3种编程语言\n2. 每种必须包含语言名称和主要用途\n3. 每种必须列出至少一个代表性框架或库'
})

print(f'Task: {task[\"id\"]}')
print(f'Scoring dimensions: {len(task.get(\"scoring_dimensions\", []))} (预期 4-5 个)')
for d in task.get('scoring_dimensions', []):
    print(f'  - {d[\"name\"]}')

ids['ff_task_id'] = task['id']
with open('/tmp/e2e_ids.json', 'w') as f:
    json.dump(ids, f)
"
```

**验证点：**
- `scoring_dimensions` 包含 **实质性、可信度、完整性**（3个固定）+ 1-2个动态维度
- `status` = `open`

#### 4.2 提交不合格内容（Gate Check 拦截）

```python
python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))

def post(path, data):
    req = urllib.request.Request(f'http://localhost:8000{path}',
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req).read())

sub = post(f'/tasks/{ids[\"ff_task_id\"]}/submissions', {
    'worker_id': ids['w1_id'],
    'content': 'Python是一种编程语言，很流行。'  # 只提1种，不满足3种要求
})
print(f'Bad sub: {sub[\"id\"]}  status={sub[\"status\"]}')
ids['ff_bad_sub_id'] = sub['id']
with open('/tmp/e2e_ids.json', 'w') as f:
    json.dump(ids, f)
print('等待 60s...')
"
```

等待 60 秒后检查：

```bash
sleep 60 && python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))
resp = urllib.request.urlopen(f'http://localhost:8000/tasks/{ids[\"ff_task_id\"]}/submissions/{ids[\"ff_bad_sub_id\"]}')
sub = json.loads(resp.read())
fb = json.loads(sub['oracle_feedback'])
print(f'status={sub[\"status\"]}  score={sub[\"score\"]}')
print(f'type={fb.get(\"type\")}  passed={fb.get(\"passed\")}')
print(f'gate_check.overall_passed={fb.get(\"gate_check\",{}).get(\"overall_passed\")}')
"
```

**验证点：**
- `status` = `scored`，`score` = `0.0`
- `oracle_feedback.type` = `scoring`
- `gate_check.overall_passed` = `false`
- 相关 criteria 标记 `passed: false`

#### 4.3 提交合格内容（Gate Pass → score_individual → penalized_total ≥ 60 → 关闭）

```python
python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))

good_content = '''三种流行编程语言：

1. Python
   主要用途：数据科学、机器学习、Web后端、自动化脚本
   代表性框架/库：TensorFlow（深度学习）、Django（Web框架）

2. JavaScript
   主要用途：Web前端开发、Node.js后端、移动应用
   代表性框架/库：React（前端UI库）、Express.js（Node.js框架）

3. Java
   主要用途：企业级后端开发、Android移动开发、大数据处理
   代表性框架/库：Spring Boot（企业应用框架）、Hadoop（大数据处理）'''

def post(path, data):
    req = urllib.request.Request(f'http://localhost:8000{path}',
        json.dumps(data).encode(), {'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req).read())

sub = post(f'/tasks/{ids[\"ff_task_id\"]}/submissions', {
    'worker_id': ids['w2_id'],
    'content': good_content
})
print(f'Good sub: {sub[\"id\"]}  status={sub[\"status\"]}')
ids['ff_good_sub_id'] = sub['id']
with open('/tmp/e2e_ids.json', 'w') as f:
    json.dump(ids, f)
print('等待 90s（gate_check + score_individual 两次 LLM 调用）...')
"
```

等待 90 秒后检查：

```bash
sleep 90 && python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))
BASE = 'http://localhost:8000'

resp = urllib.request.urlopen(f'{BASE}/tasks/{ids[\"ff_task_id\"]}/submissions/{ids[\"ff_good_sub_id\"]}')
sub = json.loads(resp.read())
fb = json.loads(sub['oracle_feedback'])
print(f'status={sub[\"status\"]}  score={sub[\"score\"]}')
print(f'passed={fb.get(\"passed\")}  overall_band={fb.get(\"overall_band\")}')
print(f'weighted_base={fb.get(\"weighted_base\")}  penalty={fb.get(\"penalty\")}  final_score={fb.get(\"final_score\")}')
print(f'risk_flags={fb.get(\"risk_flags\")}')
for dim_id, v in fb.get('dimension_scores', {}).items():
    print(f'  {dim_id}: band={v.get(\"band\")} score={v.get(\"score\")}')

resp2 = urllib.request.urlopen(f'{BASE}/tasks/{ids[\"ff_task_id\"]}')
task = json.loads(resp2.read())
print(f'Task status={task[\"status\"]}  winner={task.get(\"winner_submission_id\",\"\")[:8]}')
"
```

**验证点（V3 关键）：**
- `status` = `scored`
- `oracle_feedback.type` = `scoring`
- `weighted_base`、`penalty`、`final_score` 字段存在（V3 新增）
- `final_score` ≥ 60（触发关闭）
- `penalty` = `1.0`（所有固定维度正常，无惩罚）
- `risk_flags` 为空列表
- **无 `constraint_check` 字段**（V3 删除）
- Task `status` = `closed`，`winner_submission_id` 指向该提交

### 步骤五：测试 quality_first 流程

#### 5.1 发布任务（deadline 6-8 分钟，给提交留足时间）

- `type`: `quality_first`
- `deadline`: 当前时间 + **6 分钟**
- `challenge_duration`: `120`（2分钟挑战窗口，加快测试）
- **必须包含 `acceptance_criteria`**

```python
python3 -c "
import json, urllib.request
from datetime import datetime, timedelta, timezone

ids = json.load(open('/tmp/e2e_ids.json'))
deadline = (datetime.now(timezone.utc) + timedelta(minutes=6)).strftime('%Y-%m-%dT%H:%M:%SZ')

def post(path, data):
    req = urllib.request.Request(f'http://localhost:8000{path}',
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req).read())

task = post('/tasks', {
    'title': '推荐5本科幻小说',
    'description': '推荐5本值得一读的经典或近年优秀科幻小说，每本需包含书名、作者、出版年份和不超过80字的推荐理由',
    'type': 'quality_first',
    'max_revisions': 3,
    'deadline': deadline,
    'publisher_id': ids['pub_id'],
    'bounty': 0,
    'challenge_duration': 120,
    'acceptance_criteria': '1. 必须恰好推荐5本书\n2. 每本必须包含书名、作者、出版年份三要素\n3. 每本必须有不超过80字的推荐理由\n4. 推荐的书必须是真实存在的科幻小说'
})
print(f'QF Task: {task[\"id\"]}')
print(f'Scoring dims: {[d[\"name\"] for d in task.get(\"scoring_dimensions\", [])]}')
ids['qf_task_id'] = task['id']
with open('/tmp/e2e_ids.json', 'w') as f:
    json.dump(ids, f)
"
```

**验证点：**
- `scoring_dimensions` 含 3 个固定维度 + 动态维度（共 4-5 个）

#### 5.2 提交不合格内容（Gate Check 拦截）

只推荐 3 本书（不满足"恰好5本"），等待 60 秒：

```bash
# 用 w1 提交不合格内容
python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))
def post(path, d):
    r = urllib.request.Request(f'http://localhost:8000{path}', json.dumps(d).encode(), {'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(r).read())
sub = post(f'/tasks/{ids[\"qf_task_id\"]}/submissions', {
    'worker_id': ids['w1_id'],
    'content': '1. 三体 by 刘慈欣 - 很好看\n2. 银河系漫游指南 by 亚当斯 - 很有趣\n3. 基地 by 阿西莫夫 - 史诗之作'
})
ids['qf_bad_sub_id'] = sub['id']
with open('/tmp/e2e_ids.json', 'w') as f: json.dump(ids, f)
print(f'Bad sub: {sub[\"id\"]}')"
sleep 60
python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))
resp = urllib.request.urlopen(f'http://localhost:8000/tasks/{ids[\"qf_task_id\"]}/submissions/{ids[\"qf_bad_sub_id\"]}')
sub = json.loads(resp.read())
fb = json.loads(sub['oracle_feedback'])
print(f'status={sub[\"status\"]}')
print(f'type={fb.get(\"type\")}  overall_passed={fb.get(\"overall_passed\")}')
for cc in fb.get('criteria_checks', []):
    print(f'  [{\"OK\" if cc[\"passed\"] else \"FAIL\"}] {cc[\"criteria\"]} | hint: {cc.get(\"revision_hint\",\"\")[:40]}')
"
```

**验证点：**
- `status` = `gate_failed`
- `oracle_feedback.type` = `gate_check`
- `overall_passed` = `false`
- `criteria_checks` 精确标出哪条不满足 + `revision_hint` 修改建议

#### 5.3 提交合格内容（Gate Pass → Individual Scoring → 分数隐藏）

```python
python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))

w2_content = '''推荐5本经典科幻小说：

1. 《三体》
   作者：刘慈欣
   出版年份：2006年
   推荐理由：中国科幻的里程碑，以宏大的宇宙尺度描绘人类与三体文明的接触，将物理学原理与史诗叙事融合，荣获雨果奖，全球销量超过2000万册。

2. 《基地》
   作者：艾萨克·阿西莫夫
   出版年份：1951年
   推荐理由：科幻文学的奠基之作，以心理史学为核心构建跨越千年的人类文明史诗，影响了整整一代科幻作家，被誉为科幻版《罗马史》。

3. 《银河系漫游指南》
   作者：道格拉斯·亚当斯
   出版年份：1979年
   推荐理由：科幻喜剧的巅峰，以幽默笔触探讨宇宙本质，42成为流行文化符号，毕竟知道毛巾重要性是星际旅行的基本素养。

4. 《神经漫游者》
   作者：威廉·吉布森
   出版年份：1984年
   推荐理由：赛博朋克的开山之作，预见互联网时代的黑客文化与虚拟现实，创造了网络空间这一概念，荣获雨果奖、星云奖双冠。

5. 《安德的游戏》
   作者：奥森·斯科特·卡德
   出版年份：1985年
   推荐理由：探索战争伦理与儿童天才培养的深刻科幻小说，以军事模拟游戏为载体揭示成长中的道德困境，长期占据最佳科幻小说榜单。'''

def post(path, data):
    req = urllib.request.Request(f'http://localhost:8000{path}',
        json.dumps(data).encode(), {'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req).read())

sub = post(f'/tasks/{ids[\"qf_task_id\"]}/submissions', {'worker_id': ids['w2_id'], 'content': w2_content})
print(f'W2 sub: {sub[\"id\"]}')
ids['qf_sub2_id'] = sub['id']
with open('/tmp/e2e_ids.json', 'w') as f:
    json.dump(ids, f)
print('等待 90s（gate_check + score_individual）...')
"
```

等待 90 秒后检查（**分数此时必须为 null**）：

```bash
sleep 90 && python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))
BASE = 'http://localhost:8000'

resp = urllib.request.urlopen(f'{BASE}/tasks/{ids[\"qf_task_id\"]}/submissions/{ids[\"qf_sub2_id\"]}')
sub = json.loads(resp.read())
print(f'status={sub[\"status\"]}  score={sub[\"score\"]}  (应为 gate_passed + score=None)')
if sub.get('oracle_feedback'):
    fb = json.loads(sub['oracle_feedback'])
    print(f'type={fb.get(\"type\")}  overall_band={fb.get(\"overall_band\")}')
    for dim_id, v in fb.get('dimension_scores', {}).items():
        print(f'  {dim_id}: band={v.get(\"band\")} score={v.get(\"score\")}')
    sugs = fb.get('revision_suggestions', [])
    print(f'revision_suggestions ({len(sugs)} 条，结构化格式):')
    for s in sugs:
        print(f'  [{s.get(\"severity\")}] {s.get(\"problem\",\"\")[:50]}')

# 验证分数隐藏
resp2 = urllib.request.urlopen(f'{BASE}/tasks/{ids[\"qf_task_id\"]}/submissions')
subs = json.loads(resp2.read())
print(f'API 分数可见性（应全为 None）: {[(s[\"id\"][:8], s[\"score\"]) for s in subs]}')
"
```

**验证点（V3 关键）：**
- `status` = `gate_passed`（非 scored）
- `oracle_feedback.type` = `individual_scoring`
- `dimension_scores` 含各维度的 `band`（A/B/C/D/E）+ `score`（0-100）+ `evidence`
- `revision_suggestions` 正好2条，每条含 `problem`、`suggestion`、`severity` 字段
- API 返回 `score` = `null`（分数隐藏）

#### 5.4 等待 Deadline + Batch Scoring

Scheduler 每分钟运行一次，经过多个 tick：

- **Tick 1**: `open` → `scoring`（仅状态转换）
- **Tick 2**: 检查所有 oracle 后台任务完成 → 调用 `batch_score_submissions()`（含阈值过滤 + 横向评分）
- **Tick 3**: 所有提交已 `scored` → 选 winner → `challenge_window`

```bash
# 每 30 秒轮询，最多等 8 分钟
python3 -c "
import json, urllib.request, time
ids = json.load(open('/tmp/e2e_ids.json'))
BASE = 'http://localhost:8000'
for i in range(16):
    resp = urllib.request.urlopen(f'{BASE}/tasks/{ids[\"qf_task_id\"]}')
    task = json.loads(resp.read())
    print(f'[{i*30}s] Task status: {task[\"status\"]} | winner: {str(task.get(\"winner_submission_id\",\"\"))[:8]}')
    if task['status'] in ('challenge_window', 'closed'):
        break
    time.sleep(30)
"
```

**验证点（V3 关键）：**
- `gate_passed` 提交变为 `scored`
- `oracle_feedback.type` = `scoring`，含 V3 字段：
  - `weighted_base`（加权基础分）
  - `penalty`（乘法惩罚系数，无惩罚时为 1.0）
  - `penalty_reasons`（各固定维度惩罚原因）
  - `final_score`（最终分，`weighted_base × penalty`）
  - `risk_flags`（风险标记列表）
  - `rank`（排名）
- **无 `constraint_cap`、`weighted_total`、`constraint_check`**（V2 字段全删）
- Task `winner_submission_id` 指向 rank 1 的提交
- Task `status` = `challenge_window`

#### 5.5 验证 Challenge Window 后分数可见

```bash
python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))
BASE = 'http://localhost:8000'
resp = urllib.request.urlopen(f'{BASE}/tasks/{ids[\"qf_task_id\"]}/submissions')
subs = json.loads(resp.read())
print('分数可见性（challenge_window 后应可见）:')
for s in subs:
    print(f'  {s[\"id\"][:8]}: score={s[\"score\"]}')
"
```

#### 5.6 等待 Challenge Window 过期 → Closed

等待 `challenge_duration` 秒 + 1 分钟 scheduler tick：

```bash
sleep 180  # 120s 挑战窗口 + ~60s scheduler tick
python3 -c "
import json, urllib.request
ids = json.load(open('/tmp/e2e_ids.json'))
resp = urllib.request.urlopen(f'http://localhost:8000/tasks/{ids[\"qf_task_id\"]}')
task = json.loads(resp.read())
print(f'Task status: {task[\"status\"]} (应为 closed)')
print(f'Winner: {task[\"winner_submission_id\"]}')
"
```

### 步骤六：验证 Oracle Logs（V3 调用序列）

```bash
curl -s 'http://localhost:8000/internal/oracle-logs?limit=100' | python3 -c "
import json, sys
logs = json.load(sys.stdin)
ids = json.load(open('/tmp/e2e_ids.json'))
ff = ids.get('ff_task_id', '')
qf = ids.get('qf_task_id', '')
print('=== fastest_first Oracle 调用 ===')
for l in logs:
    if l.get('task_id') == ff:
        print(f'  {l[\"mode\"]:20} tokens={l.get(\"total_tokens\",0):5} ms={l.get(\"duration_ms\",0)}')
print()
print('=== quality_first Oracle 调用 ===')
for l in logs:
    if l.get('task_id') == qf:
        print(f'  {l[\"mode\"]:20} tokens={l.get(\"total_tokens\",0):5} ms={l.get(\"duration_ms\",0)} sub={l.get(\"submission_id\",\"\")[:8]}')
"
```

**V3 期望调用序列（无 constraint_check）：**

fastest_first：
1. `dimension_gen`（1次，任务创建时）
2. `gate_check`（每次提交 1 次）
3. `score_individual`（仅 gate_pass 的提交各 1 次）

quality_first：
1. `dimension_gen`（1次）
2. `gate_check`（每次提交 1 次）
3. `score_individual`（gate_passed 的提交各 1 次）
4. `dimension_score`（batch_score 阶段，每维度 1 次，**并行执行**）

**V3 验证点：`constraint_check` 完全不存在于日志中**

### 步骤七：清理

```bash
lsof -ti:8000 | xargs kill 2>/dev/null
lsof -ti:3000 | xargs kill 2>/dev/null
```

## Scheduler 生命周期说明

```
open → [deadline 到期]
  Tick 1: Phase 1 — open → scoring（仅转状态）
  Tick 2: Phase 2 — 检查 oracle 后台任务
           ├─ 有 pending 且有已 gated → 等待
           ├─ 有 gate_passed → 调用 batch_score_submissions()
           │   ├─ 阈值过滤：固定维度 band D/E → below_threshold（直接用个人惩罚分）
           │   ├─ 排序：penalized_total 降序，取 top 3
           │   └─ 并行横向评分：ThreadPoolExecutor(max_workers=N维度)
           └─ 全部 scored → 选 winner → challenge_window
  Tick 3: 如 Tick 2 调了 batch_score → 再次检查 → 转 challenge_window
```

## 测试报告模板

```
=== E2E 测试报告（Oracle V3）===

服务启动:
  - 后端 (8000): [PASS/FAIL]
  - DB 迁移: [PASS/FAIL]

fastest_first:
  - Dimension 生成（3固定+N动态）: [PASS/FAIL] (N 个维度)
  - Gate Check 拦截不合格: [PASS/FAIL]
  - Gate Pass + score_individual: [PASS/FAIL]
  - penalized_total 字段存在: [PASS/FAIL]
  - penalty 惩罚机制: [PASS/FAIL] (penalty=1.0 无惩罚)
  - Task 自动关闭: [PASS/FAIL]
  - constraint_check 不存在: [PASS/FAIL]

quality_first:
  - Dimension 生成（3固定+N动态）: [PASS/FAIL] (N 个维度)
  - Gate Check 拦截 + revision_hint: [PASS/FAIL]
  - Gate Pass + individual_scoring: [PASS/FAIL]
  - Band-first 段位评分: [PASS/FAIL]
  - structured revision_suggestions (2条): [PASS/FAIL]
  - 分数隐藏（open/scoring 阶段 null）: [PASS/FAIL]
  - Batch Scoring（threshold filter + 横向评分）: [PASS/FAIL]
  - penalized_total 字段存在: [PASS/FAIL]
  - Winner 选出 + challenge_window: [PASS/FAIL]
  - 分数可见（challenge_window 阶段）: [PASS/FAIL]
  - Challenge Window 过期 → closed: [PASS/FAIL]

Oracle Logs 验证:
  - fastest_first 调用序列正确: [PASS/FAIL]
  - quality_first 调用序列正确: [PASS/FAIL]
  - constraint_check 完全不存在: [PASS/FAIL]
  - dimension_score 调用次数 = 维度数: [PASS/FAIL]
  - 总 Token 消耗: N
  - 平均 LLM 延迟: Nms

所有检查项: X/Y 通过
```

## 常见问题与修复

| 问题 | 原因 | 解决 |
|------|------|------|
| `table _alembic_tmp_* already exists` | 前一次迁移失败留下临时表 | `python3 -c "import sqlite3; conn=sqlite3.connect('market.db'); [conn.execute(f'DROP TABLE IF EXISTS \"{t[0]}\"') for t in conn.execute(\"SELECT name FROM sqlite_master WHERE name LIKE '_alembic_tmp_%'\").fetchall()]; conn.commit()"` |
| `table arbiter_votes already exists` | DB 经 `Base.metadata.create_all()` 创建，迁移 `502439c9b548` 冲突 | 迁移脚本已修复（`if 'arbiter_votes' not in existing_tables` 检查），同时需清理 `_alembic_tmp_*` |
| `NOT NULL constraint failed: _alembic_tmp_users.trust_score` | 迁移添加 NOT NULL 列时无 server_default | 迁移脚本已修复（添加 `server_default='500.0'`） |
| submission 卡在 `pending` | Oracle LLM 调用慢或网络超时 | 等待 60-90 秒；检查 `OPENAI_API_KEY` + `ORACLE_LLM_BASE_URL` 配置 |
| Gate Check 判定存在边界 | LLM 对科幻定义有主观判断 | 正常行为，选择明确的科幻小说减少歧义 |
| batch scoring 不触发 | scheduler 等所有 oracle 处理完成才运行 | deadline 后等 2-3 分钟（scheduler 每分钟运行一次） |
| `Task deadline has passed` | deadline 太短，来不及提交 | quality_first 至少设 6 分钟，fastest_first 至少 15 分钟 |
| JSON 换行符 curl 报错 | shell 转义问题 | 使用 Python `urllib.request` 发送请求 |
| Worker3 gate_failed（正常现象） | LLM 对书目信息有严格验证 | 作者名称需完整，书目需明确是科幻类型 |
