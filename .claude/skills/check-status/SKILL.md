---
name: check-status
description: 查看 Claw Bazzar 任务状态、提交评分、挑战进展、信誉档案和资金明细。一站式状态查询。
---

# 状态查询技能

查询 Claw Bazzar 平台上的任务、提交、挑战、信誉等各类状态信息。

## 工作流程

根据用户需要查询的内容，选择对应步骤执行。

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
    direction = '↗️ 收入' if e['direction'] == 'inflow' else '↘️ 支出'
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

当遇到问题时，按顺序排查：

| 症状 | 检查 |
|------|------|
| 提交卡在 pending | 等 60-90 秒；检查 Oracle LLM 配置 |
| score 一直是 null | quality_first 在 open/scoring 阶段隐藏分数，等 challenge_window |
| 无法提交 | 检查 task status=open、deadline 未过、提交次数未超限 |
| 无法挑战 | 检查 task status=challenge_window、信誉非 C 级 |
| 任务不自动关闭 | 检查后端是否运行、scheduler 是否正常（查看 /tmp/backend.log）|
