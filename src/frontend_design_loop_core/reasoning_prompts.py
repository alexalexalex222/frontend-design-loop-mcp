"""Prompt-pack loading and native CLI reasoning overlays."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from frontend_design_loop_mcp.runtime_paths import get_default_prompts_path

_ROLE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("patch_generator", ("expert patch generator",)),
    ("patch_fixer", ("patch fixer", "code fixer for next.js")),
    ("ui_polisher", ("you are a ui polisher",)),
    ("vision_fixer", ("ui refiner driven by vision feedback",)),
    ("creativity_refiner", ("targeted ui section refiner", "creativity refiner")),
    ("vision_broken", ("strict website screenshot validator",)),
    ("vision_score", ("high-end ui judge", "ui design quality judge", "code-review judge")),
    ("section_creativity", ("section-level creativity evaluator",)),
    ("creative_director", ("creative director reviewing a website design", "world-class creative director")),
    (
        "planner_bold",
        (
            "bold engineering reasoner",
            "bold ui specification generator",
            "bold_layout_reasoner",
            "bold_conversion_reasoner",
        ),
    ),
    ("planner_minimal", ("minimal engineering reasoner", "minimal ui specification generator")),
    (
        "planner_safe",
        (
            "safe engineering reasoner",
            "safe ui specification generator",
            "ui specification generator.",
            "style_guardian_reasoner",
        ),
    ),
    ("planner_synth", ("synthesizer that merges", "ui_spec synthesizer")),
    (
        "refine_reasoner",
        (
            "technical translator. convert design feedback",
            "technical translator for a creative director workflow",
        ),
    ),
    (
        "refine_coder",
        (
            "implementing specific design improvements",
            "implementing surgical production fixes",
        ),
    ),
]

_PLANNER_ROLES = {
    "planner_bold",
    "planner_minimal",
    "planner_safe",
    "planner_synth",
}

_PATCH_ROLES = {
    "patch_generator",
    "patch_fixer",
    "ui_polisher",
    "vision_fixer",
    "creativity_refiner",
    "refine_reasoner",
    "refine_coder",
}

_VISION_ROLES = {
    "vision_broken",
    "vision_score",
    "section_creativity",
    "creative_director",
}


def detect_prompt_role(system_prompt: str, explicit_role: str | None = None) -> str:
    role = str(explicit_role or "").strip().lower()
    if role:
        return role

    lowered = str(system_prompt or "").strip().lower()
    for candidate, patterns in _ROLE_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return candidate
    return "generic"


def _prompt_root(prompt_root: Path | None) -> Path:
    root = Path(prompt_root).resolve() if prompt_root is not None else get_default_prompts_path()
    if root.exists():
        return root
    return get_default_prompts_path()


@lru_cache(maxsize=64)
def _read_prompt_text(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_prompt_pack(name: str, *, prompt_root: Path | None = None) -> str:
    root = _prompt_root(prompt_root)
    return _read_prompt_text(str(root / f"{name}.md"))


def _model_family(provider_name: str, model: str) -> str:
    provider_key = str(provider_name or "").strip().lower()
    model_key = str(model or "").strip().lower()

    if "minimax" in model_key:
        return "minimax"
    if provider_key == "claude_cli" or any(token in model_key for token in ("claude", "opus", "sonnet", "haiku")):
        return "claude"
    if provider_key == "codex_cli" or "gpt-5" in model_key or "codex" in model_key:
        return "codex"
    if provider_key == "gemini_cli" or "gemini" in model_key:
        return "gemini"
    if provider_key == "droid_cli":
        if any(token in model_key for token in ("claude", "opus", "sonnet", "haiku")):
            return "claude"
        if "gpt-5" in model_key or "codex" in model_key:
            return "codex"
        if "gemini" in model_key:
            return "gemini"
    if provider_key == "opencode_cli":
        if "anthropic/" in model_key or "claude" in model_key:
            return "claude"
        if "openai/" in model_key or "gpt-5" in model_key or "codex" in model_key:
            return "codex"
        if "google/" in model_key or "gemini" in model_key:
            return "gemini"
    return "generic"


def _family_prompt_name(provider_name: str, model: str) -> str | None:
    family = _model_family(provider_name, model)
    if family == "minimax":
        return "reasoning_minimax_free"
    if family == "claude":
        return "reasoning_opus46_interleaved"
    if family == "codex":
        return "reasoning_codex_impl"
    if family == "gemini":
        return "reasoning_gemini_thinking"
    return None


def _normalized_reasoning_profile(reasoning_profile: str | None) -> str:
    profile = str(reasoning_profile or "").strip().lower()
    if not profile:
        return "high"
    if profile == "off":
        return "none"
    if profile == "xhigh":
        return "max"
    return profile


def _reasoning_contract(reasoning_profile: str | None) -> str:
    profile = _normalized_reasoning_profile(reasoning_profile)
    return (
        "REASONING BUDGET\n"
        f"- Hidden reasoning target: {profile}.\n"
        "- Use the maximum internal reasoning budget that this runtime/model exposes for the task.\n"
        "- Do NOT dump hidden chain-of-thought, scratchpad, or narrated planning unless the output schema explicitly asks for it.\n"
        "- Convert deep reasoning into structured work products: evidence, alternatives, selected approach, risk ledger, and verification plan.\n"
        "- If the output contract is JSON-only, return only valid JSON and let the reasoning stay internal.\n"
    )


def _role_overlay(role: str) -> str:
    overlays: dict[str, str] = {
        "planner_bold": (
            "ROLE LANE: BOLD PLANNER\n"
            "- Generate multiple materially different approaches before committing.\n"
            "- Prefer the highest-leverage move that still preserves deterministic verification.\n"
            "- If there is a choice between safe-generic and bold-complete, choose bold-complete unless it creates clear regression risk.\n"
        ),
        "planner_minimal": (
            "ROLE LANE: MINIMAL PLANNER\n"
            "- Minimize blast radius.\n"
            "- Prefer the smallest diff that fully resolves the goal.\n"
            "- Strip away speculative refactors and decorative churn.\n"
        ),
        "planner_safe": (
            "ROLE LANE: SAFE PLANNER\n"
            "- Build an evidence-first plan with explicit regression checks.\n"
            "- Bias toward deterministic validation, reversible changes, and failure containment.\n"
            "- If context is ambiguous, surface the assumption inside the allowed schema and keep the patch strategy conservative.\n"
        ),
        "planner_synth": (
            "ROLE LANE: SYNTHESIZER\n"
            "- Merge bold leverage, minimal scope, and safe verification into one coherent plan.\n"
            "- Preserve the strongest idea from each lane; do not average them into blandness.\n"
            "- Output a single executable contract, not commentary about the merge process.\n"
        ),
        "patch_generator": (
            "ROLE LANE: PATCH GENERATOR\n"
            "- Diagnose the real change boundary before you emit a diff.\n"
            "- Favor surgical edits, exact schema compliance, and zero unrelated churn.\n"
            "- If the schema says unified diff hunks, NEVER return full file contents. Every patch string must include valid @@ hunks for exactly one file.\n"
            "- Anchor every patch to the exact file contents provided by the caller. Do not invent a prior file version just because a different layout would be easier to patch.\n"
            "- If a front-end rewrite is substantial, replace the whole file via a valid unified diff generated from the provided file text instead of hallucinating mid-file anchors.\n"
            "- When the task touches UX or presentation, add one memorable signature move if the scope allows it instead of shipping template sludge.\n"
            "- For front-end tasks, choose a composition and commit to it. Do not average your way into generic centered SaaS sludge.\n"
            "- If the page is dark, create depth with lighting, surfaces, and proof artifacts rather than flat color and generic feature grids.\n"
            "- Do not invent fake customer logos or placeholder trust rows when the brief does not provide real brands. Replace them with proof, telemetry, deployment evidence, or another credible signal.\n"
            "- If the hero already uses a terminal, dashboard, or command-center artifact, add a second distinct proof/control section deeper in the page instead of reverting to a generic feature grid.\n"
            "- Across the page, allow at most one uniform card grid. Change the rhythm with comparison, before/after, proof wall, routing timeline, or another denser structure.\n"
            "- Final CTA sections must still carry information density. Avoid large empty dark bands with one button.\n"
        ),
        "patch_fixer": (
            "ROLE LANE: PATCH FIXER\n"
            "- Treat logs, stack traces, and failing commands as hard evidence.\n"
            "- Find the causal fault, not the nearest symptom.\n"
            "- Preserve the required patch schema exactly. Do not fall back to whole-file rewrites unless the caller explicitly asks for them.\n"
            "- Repair only what is necessary to pass the gate while preserving already-strong work.\n"
        ),
        "ui_polisher": (
            "ROLE LANE: UI POLISHER\n"
            "- Upgrade weak craft without widening scope.\n"
            "- Improve hierarchy, rhythm, contrast, copy precision, and finish.\n"
            "- Keep the page coherent. Do not repaint strong sections just because you can.\n"
        ),
        "vision_fixer": (
            "ROLE LANE: VISION FIXER\n"
            "- Use the screenshots as the truth surface.\n"
            "- Fix only the weak or broken visual regions called out by the report.\n"
            "- Preserve strong sections. Do not flatten the page into a safe generic scaffold.\n"
            "- Introduce signature moments only where they improve memorability and remain build-safe.\n"
            "- If the report says generic, solve it with composition, proof, hierarchy, or art direction, not cosmetic spacing churn.\n"
        ),
        "creativity_refiner": (
            "ROLE LANE: TARGETED CREATIVITY REFINER\n"
            "- Improve ONLY the weak sections.\n"
            "- Each weak section must gain one signature moment: asymmetry, proof strip, comparison rail, timeline rhythm, layered cards, or another clearly deliberate move.\n"
            "- Keep strong sections locked. Do not rewrite the whole page.\n"
            "- When in doubt between safe-generic and bold-complete, choose bold-complete if it remains coherent and test-safe.\n"
            "- Decorative gradients alone do not count as a signature moment.\n"
            "- Do not add fake customer logos or placeholder trust bands as a shortcut to 'proof'.\n"
            "- If the hero is already the signature section, spend your effort on a second proof/control section or the closing action surface instead of repeating the same card rhythm.\n"
        ),
        "vision_broken": (
            "ROLE LANE: STRUCTURAL VISION GATE\n"
            "- Judge only structural breakage: runtime overlays, missing CSS, unusable collapse, 404s, blank output.\n"
            "- Ugly or boring is not broken.\n"
            "- If uncertain, fail open with broken=false.\n"
        ),
        "vision_score": (
            "ROLE LANE: VISION SCORER\n"
            "- Reward coherent creative risk and memorable craft.\n"
            "- Cap clean-but-generic work at 7.5.\n"
            "- Be precise about weak sections, viewport-specific issues, and what actually lifts the score.\n"
        ),
        "section_creativity": (
            "ROLE LANE: SECTION CREATIVITY SCORER\n"
            "- Map strong vs weak sections cleanly.\n"
            "- Reward distinctive structure, pacing, and art direction.\n"
            "- Keep notes short and concrete.\n"
        ),
        "creative_director": (
            "ROLE LANE: CREATIVE DIRECTOR\n"
            "- Separate what is unforgettable from what is merely competent.\n"
            "- Be specific about signature moments, hierarchy, and section-level drift.\n"
            "- Prefer actionable direction over vague taste adjectives.\n"
        ),
        "refine_reasoner": (
            "ROLE LANE: REFINEMENT REASONER\n"
            "- Translate design feedback into precise, code-addressable changes.\n"
            "- Separate observations, inferred causes, and concrete code actions.\n"
        ),
        "refine_coder": (
            "ROLE LANE: REFINEMENT CODER\n"
            "- Implement the approved improvement plan surgically.\n"
            "- Preserve working structure and only touch the parts needed to realize the design fix.\n"
        ),
        "generic": (
            "ROLE LANE: GENERAL EXECUTION\n"
            "- Work evidence-first.\n"
            "- Preserve scope discipline.\n"
            "- Return only the requested final output contract.\n"
        ),
    }
    return overlays.get(role, overlays["generic"])


def _pack_sequence(provider_name: str, model: str, role: str) -> list[str]:
    packs: list[str] = []
    if role in _PLANNER_ROLES:
        packs.append("reasoning_megamind")
    elif role in _PATCH_ROLES:
        packs.append("reasoning_deepthink")
    elif role in _VISION_ROLES:
        packs.append("reasoning_deepthink")

    family_pack = _family_prompt_name(provider_name, model)
    if family_pack and family_pack not in packs:
        packs.append(family_pack)
    if "reasoning_deepthink" not in packs and role == "generic":
        packs.append("reasoning_deepthink")
    return packs


def compose_native_cli_overlay(
    *,
    provider_name: str,
    model: str,
    reasoning_profile: str | None,
    system_prompt: str,
    prompt_role: str | None = None,
    prompt_root: Path | None = None,
) -> str:
    role = detect_prompt_role(system_prompt, prompt_role)
    packs = _pack_sequence(provider_name, model, role)

    sections: list[str] = [
        "NATIVE CLI REASONING HARNESS",
        _reasoning_contract(reasoning_profile),
        _role_overlay(role),
    ]

    for pack_name in packs:
        text = load_prompt_pack(pack_name, prompt_root=prompt_root)
        if text:
            sections.append(text)

    return "\n\n".join(section.strip() for section in sections if section and section.strip()).strip()
