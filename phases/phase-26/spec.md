# Phase 26 — zero-knowledge onboarding (understand it on first launch)

## Problem (user feedback)
Someone who just `pipx install`ed Grendel and runs it for the first time may not know what it is or
what to do. The interface must be self-explanatory: on first launch they should immediately grasp
what Grendel does and the exact next step — no README needed.

## Goal
A first-run WELCOME shown at the top of the interactive home menu when nothing is configured yet
(fresh install / empty config):
- One or two lines on WHAT Grendel is (fires authorized attack packs at an LLM/agent target and shows
  which got through).
- A numbered **Get started in 3 steps** mapped to the exact menu keys:
  1. Add a target `[t]` — a hosted model + key, OR your own agent's HTTP URL.
  2. Fire attacks `[x]`.
  3. Read the results — the live dashboard + the in-app results browser (which got through).
- A "New? `[o]` doctor for a health check" nudge.
It appears only while the user has no targets configured; once they add one, the normal menu shows.
cp1254-safe (ASCII-degrade), off-TTY plain-text, and it also strengthens the non-TTY banner's
quickstart to match.

## Non-goals
- No wizard that hijacks the flow — the menu stays; the welcome is orientation, dismissed by acting.
- No change to the run engine, scoring, targets, or existing commands.
- No new dependency; reuse the existing banner/menu rendering + install_console_fallback.

## Dev strategy
Established phase workflow: plan → plan-reviewer → implement → reviewer → tester → gates (ruff clean +
pytest green + STATUS: PASS) → append to PROGRESS.md. This ships in the same release as the packaging
prep (grendel-redteam on PyPI/GitHub).
