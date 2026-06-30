---
name: run-all
description: Runs every phase in ROADMAP.md sequentially through the full phase loop until the whole project is built. Use whenever the user wants to build the entire project end-to-end autonomously, e.g. "run all phases", "build the whole thing", "do the full roadmap". Always stop at the first phase that cannot pass.
---

# Run all phases

Builds the entire project by running each phase of `ROADMAP.md` in order through
the `phase` skill, with a hard stop on any phase that cannot reach passing status.

## Steps

1. Read `ROADMAP.md` and list every phase in order.

2. Determine the starting phase: the first phase NN whose `phases/phase-NN/`
   folder does NOT contain a `test-report.md` ending in `STATUS: PASS`.
   (This makes the run resumable — already-finished phases are skipped.)

3. For each phase NN from the start, one at a time:
   1. Run the `phase` skill for phase NN, fully:
      spec → plan → `plan-reviewer` → implement milestone by milestone →
      `reviewer` + `tester` at each checkpoint, until BOTH report `STATUS: PASS`.
   2. Confirm `phases/phase-NN/review.md` AND `phases/phase-NN/test-report.md`
      both end in `STATUS: PASS`.
   3. Append one line to `PROGRESS.md`: `phase NN: DONE` (with a one-line summary).
   4. Only then move to phase NN+1.

4. **Hard stop on trouble.** If a phase cannot reach `STATUS: PASS` after a
   reasonable number of fix attempts, STOP. Do NOT skip ahead or start the next
   phase. Append `phase NN: BLOCKED — <reason>` to `PROGRESS.md` and report to
   the user what is blocking and what you tried.

5. When every phase is `DONE`, append `ALL PHASES COMPLETE` to `PROGRESS.md`
   and stop with a summary.

## Rules

- Never start phase NN+1 until phase NN is `DONE`. Phases are sequential and
  later phases may depend on earlier ones.
- Never weaken a checkpoint to make it pass. A real `STATUS: PASS` from an
  independent `reviewer` and `tester` is the only way forward.
- Keep all state in `phases/phase-NN/` files and `PROGRESS.md` so context stays
  small and the run is auditable.
