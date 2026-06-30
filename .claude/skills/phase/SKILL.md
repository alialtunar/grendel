---
name: phase
description: Drives a single project phase end-to-end through the harness loop. Use this whenever the user says "/phase", "start phase N", "run the next phase", or wants to take one phase of the ROADMAP from spec to verified completion. Always use this for phase-by-phase delivery, even if the user does not say the word "phase" explicitly but is clearly working through the roadmap.
---

# Phase driver

Runs one phase of `ROADMAP.md` through the full loop:
spec → plan → reviewed plan → implementation → milestone verification → done.

## Input

The phase number (e.g. "phase 03"). If not given, read `ROADMAP.md` and pick the
first phase whose `phases/phase-NN/` folder has no passing `test-report.md`.

## Steps

1. **Set up the phase folder.** Create `phases/phase-NN/` if it does not exist.

2. **Spec.** Use the `brainstorming` skill to turn this phase's `ROADMAP.md` entry
   into a detailed spec. Save it as `phases/phase-NN/spec.md`.

3. **Plan.** Use the `writing-plans` skill to turn `spec.md` into an implementation
   plan. Save it as `phases/phase-NN/plan.md`. The plan MUST break the work into
   numbered milestones, each ending in a verifiable checkpoint.

4. **Review the plan.** Invoke the `plan-reviewer` agent. If it returns
   `STATUS: REVISE`, apply the fixes to `plan.md` and re-run it until `STATUS: PASS`.

5. **Implement, milestone by milestone.** For each milestone in `plan.md`:
   1. Implement that milestone's work.
   2. At the checkpoint, invoke the `reviewer` agent, then the `tester` agent.
   3. If either returns `STATUS: BLOCKING`, fix the issues and repeat step 5.2
      until BOTH return `STATUS: PASS`. Only then move to the next milestone.

6. **Close the phase.** When every milestone passes, confirm that `review.md` and
   `test-report.md` both end in `STATUS: PASS`, then summarize what shipped and stop.
   Do NOT start the next phase automatically — wait for the user to review and say go.

## Notes

- A `PostToolUse` gate hook runs a quick lint/typecheck after every edit. Treat its
  failures as must-fix before continuing.
- Keep all phase state in the `phases/phase-NN/` files (spec, plan, review, test-report)
  so the working context stays small and later phases can read earlier ones.
- To run a phase autonomously to completion, the user can pair this with:
  `/goal Complete phase NN per phases/phase-NN/plan.md, until review.md and
  test-report.md both say STATUS: PASS.`
