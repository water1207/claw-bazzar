# Comparative Scoring Display Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `comparative_feedback` field to the winner submission with a rationale explaining why the winner is best, modify the dimension_score prompt to output `winner_advantage`, adjust score visibility rules per phase, and add a horizontal comparison tab in the frontend.

**Architecture:** New `comparative_feedback` column on `Submission` model stores winner-only JSON with rationale + rankings. The `dimension_score.py` prompt gains a `winner_advantage` output field. `batch_score_submissions()` assembles the rationale from per-dimension advantages. Frontend `FeedbackCard` splits display by task status (open: revision suggestions only; scoring+: band/score/evidence). A new `ComparativeTab` component shows rankings and winner rationale.

**Tech Stack:** Python/SQLAlchemy/Alembic (backend), TypeScript/React/Next.js (frontend), pytest (tests)

---

### Task 1: Add `comparative_feedback` column to Submission model + migration

**Files:**
- Modify: `app/models.py:159-172` (Submission class)
- Create: `alembic/versions/xxxx_add_comparative_feedback.py` (auto-generated)

**Step 1: Add the column to the model**

In `app/models.py`, add after line 171 (`deposit_returned`):

```python
comparative_feedback = Column(Text, nullable=True)
```

**Step 2: Generate Alembic migration**

Run: `alembic revision --autogenerate -m "add comparative_feedback to submissions"`

Expected: New file in `alembic/versions/` with `add_column('submissions', sa.Column('comparative_feedback', ...))`.

**Step 3: Apply migration**

Run: `alembic upgrade head`

Expected: Success, no errors.

**Step 4: Commit**

```bash
git add app/models.py alembic/versions/
git commit -m "feat: add comparative_feedback column to Submission model"
```

---

### Task 2: Add `comparative_feedback` to SubmissionOut schema + visibility control

**Files:**
- Modify: `app/schemas.py:154-167` (SubmissionOut class)
- Modify: `app/routers/submissions.py:14-22` (`_maybe_hide_score` function)

**Step 1: Write failing test for visibility control**

Create test in `tests/test_comparative_visibility.py`:

```python
"""Tests for comparative_feedback visibility and score phase rules."""
import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, TaskType, TaskStatus, SubmissionStatus


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_task(db, status=TaskStatus.open):
    task = Task(
        title="T", description="D", type=TaskType.quality_first,
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        bounty=1.0, status=status,
    )
    db.add(task)
    db.flush()
    return task


def _make_sub(db, task_id, comparative_feedback=None):
    sub = Submission(
        task_id=task_id, worker_id="w1", content="c", revision=1,
        status=SubmissionStatus.scored, score=0.85,
        oracle_feedback=json.dumps({"type": "scoring", "rank": 1, "final_score": 85}),
        comparative_feedback=comparative_feedback,
    )
    db.add(sub)
    db.flush()
    return sub


def test_hide_comparative_feedback_open(db):
    """open phase: score=null, comparative_feedback=null."""
    from app.routers.submissions import _maybe_hide_score
    task = _make_task(db, TaskStatus.open)
    cf = json.dumps({"winner_rationale": "A wins", "rankings": []})
    sub = _make_sub(db, task.id, comparative_feedback=cf)
    db.commit()
    result = _maybe_hide_score(sub, task, db)
    assert result.score is None
    assert result.comparative_feedback is None


def test_hide_comparative_feedback_scoring(db):
    """scoring phase: score visible, comparative_feedback=null."""
    from app.routers.submissions import _maybe_hide_score
    task = _make_task(db, TaskStatus.scoring)
    cf = json.dumps({"winner_rationale": "A wins", "rankings": []})
    sub = _make_sub(db, task.id, comparative_feedback=cf)
    db.commit()
    result = _maybe_hide_score(sub, task, db)
    assert result.score is not None
    assert result.comparative_feedback is None


def test_show_comparative_feedback_challenge_window(db):
    """challenge_window phase: score visible, comparative_feedback visible."""
    from app.routers.submissions import _maybe_hide_score
    task = _make_task(db, TaskStatus.challenge_window)
    cf = json.dumps({"winner_rationale": "A wins", "rankings": []})
    sub = _make_sub(db, task.id, comparative_feedback=cf)
    db.commit()
    result = _maybe_hide_score(sub, task, db)
    assert result.score is not None
    assert result.comparative_feedback == cf
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_comparative_visibility.py -v`

Expected: FAIL (comparative_feedback attribute doesn't exist on SubmissionOut, visibility logic not implemented yet).

**Step 3: Add field to SubmissionOut schema**

In `app/schemas.py`, add to `SubmissionOut` class after line 164 (`deposit_returned`):

```python
comparative_feedback: Optional[str] = None
```

**Step 4: Update `_maybe_hide_score` visibility logic**

Replace the entire `_maybe_hide_score` function in `app/routers/submissions.py:14-22` with:

```python
def _maybe_hide_score(submission: Submission, task: Task, db: Session = None) -> Submission:
    """Control field visibility based on task phase for quality_first tasks.

    - open: hide score, hide comparative_feedback
    - scoring: show score, hide comparative_feedback
    - challenge_window+: show all
    """
    if task.type != TaskType.quality_first:
        return submission

    if db:
        db.expunge(submission)

    if task.status == TaskStatus.open:
        submission.score = None
        submission.comparative_feedback = None
    elif task.status == TaskStatus.scoring:
        submission.comparative_feedback = None

    return submission
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_comparative_visibility.py -v`

Expected: All 3 PASS.

**Step 6: Run existing tests to check no regressions**

Run: `pytest tests/test_oracle_service.py tests/test_oracle_v2_service.py -v`

Expected: All PASS.

**Step 7: Commit**

```bash
git add app/schemas.py app/routers/submissions.py tests/test_comparative_visibility.py
git commit -m "feat: add comparative_feedback to schema with phase-based visibility"
```

---

### Task 3: Add `winner_advantage` to dimension_score prompt

**Files:**
- Modify: `oracle/dimension_score.py:58-73` (PROMPT_TEMPLATE output format section)

**Step 1: Write failing test**

Add test to `tests/test_comparative_visibility.py`:

```python
def test_dimension_score_prompt_includes_winner_advantage():
    """dimension_score prompt template should require winner_advantage in output."""
    from oracle.dimension_score import PROMPT_TEMPLATE
    assert "winner_advantage" in PROMPT_TEMPLATE
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_comparative_visibility.py::test_dimension_score_prompt_includes_winner_advantage -v`

Expected: FAIL.

**Step 3: Update dimension_score.py prompt**

In `oracle/dimension_score.py`, replace the output format section (lines 58-73):

```python
PROMPT_TEMPLATE = """## 你的任务
在指定维度下，对所有提交进行横向比较并打分。只关注当前维度。

## 任务信息

### 标题
{task_title}

### 描述
{task_description}

## 当前评分维度

### 维度名称
{dim_name}

### 维度描述
{dim_description}

### 评分指引
{dim_scoring_guidance}

## Individual Scoring 参考（仅供锚定，不限制你的判断）

{individual_ir_text}

## 待评提交（已匿名化）
<user_content>
{submissions_text}
</user_content>

## 评分流程

### 1. 明确评判焦点
结合任务描述和维度定义，阐述该维度的评判重点。

### 2. 逐提交分析
对每个提交分析在该维度上的表现，具体引用提交中的内容作为 evidence。

### 3. 横向比较
将所有提交在该维度上的表现放在一起对比，说明排序理由。

### 4. 打分
0-100 分。

### 5. Winner 优势总结
用一句话说明该维度得分最高者为什么优于其他提交。

## 打分标准
- 90-100: 显著超出预期
- 70-89: 良好完成，有亮点
- 50-69: 基本满足但平庸
- 30-49: 勉强相关但质量差
- 0-29: 几乎无价值

## 输出格式 (严格JSON)

{{
  "dimension_id": "{dim_id}",
  "dimension_name": "{dim_name}",
  "evaluation_focus": "本次评判的具体焦点",
  "comparative_analysis": "横向比较说明",
  "winner_advantage": "该维度得分最高者为什么优于其他提交（一句话）",
  "scores": [
    {{
      "submission": "Submission_A",
      "raw_score": 85,
      "final_score": 85,
      "evidence": "核心评分依据"
    }}
  ]
}}"""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_comparative_visibility.py::test_dimension_score_prompt_includes_winner_advantage -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add oracle/dimension_score.py tests/test_comparative_visibility.py
git commit -m "feat: add winner_advantage field to dimension_score prompt"
```

---

### Task 4: Assemble `comparative_feedback` in `batch_score_submissions`

**Files:**
- Modify: `app/services/oracle.py:575-598` (batch_score_submissions write-back section)

**Step 1: Write failing test**

Add test to `tests/test_comparative_visibility.py`:

```python
def test_batch_score_sets_comparative_feedback_on_winner(db):
    """batch_score_submissions should populate comparative_feedback on the rank=1 submission."""
    from app.services.oracle import batch_score_submissions
    from app.models import ScoringDimension

    task = Task(
        title="T", description="D", type=TaskType.quality_first,
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc), bounty=10.0,
        acceptance_criteria=json.dumps(["AC"]),
    )
    db.add(task)
    db.commit()

    dim1 = ScoringDimension(
        task_id=task.id, dim_id="substantiveness", name="实质性",
        dim_type="fixed", description="d", weight=0.5, scoring_guidance="g"
    )
    dim2 = ScoringDimension(
        task_id=task.id, dim_id="completeness", name="完整性",
        dim_type="fixed", description="d", weight=0.5, scoring_guidance="g"
    )
    db.add_all([dim1, dim2])
    db.commit()

    sub1 = Submission(
        task_id=task.id, worker_id="w1", content="content A",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "B", "score": 80, "evidence": "good"},
                "completeness": {"band": "B", "score": 75, "evidence": "ok"},
            },
            "revision_suggestions": []
        })
    )
    sub2 = Submission(
        task_id=task.id, worker_id="w2", content="content B",
        status=SubmissionStatus.gate_passed,
        oracle_feedback=json.dumps({
            "type": "individual_scoring",
            "dimension_scores": {
                "substantiveness": {"band": "C", "score": 60, "evidence": "basic"},
                "completeness": {"band": "C", "score": 55, "evidence": "incomplete"},
            },
            "revision_suggestions": []
        })
    )
    db.add_all([sub1, sub2])
    db.commit()

    mock_dim_sub = json.dumps({
        "dimension_id": "substantiveness",
        "comparative_analysis": "A > B",
        "winner_advantage": "A 的分析更深入全面",
        "scores": [
            {"submission": "Submission_A", "raw_score": 85, "final_score": 85, "evidence": "good"},
            {"submission": "Submission_B", "raw_score": 70, "final_score": 70, "evidence": "ok"},
        ]
    })
    mock_dim_comp = json.dumps({
        "dimension_id": "completeness",
        "comparative_analysis": "A > B",
        "winner_advantage": "A 覆盖了所有验收标准",
        "scores": [
            {"submission": "Submission_A", "raw_score": 80, "final_score": 80, "evidence": "good"},
            {"submission": "Submission_B", "raw_score": 60, "final_score": 60, "evidence": "ok"},
        ]
    })

    responses = [
        type("R", (), {"stdout": mock_dim_sub, "returncode": 0})(),
        type("R", (), {"stdout": mock_dim_comp, "returncode": 0})(),
    ]
    call_idx = 0
    def mock_subprocess(*args, **kwargs):
        nonlocal call_idx
        result = responses[call_idx]
        call_idx += 1
        return result

    from unittest.mock import patch
    with patch("app.services.oracle.subprocess.run", side_effect=mock_subprocess):
        batch_score_submissions(db, task.id)

    db.refresh(sub1)
    db.refresh(sub2)

    # Winner (sub1, rank=1) should have comparative_feedback
    assert sub1.comparative_feedback is not None
    cf = json.loads(sub1.comparative_feedback)
    assert "winner_rationale" in cf
    assert "rankings" in cf
    assert len(cf["rankings"]) == 2
    assert cf["rankings"][0]["rank"] == 1
    assert "实质性" in cf["winner_rationale"]
    assert "完整性" in cf["winner_rationale"]

    # Non-winner (sub2, rank=2) should NOT have comparative_feedback
    assert sub2.comparative_feedback is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_comparative_visibility.py::test_batch_score_sets_comparative_feedback_on_winner -v`

Expected: FAIL (comparative_feedback not being set).

**Step 3: Implement comparative_feedback assembly in batch_score_submissions**

In `app/services/oracle.py`, modify the `batch_score_submissions` function. After the ranking is computed (line 573) and before the write-back loop (line 576), add the assembly logic. Replace lines 575-598 with:

```python
    # Step 5: Assemble comparative_feedback for winner
    winner_entry = ranking[0] if ranking else None
    comparative_feedback_json = None
    if winner_entry:
        # Collect winner_advantage from each dimension's LLM output
        advantages = []
        for dim_data in dims_data:
            dim_id = dim_data["id"]
            dim_result = all_scores.get(dim_id, {})
            advantage = dim_result.get("winner_advantage", "")
            if advantage:
                advantages.append(f"• {dim_data['name']}: {advantage}")

        rationale_lines = advantages if advantages else ["• 综合评分最高"]
        winner_rationale = f"Winner 在 {len(dims_data)} 个维度中综合表现最优：\n" + "\n".join(rationale_lines)

        rankings_list = []
        for rank_idx, entry in enumerate(ranking):
            sub = label_map[entry["label"]]
            rankings_list.append({
                "rank": rank_idx + 1,
                "submission_id": sub.id,
                "worker_id": sub.worker_id,
                "final_score": entry["final_score"],
            })

        comparative_feedback_json = json.dumps({
            "winner_rationale": winner_rationale,
            "rankings": rankings_list,
        }, ensure_ascii=False)

    # Write back to submissions
    for rank_idx, entry in enumerate(ranking):
        sub = label_map[entry["label"]]
        sub.oracle_feedback = json.dumps({
            "type": "scoring",
            "dimension_scores": entry["dimension_breakdown"],
            "weighted_base": entry["weighted_base"],
            "penalty": entry["penalty"],
            "penalty_reasons": entry["penalty_reasons"],
            "final_score": entry["final_score"],
            "risk_flags": entry["risk_flags"],
            "rank": rank_idx + 1,
        })
        sub.score = entry["final_score"] / 100.0
        sub.status = SubmissionStatus.scored

        # Only winner gets comparative_feedback
        if rank_idx == 0 and comparative_feedback_json:
            sub.comparative_feedback = comparative_feedback_json

    # Mark remaining eligible subs (outside top 3) as scored
    for sub in eligible:
        if sub not in [label_map[a["label"]] for a in anonymized]:
            sub.status = SubmissionStatus.scored
            if not sub.score:
                sub.score = _get_individual_weighted_total(sub, dimensions) / 100.0

    db.commit()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_comparative_visibility.py::test_batch_score_sets_comparative_feedback_on_winner -v`

Expected: PASS.

**Step 5: Run existing batch_score tests to check no regressions**

Run: `pytest tests/test_oracle_v2_service.py -v`

Expected: All PASS.

**Step 6: Commit**

```bash
git add app/services/oracle.py tests/test_comparative_visibility.py
git commit -m "feat: assemble comparative_feedback from winner_advantage in batch_score"
```

---

### Task 5: Update frontend Submission type + FeedbackCard phase-based display

**Files:**
- Modify: `frontend/lib/api.ts:60-70` (Submission interface)
- Modify: `frontend/components/FeedbackCard.tsx` (phase-based display logic)

**Step 1: Add `comparative_feedback` to Submission interface**

In `frontend/lib/api.ts`, add after line 67 (`oracle_feedback`):

```typescript
comparative_feedback: string | null
```

**Step 2: Update FeedbackCard to accept task status and change display logic**

Rewrite `frontend/components/FeedbackCard.tsx`:

```tsx
'use client'
import { useState } from 'react'

interface GateCheckResult {
  criterion: string
  passed: boolean
  reason?: string
}

interface GateCheckFeedback {
  type: 'gate_check'
  overall_passed: boolean
  criteria_results?: GateCheckResult[]
  summary?: string
}

interface DimensionScore {
  band: string
  score: number
  evidence?: string
  feedback?: string
}

interface RevisionSuggestion {
  problem: string
  suggestion: string
  severity: 'high' | 'medium' | 'low'
}

interface IndividualScoringFeedback {
  type: 'individual_scoring'
  dimension_scores?: Record<string, DimensionScore>
  overall_band?: string
  revision_suggestions?: RevisionSuggestion[]
}

interface ScoringFeedback {
  type: 'scoring'
  gate_check?: { overall_passed: boolean; summary?: string }
  dimension_scores?: Record<string, DimensionScore>
  overall_band?: string
  revision_suggestions?: RevisionSuggestion[]
  passed?: boolean
}

type OracleFeedback = GateCheckFeedback | IndividualScoringFeedback | ScoringFeedback

const SEVERITY_LABEL: Record<string, string> = {
  high:   'High',
  medium: 'Mid',
  low:    'Low',
}

const SEVERITY_COLOR: Record<string, string> = {
  high:   'text-red-400',
  medium: 'text-yellow-400',
  low:    'text-zinc-400',
}

const BAND_COLOR: Record<string, string> = {
  A: 'text-green-400',
  B: 'text-blue-400',
  C: 'text-yellow-400',
  D: 'text-orange-400',
  E: 'text-red-400',
}

function BandBadge({ band }: { band: string }) {
  return (
    <span className={['font-mono font-bold', BAND_COLOR[band] ?? 'text-white'].join(' ')}>
      [{band}]
    </span>
  )
}

function DimTable({ dims }: { dims: Record<string, DimensionScore> }) {
  return (
    <table className="w-full text-[11px] mt-1">
      <thead>
        <tr className="text-muted-foreground border-b border-zinc-800">
          <th className="text-left py-0.5 font-normal">维度</th>
          <th className="text-center py-0.5 font-normal w-8">Band</th>
          <th className="text-right py-0.5 font-normal w-10">分数</th>
          <th className="text-left py-0.5 font-normal pl-2">依据</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(dims).map(([id, d]) => (
          <tr key={id} className="border-b border-zinc-800/50">
            <td className="py-0.5 text-muted-foreground pr-2">{id}</td>
            <td className="py-0.5 text-center"><BandBadge band={d.band} /></td>
            <td className="py-0.5 text-right font-mono text-white">{d.score}</td>
            <td className="py-0.5 pl-2 text-muted-foreground truncate max-w-[200px]" title={d.evidence}>{d.evidence ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Suggestions({ suggestions }: { suggestions: RevisionSuggestion[] }) {
  return (
    <div className="space-y-1.5">
      {suggestions.map((s, i) => (
        <div key={i} className="flex gap-1.5">
          <span className={['shrink-0 text-[9px] font-bold w-8 mt-0.5', SEVERITY_COLOR[s.severity] ?? ''].join(' ')}>
            {SEVERITY_LABEL[s.severity] ?? s.severity}
          </span>
          <div>
            <p className="text-white leading-tight">{s.problem}</p>
            <p className="text-muted-foreground leading-tight">→ {s.suggestion}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

interface FeedbackCardProps {
  raw: string
  taskStatus?: string
}

export function FeedbackCard({ raw, taskStatus }: FeedbackCardProps) {
  const [showDims, setShowDims] = useState(false)

  let data: OracleFeedback
  try {
    data = JSON.parse(raw)
  } catch {
    return <p className="text-muted-foreground text-[11px] break-all">{raw}</p>
  }

  const isOpen = taskStatus === 'open'

  if (data.type === 'gate_check') {
    return (
      <div className="space-y-1 text-[11px]">
        <div className="flex items-center gap-2">
          <span className={data.overall_passed ? 'text-green-400 font-medium' : 'text-red-400 font-medium'}>
            Gate {data.overall_passed ? '✓ 通过' : '✗ 未通过'}
          </span>
        </div>
        {data.summary && <p className="text-muted-foreground">{data.summary}</p>}
        {!data.overall_passed && data.criteria_results && (
          <ul className="space-y-0.5 pl-2">
            {data.criteria_results.filter(c => !c.passed).map((c, i) => (
              <li key={i} className="text-red-300">
                ✗ {c.criterion}{c.reason ? `：${c.reason}` : ''}
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  if (data.type === 'individual_scoring') {
    return (
      <div className="space-y-2 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="text-blue-400 font-medium">个人评分</span>
          {!isOpen && data.overall_band && <BandBadge band={data.overall_band} />}
        </div>
        {/* open 阶段：只显示修订建议 */}
        {isOpen && data.revision_suggestions && data.revision_suggestions.length > 0 && (
          <div>
            <p className="text-muted-foreground mb-1">修订建议：</p>
            <Suggestions suggestions={data.revision_suggestions} />
          </div>
        )}
        {/* scoring 及之后：显示 band/score/evidence，不显示修订建议 */}
        {!isOpen && data.dimension_scores && (
          <div>
            <button
              type="button"
              onClick={() => setShowDims(!showDims)}
              className="text-muted-foreground hover:text-white text-[11px]"
            >
              {showDims ? '▲ 隐藏维度详情' : '▼ 查看维度详情'}
            </button>
            {showDims && <DimTable dims={data.dimension_scores} />}
          </div>
        )}
      </div>
    )
  }

  if (data.type === 'scoring') {
    return (
      <div className="space-y-2 text-[11px]">
        <div className="flex items-center gap-2">
          {data.gate_check && (
            <span className={data.gate_check.overall_passed ? 'text-green-400' : 'text-red-400'}>
              Gate {data.gate_check.overall_passed ? '✓' : '✗'}
            </span>
          )}
          {data.overall_band && <BandBadge band={data.overall_band} />}
        </div>
        {/* scoring type always shows dimensions (only visible in scoring+ phases via API) */}
        {data.dimension_scores && (
          <div>
            <button
              type="button"
              onClick={() => setShowDims(!showDims)}
              className="text-muted-foreground hover:text-white text-[11px]"
            >
              {showDims ? '▲ 隐藏' : '▼ 维度详情'}
            </button>
            {showDims && <DimTable dims={data.dimension_scores} />}
          </div>
        )}
      </div>
    )
  }

  return (
    <pre className="text-[10px] text-muted-foreground overflow-auto max-h-32 whitespace-pre-wrap break-all">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
```

Key changes:
- `FeedbackCard` now accepts optional `taskStatus` prop
- `SEVERITY_LABEL` maps `high`→`High`, `medium`→`Mid`, `low`→`Low`
- `individual_scoring` type: open phase shows revision suggestions only (no band); scoring+ shows band/score/evidence (no suggestions)
- `DimTable` now shows `evidence` column
- `scoring` type: no revision suggestions shown (these come from individual scoring only)

**Step 3: Run frontend tests**

Run: `cd frontend && npm test`

Expected: All PASS (FeedbackCard tests may need updating if they exist).

**Step 4: Commit**

```bash
git add frontend/lib/api.ts frontend/components/FeedbackCard.tsx
git commit -m "feat: phase-based FeedbackCard display + severity label mapping"
```

---

### Task 6: Add ComparativeTab component + integrate into SubmissionTable

**Files:**
- Create: `frontend/components/ComparativeTab.tsx`
- Modify: `frontend/components/SubmissionTable.tsx`

**Step 1: Create ComparativeTab component**

Create `frontend/components/ComparativeTab.tsx`:

```tsx
'use client'

interface Ranking {
  rank: number
  submission_id: string
  worker_id: string
  final_score: number
}

interface ComparativeFeedback {
  winner_rationale: string
  rankings: Ranking[]
}

interface ComparativeTabProps {
  comparativeFeedback: string | null
  taskStatus: string
  allSubmissions: { id: string; worker_id: string; comparative_feedback: string | null }[]
}

function WorkerName({ workerId }: { workerId: string }) {
  // Reuse the useUser hook from api
  const { useUser } = require('@/lib/api')
  const { data: user } = useUser(workerId)
  return <span>{user?.nickname ?? workerId.slice(0, 8) + '…'}</span>
}

export function ComparativeTab({ comparativeFeedback, taskStatus, allSubmissions }: ComparativeTabProps) {
  const isVisible = !['open', 'scoring'].includes(taskStatus)

  if (!isVisible) {
    return (
      <div className="text-muted-foreground text-[11px] py-2">
        评分中，待公开
      </div>
    )
  }

  // Find comparative_feedback from winner submission if current sub doesn't have it
  const feedbackSource = comparativeFeedback
    ?? allSubmissions.find(s => s.comparative_feedback)?.comparative_feedback

  if (!feedbackSource) {
    return (
      <div className="text-muted-foreground text-[11px] py-2">
        暂无横向比较数据
      </div>
    )
  }

  let cf: ComparativeFeedback
  try {
    cf = JSON.parse(feedbackSource)
  } catch {
    return null
  }

  return (
    <div className="space-y-3 text-[11px]">
      <div>
        <p className="text-muted-foreground mb-1.5 font-medium">排名</p>
        <table className="w-full">
          <thead>
            <tr className="text-muted-foreground border-b border-zinc-800">
              <th className="text-left py-0.5 font-normal w-8">#</th>
              <th className="text-left py-0.5 font-normal">Worker</th>
              <th className="text-right py-0.5 font-normal w-14">分数</th>
            </tr>
          </thead>
          <tbody>
            {cf.rankings.map((r) => (
              <tr key={r.submission_id} className={`border-b border-zinc-800/50 ${r.rank === 1 ? 'text-yellow-400' : ''}`}>
                <td className="py-0.5 font-mono">{r.rank}</td>
                <td className="py-0.5"><WorkerName workerId={r.worker_id} /></td>
                <td className="py-0.5 text-right font-mono">{r.final_score.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <p className="text-muted-foreground mb-1 font-medium">横向比较分析</p>
        <div className="text-white whitespace-pre-wrap leading-relaxed">
          {cf.winner_rationale}
        </div>
      </div>
    </div>
  )
}
```

**Step 2: Update SubmissionTable to add tabs**

Rewrite `frontend/components/SubmissionTable.tsx` to add a tabbed interface per submission:

```tsx
'use client'

import { useState } from 'react'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Submission, Task, useUser } from '@/lib/api'
import { TrustBadge } from '@/components/TrustBadge'
import { FeedbackCard } from '@/components/FeedbackCard'
import { ComparativeTab } from '@/components/ComparativeTab'
import { scoreColor } from '@/lib/utils'

function WorkerCell({ workerId }: { workerId: string }) {
  const { data: user } = useUser(workerId)
  if (!user) {
    return <span className="font-mono text-xs text-muted-foreground">{workerId.slice(0, 8)}…</span>
  }
  return (
    <span className="flex items-center gap-1.5 flex-wrap">
      <span className="text-sm">{user.nickname}</span>
      <TrustBadge tier={user.trust_tier} score={user.trust_score} />
    </span>
  )
}

const STATUS_COLOR: Record<string, string> = {
  pending:         'text-muted-foreground',
  gate_passed:     'text-blue-400',
  gate_failed:     'text-red-400',
  policy_violation:'text-orange-400',
  scored:          'text-green-400',
}

interface Props {
  submissions: Submission[]
  task: Task
}

function isTopRanked(sub: Submission): boolean {
  if (!sub.oracle_feedback) return false
  try {
    const fb = JSON.parse(sub.oracle_feedback)
    return fb.type === 'scoring' && typeof fb.rank === 'number' && fb.rank <= 3
  } catch {
    return false
  }
}

function SubmissionFeedbackCell({ sub, task, allSubmissions }: { sub: Submission; task: Task; allSubmissions: Submission[] }) {
  const [activeTab, setActiveTab] = useState<'feedback' | 'comparative'>('feedback')
  const showComparativeTab = task.type === 'quality_first' && isTopRanked(sub)

  if (!sub.oracle_feedback && !showComparativeTab) {
    return <span className="text-muted-foreground text-xs">—</span>
  }

  if (!showComparativeTab) {
    return sub.oracle_feedback
      ? <FeedbackCard raw={sub.oracle_feedback} taskStatus={task.status} />
      : <span className="text-muted-foreground text-xs">—</span>
  }

  return (
    <div>
      <div className="flex gap-2 mb-1.5 border-b border-zinc-800 pb-1">
        <button
          type="button"
          onClick={() => setActiveTab('feedback')}
          className={`text-[11px] px-1.5 py-0.5 rounded ${activeTab === 'feedback' ? 'bg-zinc-700 text-white' : 'text-muted-foreground hover:text-white'}`}
        >
          评分详情
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('comparative')}
          className={`text-[11px] px-1.5 py-0.5 rounded ${activeTab === 'comparative' ? 'bg-zinc-700 text-white' : 'text-muted-foreground hover:text-white'}`}
        >
          横向比较
        </button>
      </div>
      {activeTab === 'feedback' && sub.oracle_feedback && (
        <FeedbackCard raw={sub.oracle_feedback} taskStatus={task.status} />
      )}
      {activeTab === 'comparative' && (
        <ComparativeTab
          comparativeFeedback={sub.comparative_feedback}
          taskStatus={task.status}
          allSubmissions={allSubmissions}
        />
      )}
    </div>
  )
}

export function SubmissionTable({ submissions, task }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-32">Worker</TableHead>
          <TableHead className="w-8 text-center">Rev</TableHead>
          <TableHead className="w-16 text-center">Score</TableHead>
          <TableHead className="w-24">Status</TableHead>
          <TableHead>Oracle Feedback</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {submissions.map((sub) => {
          const isWinner = sub.id === task.winner_submission_id
          return (
            <TableRow
              key={sub.id}
              className={isWinner ? 'bg-yellow-500/10 border-yellow-500/30' : ''}
            >
              <TableCell>
                <WorkerCell workerId={sub.worker_id} />
              </TableCell>
              <TableCell className="text-center text-sm text-muted-foreground">
                {sub.revision}
              </TableCell>
              <TableCell className={`text-center font-mono text-sm ${scoreColor(sub.score, task.threshold)}`}>
                {sub.score !== null ? (sub.score * 100).toFixed(1) : '—'}
                {isWinner && ' 🏆'}
              </TableCell>
              <TableCell className={`text-xs ${STATUS_COLOR[sub.status] ?? 'text-muted-foreground'}`}>
                {sub.status.replace('_', ' ')}
              </TableCell>
              <TableCell className="py-2 max-w-sm">
                <SubmissionFeedbackCell sub={sub} task={task} allSubmissions={submissions} />
              </TableCell>
            </TableRow>
          )
        })}
        {submissions.length === 0 && (
          <TableRow>
            <TableCell colSpan={5} className="text-center text-muted-foreground py-8 text-sm">
              No submissions yet
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
```

Key changes:
- `isTopRanked()` checks if submission has `rank <= 3` in oracle_feedback
- `SubmissionFeedbackCell` adds tab switching for top 3 submissions
- Two tabs: "评分详情" (existing FeedbackCard) and "横向比较" (new ComparativeTab)
- `FeedbackCard` now receives `taskStatus` prop
- `ComparativeTab` looks for `comparative_feedback` from the winner if current sub doesn't have it

**Step 3: Run frontend tests**

Run: `cd frontend && npm test`

Expected: All PASS.

**Step 4: Commit**

```bash
git add frontend/components/ComparativeTab.tsx frontend/components/SubmissionTable.tsx
git commit -m "feat: add ComparativeTab and tabbed submission feedback display"
```

---

### Task 7: Final integration testing

**Files:** None (testing only)

**Step 1: Run all backend tests**

Run: `pytest -v`

Expected: All PASS.

**Step 2: Run all frontend tests**

Run: `cd frontend && npm test`

Expected: All PASS.

**Step 3: Run frontend lint**

Run: `cd frontend && npm run lint`

Expected: No errors.

**Step 4: Final commit (if any fixes needed)**

If any test fixes or lint fixes were needed, commit them.
