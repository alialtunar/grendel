# Phase 22 — dashboard polish: logo, panel, "sent" count, taller stream

## Problem (user feedback on the phase-21 live dashboard)
1. **"kaç tanesi LLM'e gitti?"** — the total-sent count isn't labelled; the user can't tell how many
   requests actually hit the model.
2. **Only ~10 recent rows visible; no way to see older ones.** The stream window is fixed at 12; on a
   tall terminal the user wants to see far more of the run as it happens.
3. **"çok daha güzel bir görsel şölen olabilir + GRENDEL logo."** The current view is a bare Group of
   lines; the user wants a real branded, bordered, colorful dashboard with the GRENDEL wordmark.

## Goal
Redesign the live dashboard (menu run, on a TTY) into a branded, bordered `rich` panel:
- **GRENDEL wordmark** at the top (reuse `banner.render_logo`, ASCII-degraded like everywhere else).
- **A real progress bar** + **ASR%** + a clearly labelled **`sent N/total`** counter (answers #1 — one
  request per attempt; errors are sent too, counted separately).
- **Colored stat row**: hits (red) / defended (green) / errors (yellow).
- **A taller stream** that fills the available terminal height (answers #2): show as many recent
  attempts as fit, newest first, colored by verdict; retain more history internally. Full history stays
  in the run record (`grendel report`) — a live repainting view can't be scrolled, so "see everything"
  is the saved record.

## Non-goals
- No mouse/scrollback inside the live view (a repainting `rich.Live` can't scroll) — fill the height
  and point to the saved record for the complete list.
- No change to counters/ASR semantics (still excludes `is_control`), to model fetching, to the run
  engine, or to the off-TTY / no-rich plain fallback (byte-identical to today).
- No crash on the user's Windows cp1254 console — keep `legacy_windows=False`, ASCII-degrade glyphs AND
  box/bar/rule characters, and the existing `install_console_fallback`.

## Decisions
- Presentation-only, all in `src/grendel/live.py`; reuse `render_logo`. No new dependency.

## Dev strategy
Established phase workflow: plan → plan-reviewer → implement → reviewer → tester → gates (ruff clean +
pytest green + STATUS: PASS) → append to PROGRESS.md.
