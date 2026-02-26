---
name: e2e-test
description: 端到端集成测试。启动后端服务，注册用户，依次测试 fastest_first 和 quality_first 完整生命周期（发布→提交→Gate Check→Individual Scoring→Batch Scoring→挑战窗口），验证 Oracle V3 全链路。
---

# E2E 集成测试技能（Oracle V3）

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
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
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
