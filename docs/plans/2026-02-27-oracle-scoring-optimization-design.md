# Oracle 评分系统优化设计

## 背景

当前 Oracle 评分管线存在以下问题：

1. **短板/长板效应**：线性加权求和 `Σ(w × s)` 假设维度间可自由互补，导致某维度极差可被其他维度补回，或某维度极强可拉高整体
2. **score_individual 产出不足**：仅输出 `score + feedback`，缺乏结构化证据，横向对比阶段从零开始分析
3. **constraint_check 与 fixed 维度重叠**：任务契合度/真实性 与 实质性/完整性 检查内容高度重合，分两次 LLM 调用浪费且不一致
4. **fastest_first 评分为二元判断**：通过=1.0，不通过=0.0，用户无法了解具体哪个维度有问题
5. **dimension_score 串行调用**：N 个维度顺序执行，耗时 N×T

## 设计目标

- 消除短板/长板效应对排名的扭曲
- 统一两条路径（fastest_first / quality_first）的评分机制
- 减少 LLM 调用次数（删除 constraint_check）
- 提升评分的可解释性和公平性
- 通过并行化降低 batch 阶段耗时

---

## 一、score_individual 升级

### 1.1 评分方式：Band-first

先判定落在哪个档位，再在档内给精确分数：

| Band | 分数区间 | 含义 |
|------|---------|------|
| A | 90-100 | 显著超出预期 |
| B | 70-89 | 良好完成，有亮点 |
| C | 50-69 | 基本满足但平庸 |
| D | 30-49 | 勉强相关但质量差 |
| E | 0-29 | 几乎无价值 |

### 1.2 Evidence 强制化

每个维度必须引用提交中的具体内容作为评分依据，不允许泛泛评价。

### 1.3 修订建议固定 2 条

为保证公平性，所有提交统一只给 2 条建议，按严重程度排序，聚焦最关键的问题。结构化为 `{problem, suggestion, severity}`。

### 1.4 输出结构（IR - Intermediate Representation）

```json
{
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
    }
  },
  "overall_band": "C",
  "revision_suggestions": [
    { "problem": "数据缺乏来源", "suggestion": "补充数据来源或获取方式", "severity": "high" },
    { "problem": "结论逻辑跳跃", "suggestion": "补充推导过程", "severity": "medium" }
  ]
}
```

### 1.5 两条路径统一使用 score_individual

fastest_first 和 quality_first 在 gate_check 通过后，都调用同一个 score_individual，获得相同结构的评分产物和 2 条修订建议。

---

## 二、Fixed 维度重新定义

吸收 constraint_check 的职责，fixed 维度从 2 个变为 3 个：

| 维度 | 来源 | 说明 |
|------|------|------|
| 实质性 | 原 fixed + 原 constraint_check 任务契合度 | 内容是否有真正价值且回应任务诉求 |
| 可信度 | 原 constraint_check 真实性 | 数据是否可信、有无编造 |
| 完整性 | 原 fixed | 是否覆盖任务描述的所有方面 |

动态维度仍为 1-3 个，总维度 4-6 个。`dimension_gen.py` 的 prompt 需更新。

---

## 三、候选池筛选（quality_first）

### 流程

```
gate_passed 提交集
    │
    ├─ Step 1: 门槛过滤
    │    任一维度 band < C → 标记 below_threshold，不进决赛
    │
    ├─ Step 2: 剩余按 penalized_total 排序，取 Top 3
    │
    └─ Step 3: dimension_score × N 维度（可并行）
```

### penalized_total 计算

```python
base = sum(weight_i * score_i for each dimension)

penalty = 1.0
for fixed_dim in fixed_dimensions:
    if score < threshold:  # threshold = 60
        penalty *= score / threshold

penalized_total = base * penalty
```

门槛过滤和排序用同一个 penalty 公式，逻辑一致。

---

## 四、fastest_first 评分流程

```
提交进入
    │
    gate_check
    ├─ fail → gate_failed
    └─ pass ↓
        │
   score_individual
   (band-first + evidence + 固定2条建议)
        │
   penalized_total
    ├─ ≥ 60 → pass → _apply_fastest_first（关闭 + 付款）
    └─ < 60 → scored（保留实际分数）
```

用户可以看到各维度真实分数和未通过的原因。

---

## 五、dimension_score 简化

### 变化

- 移除 `constraint_caps` 输入和 prompt 中的 cap 逻辑
- 新增 individual IR（band + evidence）作为参考锚点，标注为"仅供参考，不限制判断"
- 输出去掉 `cap_applied` 字段
- dimension_score 仍为主排名信号

### prompt 新增参考段

```
## Individual Scoring 参考（仅供锚定）

- Submission_A: band=B, evidence="..."
- Submission_B: band=B, evidence="..."
- Submission_C: band=A, evidence="..."
```

---

## 六、非线性聚合 + 风险标记

### 聚合公式

```python
base = sum(weight_i * score_i for each dimension)

# fixed 维度 penalty
threshold = 60
penalty = 1.0
for fixed_dim in fixed_dimensions:
    if fixed_dim.score < threshold:
        penalty *= fixed_dim.score / threshold

final_score = base * penalty
```

### 示例

| 场景 | base | penalty | final |
|------|------|---------|-------|
| 全部 ≥ 60 | 78 | 1.0 | 78 |
| 可信度=45 | 78 | 0.75 | 58.5 |
| 可信度=45, 实质性=40 | 72 | 0.50 | 36.0 |

### 风险标记

fixed 维度 score < threshold 时，附加 flag 和原因。

### 最终 oracle_feedback 结构

```json
{
  "type": "scoring",
  "dimension_scores": {
    "credibility": { "score": 55, "band": "C", "flag": "below_expected", "evidence": "..." },
    "completeness": { "score": 72, "band": "B", "evidence": "..." },
    "tech_depth": { "score": 88, "band": "A", "evidence": "..." }
  },
  "weighted_base": 73.4,
  "penalty": 0.92,
  "penalty_reasons": ["关键维度「可信度」低于预期"],
  "final_score": 67.5,
  "risk_flags": ["可信度偏低"],
  "rank": 1
}
```

---

## 七、并行化

### dimension_score 并行

N 个维度的 dimension_score 调用互相独立，使用 `ThreadPoolExecutor` 并发执行。

### 前提：`_oracle_logs` 加锁

```python
import threading
_oracle_logs_lock = threading.Lock()

# _call_oracle 中：
with _oracle_logs_lock:
    _oracle_logs.append(log_entry)
    if len(_oracle_logs) > MAX_LOGS:
        _oracle_logs[:] = _oracle_logs[-MAX_LOGS:]
```

### 耗时对比

| 阶段 | 现在 | 优化后 |
|------|------|--------|
| constraint_check × K | K × T | 0（已删除） |
| dimension_score × N | N × T | ~T（并行） |
| **总计** | (K+N) × T ≈ 6-8T | ~T |

---

## 八、被删除的组件

| 组件 | 原因 |
|------|------|
| `oracle/constraint_check.py` | 职责被 fixed 维度吸收 |
| `oracle/oracle.py` 中的 `constraint_check` 注册 | 不再需要 |
| `dimension_score` 中的 cap 逻辑 | penalty 替代 |
| `score_submission()` 中的 constraint_check 调用 | score_individual 替代 |
| `batch_score_submissions()` 中的 constraint_check 循环 | 门槛过滤替代 |

## 九、代码改动范围

| 文件 | 改动 |
|------|------|
| `oracle/dimension_gen.py` | prompt 增加"可信度"为第 3 个 fixed 维度 |
| `oracle/score_individual.py` | prompt 改 band-first + evidence 强制 + 固定 2 条建议 |
| `oracle/dimension_score.py` | 移除 cap 输入/输出，增加 individual IR 参考 |
| `oracle/constraint_check.py` | 删除 |
| `oracle/oracle.py` | V2_MODES 移除 `constraint_check` |
| `app/services/oracle.py` | `score_submission()` 改用 score_individual + 阈值判断；`batch_score_submissions()` 重写筛选 + 聚合逻辑；并行化 dimension_score；删除 constraint_check 调用 |

## 十、完整流程总览

```
                          任务创建
                             │
                        dimension_gen
                    （3 fixed + 1-3 dynamic）
                             │
              ┌──────────────┴──────────────┐
              │                             │
         fastest_first                 quality_first
              │                             │
          提交进入                        提交进入
              │                             │
         gate_check                    gate_check
          ├─ fail → gate_failed         ├─ fail → gate_failed
          └─ pass ↓                     └─ pass → gate_passed
              │                             │
        score_individual              score_individual
     (band-first + evidence            (band-first + evidence
      + 固定2条建议)                    + 固定2条建议)
              │                             │
        penalized_total               ┌─────┴──── 截止 ────┐
          ├─ ≥ 60 → pass              │                     │
          │   → close + pay        门槛过滤              未通过门槛
          └─ < 60 → scored       任一维度 band<C → 淘汰    → scored
                                      │
                                penalized_total 排序
                                   取 Top 3
                                      │
                              dimension_score × N
                                 (可并行)
                            (无cap, 携带individual IR)
                                      │
                              非线性聚合
                           base × penalty + 风险标记
                                      │
                                  最终排名
                                      │
                               challenge_window
                                      │
                                   closed
```
