# Weighted Task Priority Scoring Algorithm

Source: `backend/app/services/priority.py` (pure Python, no database, no AI, no network).
Tests: `backend/tests/test_priority.py` (unit) and `backend/tests/test_tasks_priority.py` (API).
Demo: `python -m scripts.demo_priority` (run from `backend/`).

## 1. Purpose
Rank the tasks of an activity so the user sees what needs attention first. The result is deterministic
(same inputs, same output), explainable (every result lists each factor and a sentence of reasons) and works with no AI.

## 2. Formula
```
Score (0-100) = 100 x ( 0.40 x DeadlineUrgency + 0.30 x TaskImportance + 0.15 x ActivityPriority + 0.15 x OverdueStatusRisk )
```
Each factor is normalized to 0..1 first, so the weights are directly comparable.

| Factor | Weight | Normalization |
|---|---|---|
| Deadline urgency | 0.40 | no deadline = 0; overdue = 1; otherwise `max(0, 1 - days_left / 14)` (due today = 1.0, in 7 days = 0.5, 14+ days = 0) |
| Task importance | 0.30 | `(importance - 1) / 4`, importance is the user's 1-5 rating |
| Activity priority | 0.15 | `(priority - 1) / 4`, priority of the activity the task belongs to |
| Overdue / status | 0.15 | overdue and incomplete = 1.0; not started (PENDING) = 0.5; IN_PROGRESS = 0.3 |

Completed tasks are never active priorities: score 0, `is_active = false`.

## 3. Classification
| Score | Level |
|---|---|
| 80 and above | CRITICAL |
| 60 to below 80 | HIGH |
| 35 to below 60 | MEDIUM |
| below 35 | LOW |

The user can override the level of a task (`manual_priority`). The API then shows the overridden level and still
reports the calculated score and calculated level, and the explanation says the level was set manually.
An override has no effect while the task is completed.

## 4. Why these numbers (design judgement, not proof)
The weights, the 14-day horizon, the status values and the thresholds are **design choices made to give sensible
rankings. They are not derived from data and are not scientifically proven.** The reasoning:
- **Deadline 0.40:** time pressure is the main reason a task needs attention now, so it gets the largest weight.
- **Importance 0.30:** a user-supplied judgement of consequences; it must be able to lift a task even when the deadline is not close, but not outweigh an overdue deadline.
- **Activity priority 0.15 and status 0.15:** supporting context. They separate otherwise similar tasks without dominating.
- **14-day horizon:** two weeks is a common planning window for coursework and personal deadlines; the urgency ramps up linearly so the rule is easy to explain.
- **Status risk:** an unstarted task is riskier than one already in progress, so PENDING (0.5) > IN_PROGRESS (0.3). Overdue (1.0) is the strongest signal.
- **Thresholds:** chosen so that the four required test cases fall in the expected levels and so that an overdue task with the top importance rating (5/5) is always Critical (at least 85 points, whatever the activity priority).

Because all values are named constants in one place, they can be tuned, and the effect of changing them can be re-tested.

## 5. Results of the required test cases (computed by `scripts.demo_priority`, reference date 2026-10-07, activity priority 3/5)
| Case | Deadline | Importance | Status | Deadline pts | Importance pts | Activity pts | Status pts | Score | Level |
|---|---|---|---|---|---|---|---|---|---|
| 1. Far deadline + low importance | in 30 days | 1/5 | PENDING | 0.00 | 0.00 | 7.50 | 7.50 | 15.00 | LOW |
| 2. Approaching deadline + high importance | in 3 days | 5/5 | PENDING | 31.43 | 30.00 | 7.50 | 7.50 | 76.43 | HIGH |
| 3. Overdue + high importance | 2 days overdue | 5/5 | PENDING | 40.00 | 30.00 | 7.50 | 15.00 | 92.50 | CRITICAL |
| 4. Completed task | 2 days overdue | 5/5 | COMPLETED | - | - | - | - | 0.00 | not active |

Example explanation (case 3): "Critical priority (score 92.5/100) because the deadline passed 2 days ago, the task
importance is very high (5/5), the activity priority is medium (3/5) and the task is overdue and still incomplete."

## 6. Testing
`tests/test_priority.py` has 20 unit tests: the four cases above, factor values, level boundaries (79.99/80, 59.99/60, 34.99/35),
score range (maximum 100.0, lowest open task 4.5), monotonic behaviour (more importance, higher activity priority or a closer
deadline never lowers the score), manual override, completed tasks, determinism and input validation.
Result in the development environment: 20 passed, 0 failed. `tests/test_tasks_priority.py` tests the same behaviour through the API.

## 7. Limitations (state these in the report)
- Weights and thresholds are judgement-based; no user study or data supports them.
- Importance is entered by the user; the system does not infer it.
- Deadline urgency is linear within 14 days; tasks several weeks away all score zero for urgency.
- Task dependencies, estimated effort and the activity's own deadline are not considered.
- "Today" uses the server's date; there is no per-user time zone.

## 8. Viva answers
- **Why not ask AI to prioritize?** The result must be repeatable, explainable and available offline. An LLM can give different answers to the same input and cannot show a verifiable calculation.
- **How were the weights chosen?** By reasoning about which factors matter most (section 4), then checking the results against test cases. They are not proven optimal and can be tuned.
- **What if the user disagrees?** They can override the level manually.
