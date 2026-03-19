# Candidates Playbook - Agent-Owned Parallel Attempts

Generate multiple solution attempts in parallel when the task has real design variance.

The MCP does not create patches or isolate worktrees for you. You or your subagents own that.

---

## When to Use

- visual/UI work
- redesigns with multiple valid directions
- tasks where a weak first idea can waste a full review cycle

Skip for obvious single-path fixes.

---

## How Many Candidates

| Task complexity | Candidates |
|---|---|
| Small | 1-2 |
| Medium | 2-3 |
| Large / redesign | 3-4 |

---

## Candidate Calibration

Give each candidate a distinct creative posture:

### Candidate 0: Conservative
Follow existing patterns. Prioritize safety and correctness.

### Candidate 1: Creative
Push the look harder. Introduce at least one memorable signature moment.

### Candidate 2: Minimal
Make the smallest viable change set that still satisfies the goal.

### Candidate 3: Ambitious
Rethink the section or page structure if a better result clearly exists.

---

## Candidate Contract

Each candidate should return:

```json
{
  "summary": "short description",
  "files_touched": ["..."],
  "risk_level": "low|medium|high",
  "notable_moves": ["..."],
  "followup_checks": ["..."]
}
```

The actual edits must be made by the agent or its subagents using native editing tools.

---

## Isolation Guidance

If your environment supports isolated work:
- use worktrees
- use temporary copies
- use parallel branches

If not:
- sequence candidates carefully
- save snapshots between attempts
- avoid losing a strong candidate while exploring a weaker one

---

## Candidate Review Loop

For each candidate:
1. edit code
2. run deterministic gates
3. capture screenshots
4. review screenshots yourself
5. iterate if needed

Do not let the MCP choose the winner. That is your job.
