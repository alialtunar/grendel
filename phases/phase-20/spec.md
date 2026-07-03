# Phase 20 — guided run flow (pick, don't type)

## Problem
The interactive `run` menu's ad-hoc path (used when `cfg.targets` is empty) is a chain of bare
`typer.prompt`s with no guidance:
- **provider** picker defaults to `openai` with no explanation → user asks "why openai?" and can't
  add another provider from here.
- **model** is free-text only → "model listeleri gelmiyor", user has no idea what to enter.
- **packs** and **dry-run** prompts are unlabeled → user doesn't know what they choose.

## Goal
Make the run flow selectable and self-explaining, without hardcoding a closed model list.

Capabilities:
1. **Model picker with suggestions + own entry.** On a TTY, offer the provider's suggested models as
   an arrow-key list plus a "✎ type another model…" escape. Suggestions are DATA on the preset
   (`models`), not logic; the user can always type any model. Non-TTY keeps the typed fallback.
2. **Provider picker: no biased default + add a custom agent inline.** No preselected `openai` in the
   arrow-key (TTY) picker; the non-interactive letter/numbered fallback keeps a default so pipes/tests
   still resolve. Add a
   "+ add a custom agent (its own JSON API)" entry that runs the existing custom-agent flow, persists
   it into `cfg`, and runs against it.
3. **Explain packs & dry-run.** One short line before each: packs = which attack packs (blank = all
   bundled); dry-run = plan only, no network / real API calls.

## Non-goals
- No closed/hardcoded model list — suggestions only, always type-your-own.
- No change to the configured-target run path (it already skips provider/model).
- No new dependency; reuse `questionary` (TTY) + typed fallback (tests/pipes), same as existing menus.
- No change to the `run` subcommand (flags), only the interactive menu.

## Dev strategy
Established phase workflow: plan → plan-reviewer → implement → reviewer → tester → gates (ruff clean +
pytest green + STATUS: PASS) → append to PROGRESS.md.
