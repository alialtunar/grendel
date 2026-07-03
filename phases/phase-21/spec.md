# Phase 21 — full model lists + a live attack dashboard

## Problem (user feedback)
Two gaps in the interactive run flow:
1. **Model suggestions are too few.** Each provider shows only a handful of hand-written ids. The user
   wants the FULL, current model list for every provider — not a short static guess.
2. **The live run is a bare one-line counter.** The user wants a real-time, colorful dashboard
   (red = hit, green = defended) — "görsel şölen" — showing exactly what's happening as attacks fire.

## Goal
1. **Live model discovery.** On a TTY, fetch the provider's actual models from its own API
   (`/models` for openai/anthropic-style, `/api/tags` for ollama) and offer them in the picker; when
   no key/offline/unsupported, fall back to a broadened static suggestion list. Never a closed list —
   "✎ type another" always available. No hang: a short timeout, failures degrade silently.
2. **Rich live dashboard.** Replace the one-line counter (on a TTY) with a `rich` live view: a
   progress bar, running ASR%, colored counters (hits/defended/errors), and a scrolling stream of the
   most recent attempts glyphed + colored by verdict. Off-TTY / no-rich degrades to the existing plain
   counter (pipes/tests unaffected).

## Non-goals
- No closed/hardcoded model list — live fetch is authoritative, static is only a fallback; type-your-
  own always works.
- No full-screen Textual app (that was removed on purpose) — `rich.Live` inline only.
- No change to the `grendel run` subcommand output, the proxy, or scoring — dashboard is menu-run only.
- No blocking network in tests/pipes: fetching + the dashboard are TTY-gated; off-TTY behaviour is
  byte-identical to today.

## Decisions (user-approved)
- Model source: **live fetch + static fallback**.
- Live UI: **rich dashboard** (rich is already present transitively via typer; add it as an explicit
  dependency for hygiene since we now import it directly).

## Dev strategy
Established phase workflow: plan → plan-reviewer → implement → reviewer → tester → gates (ruff clean +
pytest green + STATUS: PASS) → append to PROGRESS.md.
