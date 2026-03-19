# Vision Gate Playbook - Agent-Owned Screenshot Review

Use screenshots to review the page yourself. Do not call an external evaluator through MCP.

The agent is the judge.

---

## The Loop

For each candidate that is ready for visual review:

```text
1. preview_start(command, cwd)
2. capture_screenshots(url)
3. inspect the screenshots yourself
4. score the result yourself
5. preview_stop(pid)
```

If the score is below threshold, fix the page and repeat.

---

## Review Rubric

Score each category from `0.0` to `2.0`.

1. Craft and polish
2. Hierarchy and usability
3. Cohesive art direction
4. Content quality
5. Creative signature

Total score = sum of all five categories.

### Hard scoring rules

- If the page is broken, unusable, blank, or obviously busted: fail immediately.
- If the page is clean but generic: cap at `7.5`.
- If the page takes a strong tasteful risk that works: allow `8.5-10.0`.
- Do not reward decorative gradients alone as creativity.

---

## Review Output Format

Write your review in this shape:

```json
{
  "score": 0.0,
  "pass": false,
  "broken": false,
  "issues": ["..."],
  "highlights": ["..."],
  "fix_suggestions": ["..."]
}
```

This is not an MCP response. This is your own reasoning artifact.

---

## Broken Detection

Mark `broken=true` when you see:
- runtime overlay
- 404 / error page
- blank page
- missing CSS that makes the page unusable
- obvious layout collapse

If broken:
1. stop judging aesthetics
2. fix the root cause
3. rerun gates if needed
4. capture fresh screenshots

---

## Fix Strategy

When the page renders but scores low:
- fix only the weak areas first
- prefer layout, hierarchy, spacing, contrast, and CTA clarity changes
- if the page is structurally healthy but forgettable, add one signature move
- do not rewrite the whole file unless the problem is global

---

## Max Fix Rounds

- Default: 2 focused visual fix rounds per candidate
- If score improvement is less than `0.5` after a full round, stop and pick the best realistic state

---

## Threshold Guidance

- `>= 8.0`: good enough to ship if no major issues remain
- `9.0+`: excellent
- `< 8.0`: iterate unless time or scope makes that irrational
