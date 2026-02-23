# Quality-First Scoring Redesign

**Date:** 2026-02-23
**Branch:** agent-teams-test

## Overview

Redesign the quality_first submission flow so that:
- Submissions during the open phase receive 3 oracle revision suggestions (not a score)
- Scores are assigned in batch after the deadline (scoring phase)
- Scores are hidden from all workers until the task enters challenge_window
- Frontend shows task ID, dynamic countdowns for deadline and challenge window, and revision suggestions

---

## Section 1 — Oracle Layer

### `oracle/oracle.py`
Reads `mode` from the payload:
- `mode = "feedback"` → returns `{"suggestions": ["...", "...", "..."]}` (3 random revision suggestions, no score)
- `mode = "score"` → returns `{"score": <random 0.5–1.0>, "feedback": "..."}` (existing behavior)

### `app/services/oracle.py`
Two new functions:

- **`give_feedback(db, submission_id, task_id)`**
  Calls oracle in feedback mode. Stores result as JSON string in `submission.oracle_feedback`. Submission status remains `pending`.

- **`batch_score_submissions(db, task_id)`**
  Iterates all `pending` submissions for the task, calls oracle in score mode for each, sets `submission.score` and `submission.status = scored`.

### Entry point change
`invoke_oracle` (called from submission router):
- `quality_first` task → calls `give_feedback`
- `fastest_first` task → existing scoring logic unchanged

---

## Section 2 — Scheduler Layer

`app/scheduler.py` — `quality_first_lifecycle()`:

**Phase 1 (open → scoring):** After transitioning expired open tasks to `scoring`, immediately call `batch_score_submissions(db, task_id)` for each.

**Phase 2 (scoring → challenge_window):** Unchanged — waits until `pending_count == 0`, then selects winner and sets `challenge_window_end`.

Batch scoring is synchronous within the scheduler tick, so the next tick (1 min later) will find all submissions scored and advance to challenge_window.

---

## Section 3 — API Layer (Score Visibility)

`GET /tasks/{task_id}/submissions` and `GET /tasks/{task_id}/submissions/{sub_id}`:

| Task type | Task status | Score visible? |
|-----------|-------------|----------------|
| quality_first | open, scoring | No (score = null) |
| quality_first | challenge_window, arbitrating, closed | Yes |
| fastest_first | any | Yes |

Implemented as post-processing in the router after fetching submissions. No schema changes required.

---

## Section 4 — Frontend

### Revision suggestions
- After submission, parse `oracle_feedback` JSON array and render 3 bullet points
- quality_first open phase: hide score field entirely

### Task ID display
- Show `task.id` on task cards (truncated with copy option)

### Deadline countdown
- Replace static deadline timestamp with dynamic "X小时X分钟后到期"
- Updates every second; shows "已截止" when expired

### Challenge window countdown
- When `task.status === "challenge_window"`, show "挑战期剩余 X小时X分" using `challenge_window_end`
- Disappears when expired

### Default values
- `bounty`: default `0.01`
- `deadline duration`: default `5`, unit `minutes`
