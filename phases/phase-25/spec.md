# Phase 25 — in-app results browser (which got through / which were defended)

## Problem (user feedback)
After a run the aggregate report card isn't enough — the user can't see WHICH attacks got through vs
which were defended, and having to run `grendel report` separately is "çok yorucu". They want to browse
the per-attempt results inside the menu: filter by outcome and drill into each attack's prompt, the
agent's response, and why the scorer decided.

Constraint (user): analysis/inspection is the APP's own capability, read from the RunRecord — never
delegated to the target model (the target is what's being attacked, not an analyst). No LLM.

## Goal
An interactive results browser, reachable right after a run AND from the `[r] reports` viewer:
- A filter over outcomes: **got through** (hit/FAIL) · **defended** (PASS) · **errors** (ERROR) · all.
- A selectable list of the filtered attempts (attack id · category), arrow-key on a TTY / numbered off.
- A per-attempt **detail card**: attack id, category, colored verdict, the PROMPT sent, the agent's
  RESPONSE, and the scorer's reason (score_detail) — so the user understands each pass/hit.
- Same rich visual language as the dashboard/report card; cp1254-safe; off-TTY plain-text fallback.

## Non-goals
- No LLM/AI-written report, no target-model dependency, no browser auto-open (dropped per user).
- No change to the run engine, scoring, record format, or the `report`/`run` subcommands.
- Off-TTY / pipes / tests: behaviour stays deterministic (letter/numbered fallback testable;
  questionary path offline-untestable per convention).

## Dev strategy
Established phase workflow: plan → plan-reviewer → implement → reviewer → tester → gates (ruff clean +
pytest green + STATUS: PASS) → append to PROGRESS.md. Eyeball a rendered detail card (unicode + ascii).
