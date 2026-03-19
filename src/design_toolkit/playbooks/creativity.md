# Creativity Playbook - Agent-Owned Section Review

Once the page is structurally sound, review section creativity yourself from the screenshots.

The goal is not "pretty enough." The goal is to avoid generic sections.

---

## When to Use

- after the page is visually coherent
- when the score is solid but not distinctive
- when some sections clearly lag behind others

Skip if the page is already excellent or the task is purely functional.

---

## Section Review

Identify the major sections top to bottom and score each from `0.0` to `1.0`.

### Scale

- `1.0`: distinctive, memorable, clearly intentional
- `0.7`: solid and non-generic
- `0.4`: functional but template-like
- `0.0`: broken, empty, placeholder, or absent

For each section, record:
- `label`
- `score`
- `confidence`
- `notes`

Use a structure like:

```json
{
  "sections": [
    {"label": "hero", "score": 0.92, "confidence": 0.84, "notes": "strong art direction"},
    {"label": "services", "score": 0.44, "confidence": 0.82, "notes": "generic equal cards"}
  ],
  "strong_labels": ["hero"],
  "weak_labels": ["services"],
  "avg_score": 0.68,
  "min_score": 0.44
}
```

This is your own artifact, not an MCP-generated answer.

---

## Strong vs Weak

- Strong sections: `>= 0.78`
- Weak sections: `< 0.78`

Do not touch strong sections unless they directly conflict with a weak-section fix.

---

## Fix Strategy

Fix at most 3 weak sections per round.

For each weak section, introduce one real signature move:
- asymmetric composition
- proof wall
- comparison strip
- timeline with rhythm
- layered CTA cluster
- strong before/after framing
- interactive-looking chips or filters
- tighter typography hierarchy

Do not count color changes alone as a signature move.

---

## Scope Discipline

- edit only the weak sections
- keep strong sections intact
- do not rewrite the whole page unless the weakness is global
- re-capture screenshots after the fix

---

## Recheck

After creativity fixes:
1. rerun deterministic gates if needed
2. capture fresh screenshots
3. rescore the page yourself
4. confirm the fix improved the weak sections without hurting the strong ones
