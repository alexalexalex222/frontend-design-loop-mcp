# Megamind Playbook - Agent-Owned Multi-Perspective Planning

Megamind is a planning discipline, not an MCP automation.

Use your own subagent or parallel-planning capability to produce three plans, then synthesize them yourself.

---

## When to Use

- complex UI work
- redesigns
- multi-file tasks with real tradeoffs
- anything where a single first idea is risky

Skip for trivial edits.

---

## The Three Plans

Create three independent plans:

### Bold
What is the highest-leverage version that still stays build-safe?

### Minimal
What is the smallest change that still satisfies the goal?

### Safe
What is the most robust version with the lowest regression risk?

---

## Required Output Shape

Have each planner return something like:

```json
{
  "summary": "one paragraph",
  "intent": "what success looks like",
  "repo_evidence": ["file or observation"],
  "assumptions": ["..."],
  "steps": ["ordered steps"],
  "files_to_read": ["..."],
  "changes": ["..."],
  "tests": ["..."],
  "risks": ["..."],
  "verification_checklist": ["..."]
}
```

---

## Synthesis Rule

Your final plan should:
- keep the strongest simplification from Bold
- keep the tightest scope from Minimal
- keep the best safety checks from Safe

Do not average them. Choose.
