# Progress log

> Auto-updated by the `run-all` skill. This is your window into an unattended run:
> what finished, what is blocked, and where the run stopped.

<!-- Entries are appended below, one per phase. Examples:

phase 01: DONE — auth scaffolding + login endpoint, 14 tests green
phase 02: DONE — session store + refresh tokens, 9 tests green
phase 03: BLOCKED — tester STATUS: BLOCKING, 2 integration tests fail (DB timeout)

ALL PHASES COMPLETE
-->

phase 01: DONE — foundation: gauntlet CLI (run/list/report), Pydantic config + YAML loader, structured logging, TargetAdapter ABC + HTTP adapter (openai/anthropic/openrouter/ollama/openai-compatible + custom providers), RunRecord model. 41 tests green, ruff clean. reviewer + tester STATUS: PASS.
phase 02: DONE — attack-pack schema (Attack model + discriminated success_when union), packloader with strict validation + license gating (allowlist + opt-in), 12 bundled Apache-2.0 packs (6 prompt-injection + 6 jailbreak, OWASP 2025/ATLAS mapped), CLI list --packs wired. 79 tests green (41+38), ruff clean. reviewer + tester STATUS: PASS.
phase 03: DONE — async Runner engine: bounded concurrency (semaphore), rate-limit gate, seeded full-jitter retries + error taxonomy, per-request timeouts, token/cost accounting (pricing table), atomic resumable RunRecord persistence, CLI run wired (--pack/--dry-run/--resume/--out). Crash-safe (failing attack→ERROR, run completes). 107 tests green (79+28), deterministic & offline, ruff clean. reviewer + tester STATUS: PASS.
phase 04: DONE — Scoring T1 (deterministic canary/regex + refusal markers) + T2 (pluggable Classifier protocol + bundled pure LexicalClassifier, ambiguous-only escalation), verdict schema locked (PASS=defended, FAIL=attack-succeeded), ScoreDetail, ASR overall + by-category + metrics_summary, scorer wired into runner + report. Contract updates: asr denominator scored-only, executed sends now scored. 137 tests green (+30), deterministic & offline, ruff clean. reviewer + tester STATUS: PASS.
phase 05: DONE — ⭐ TUI scoreboard (Textual): pure zero-Textual ScoreboardState view-model (per-category grid, ASR, elapsed/cost/progress, severity flags, failure list, repro string), additive Runner on_attempt hook for live updates, ScoreboardApp (header/grid/detail panes) with hotkeys (j/k filter f/c/s explain copy-repro rerun quit), cli run --tui. Live bridge via post_message (no deadlock). 175 tests green (+38), Textual run_test pilot tests deterministic across 3 runs, offline, ruff clean. reviewer + tester STATUS: PASS.
phase 06: DONE — T3 LLM-judge (opt-in, default OFF): Judge protocol + FakeJudge + adapter-backed AdapterJudge (reuses target machinery), versioned rubric (RUBRIC_V1) + N-vote ensemble (majority, tie→defended), JudgeCheck handling, contested-only escalation via async score_async (sync score unchanged). Benign controls (is_control, control/ namespace) + utility-under-attack metric in report. No import cycle. 226 tests green (+51), inert when disabled, offline (FakeJudge/FakeAdapter), ruff clean. reviewer + tester STATUS: PASS.
