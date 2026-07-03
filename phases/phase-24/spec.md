# Phase 24 — a jaw-dropping live attack dashboard

## Goal (user)
"arayüzsel iyileştirmeler yap, attackları çok güzel bir şekilde göstermelisin, gören 'bu neymiş ya'
desin — o kadar iyi olmalı." Elevate the phase-22 live dashboard from a vertical stack into a real
two-column control-room view that makes attacks visually pop.

## What "wow" means here (concrete, objective additions)
1. **Two-column layout** (rich, via Table.grid so it renders headless/testable): LEFT = live stats +
   a per-category ASR breakdown with mini bars; RIGHT = a taller attack stream (newest first), colored
   by verdict. The GRENDEL wordmark heads it; a full-width progress footer anchors it.
2. **Per-category live ASR bars** — as attacks fire, show the top categories by volume, each with a
   colored mini bar and its running ASR (jailbreak ▓▓▓░ 28%, prompt-injection ▓▓▓▓ 41% …). This is the
   "show the attacks beautifully" core.
3. **Momentum metrics** — elapsed time, throughput (attacks/sec), and ETA in the footer, updating live.
4. **Latest-hit spotlight** — the most recent successful attack (FAIL) is highlighted so a breach
   jumps out.
5. **Polish** — a spinner/pulse while running, big colored ASR headline, tasteful box + rules + styles.

## Non-goals
- No new dependency (rich only, already present). No full-screen Textual app.
- No change to counters/ASR semantics (still exclude `is_control`), the run engine, scoring, or the
  off-TTY / no-rich plain-counter fallback (byte-identical to today).
- Must stay crash-safe on the user's Windows cp1254 console: ASCII-degrade ALL glyphs/bars/box/rule,
  keep `legacy_windows=False` + `install_console_fallback`.
- Must keep fitting the terminal (the phase-23 `_layout` height/width guards) — the new columns adapt,
  never overflow/scroll.

## Dev strategy
Established phase workflow: plan → plan-reviewer → implement → reviewer → tester → gates (ruff clean +
pytest green + STATUS: PASS) → append to PROGRESS.md. Verify the frame visually (render to a forced
terminal) for both unicode and ascii before gating.
