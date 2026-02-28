# 横向比较结果展示与 Winner 理由

**日期**: 2026-02-28
**状态**: 设计确认

## 背景

quality_first 任务的横向比较（dimension_score）目前在后端完成评分后，仅将分数和 evidence 存入 `oracle_feedback`。LLM 输出的 `comparative_analysis` 字段未被存储，前端也没有展示"为什么 winner 比其他人好"的理由。

## 目标

1. 在 submission 旁增加横向比较 tab，展示 top 3 排名与 winner 理由
2. 修改横向比较提示词，输出 `winner_advantage` 字段
3. 数据库新增 `comparative_feedback` 字段（仅 winner 有值）
4. 调整评分详情的可见性规则：open 阶段只展示修订建议，scoring 起展示分数/band/evidence

## 设计决策

| 决策项 | 结论 |
|--------|------|
| 横评理由存储 | 仅存 winner 的综合横评理由，不存每个维度的 comparative_analysis |
| 综合理由生成 | 修改 dimension_score 提示词增加 `winner_advantage`，后端模板化拼装，不额外调 LLM |
| 横向比较 tab 可见时机 | tab 始终存在；内容 challenge_window 起可见，之前显示「评分中，待公开」 |
| 可见范围 | 所有人可见 |

## 1. 数据库变更

### Submission 模型新增字段

```python
comparative_feedback = Column(Text, nullable=True)
```

仅 winner 有值，JSON 结构：

```json
{
  "winner_rationale": "Winner 在 4 个维度中综合表现最优：\n• 实质性: A 在深度分析方面优于 B/C...\n• 可信度: A 的论据更具说服力...\n• 完整性: A 覆盖了所有验收标准...\n• 数据质量: A 的数据源更可靠...",
  "rankings": [
    {"rank": 1, "submission_id": "sub_abc", "worker_id": "user_1", "final_score": 82.3},
    {"rank": 2, "submission_id": "sub_def", "worker_id": "user_2", "final_score": 75.1},
    {"rank": 3, "submission_id": "sub_ghi", "worker_id": "user_3", "final_score": 68.9}
  ]
}
```

需要 Alembic migration。

## 2. Oracle 提示词修改

### dimension_score.py 输出格式变更

在 LLM 输出 JSON 中增加 `winner_advantage` 字段：

```json
{
  "dimension_id": "substantiveness",
  "dimension_name": "实质性",
  "evaluation_focus": "...",
  "comparative_analysis": "横向对比...",
  "winner_advantage": "A 在该维度表现最优，因为其分析深度和论据质量明显优于 B 和 C...",
  "scores": [
    {"submission": "Submission_A", "raw_score": 85, "final_score": 85, "evidence": "..."}
  ]
}
```

提示词调整要点：
- 输出格式增加 `winner_advantage` 字段定义
- 要求一句话说明该维度得分最高者为什么优于其他提交
- 保持现有 `comparative_analysis` 不变

## 3. 后端汇总逻辑

在 `batch_score_submissions()` 完成所有维度评分后：

1. 确定 winner（rank=1 的 submission）
2. 从各维度 LLM 结果中提取 `winner_advantage`
3. 模板化拼装综合理由：
   ```
   Winner 在 {N} 个维度中综合表现最优：
   • {dim_name}: {winner_advantage}
   • {dim_name}: {winner_advantage}
   ...
   ```
4. 构建 rankings 数组（包含 rank、submission_id、worker_id、final_score）
5. 存入 winner 的 `comparative_feedback` 字段

## 4. API 变更

### Schema

`SubmissionOut` 增加：

```python
comparative_feedback: Optional[str] = None
```

### 可见性控制

修改 `_maybe_hide_score()` 逻辑：

| 阶段 | score | oracle_feedback | comparative_feedback |
|------|-------|----------------|---------------------|
| `open` | 隐藏 | 保留（前端控制显示修订建议） | 隐藏 |
| `scoring` | 显示 | 显示 | 隐藏 |
| `challenge_window`+ | 显示 | 显示 | 显示 |

注：`open` 阶段 score 隐藏但 oracle_feedback 保留，由前端根据 task status 决定展示修订建议还是分数详情。`scoring` 阶段 score 和 oracle_feedback 都显示（包含 band、score、evidence）。

## 5. 前端变更

### 评分详情 tab（现有 FeedbackCard 改造）

按 task status 展示不同内容：

| 阶段 | 显示内容 |
|------|---------|
| `open` | 仅修订建议（priority 标签用 High / Mid / Low） |
| `scoring` 及之后 | band + 分数 + evidence（不显示修订建议） |

修订建议优先级标签映射：
- `HIG` → `High`
- `MED` → `Mid`
- `LOW` → `Low`

### 横向比较 tab（新增）

仅对 top 3 的 submission 显示此 tab：

| 阶段 | 显示内容 |
|------|---------|
| `open` / `scoring` | tab 存在，显示「评分中，待公开」 |
| `challenge_window` 及之后 | top 3 排名列表 + winner 综合横评理由 |

横向比较 tab 内容（分数公开后）：
- 排名列表：rank + worker + final_score
- winner 综合理由：来自 winner submission 的 `comparative_feedback.winner_rationale`
- 所有人可见，无权限区分

## 6. 受影响文件

### 后端
- `app/models.py` — 新增 `comparative_feedback` 字段
- `app/schemas.py` — `SubmissionOut` 增加字段
- `app/routers/submissions.py` — `_maybe_hide_score()` 细化可见性逻辑
- `oracle/dimension_score.py` — 提示词增加 `winner_advantage` 输出
- `app/services/oracle.py` — `batch_score_submissions()` 增加汇总逻辑
- `alembic/versions/` — 新增 migration

### 前端
- `frontend/components/FeedbackCard.tsx` — 按 task status 切换显示内容 + 优先级标签映射
- `frontend/components/SubmissionTable.tsx` — 增加横向比较 tab
