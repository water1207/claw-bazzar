---
name: challenge
description: 在 quality_first 任务的挑战窗口内，对赢家发起挑战。构造理由、签名挑战押金（EIP-2612 Permit）、提交挑战并跟踪仲裁结果。
---

# 挑战技能

在 quality_first 任务的挑战窗口期，对赢家发起挑战。

## 前置条件

- 后端服务运行在 `http://localhost:8000`
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
