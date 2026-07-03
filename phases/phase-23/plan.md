# Phase 23 — implementation plan

Derived from `phases/phase-23/spec.md`. One milestone, ending in a checkpoint (ruff clean + pytest
green + reviewer/tester STATUS: PASS).

---

## Milestone 1 — menu report viewer

**Steps**
1. **`reports.py` — extract `render_text(record) -> str`:** move the `report` command's inline text body
   (cli.py ~687-721: `Run <id>`, target, status, attempts, `ASR (overall): N%`, `utility-under-attack`,
   controls line when any, the `scored/succeeded/defended/errored/skipped` line, and `by category` /
   `by OWASP` / `by ATLAS` sorted breakdowns) into a pure function returning the joined lines. Reproduce
   the strings EXACTLY (tests assert substrings like `"ASR (overall): 66.67%"`, `"by category:"`,
   `"by OWASP:"`, `"utility-under-attack: 50.00%"` / `"n/a"`).
2. **`cli.py` — `report` command text branch:** replace the inline echoes with
   `typer.echo(reportsmod.render_text(record))` (behavior identical; single source).
3. **`cli.py` — `_list_run_records(cfg) -> list[tuple[Path, str]]`:** glob `*.json` under
   `cfg.run.output_dir`, newest-first by mtime, cap at 20; per file load the record and build a label
   `f"{target} ({provider}/{model}) · {n} atk · ASR {asr:.0%} · {status}"`; a load failure falls back to
   the filename. Missing dir → `[]`.
4. **`cli.py` — `_menu_reports(cfg)`:** if no records → `"no run records in <dir> — fire a run first"`
   + `_pause_menu()` + return. Else pick one — TTY+questionary `questionary.select("which run?", …)`
   over the labels (value = index), else a numbered `typer.prompt` fallback (`_reports_letter_pick`);
   `None`/cancel → return cfg. Load the chosen record (ConfigError/parse guarded → `error:` line), then
   `typer.echo(reports.render_text(rec))`, echo the `full: grendel report --run <path> --format md`
   hint, `_pause_menu()`, return cfg. (Read-only: never mutates cfg.)
5. **`cli.py` — wire both home loops:** add `[e] reports  · view a past run's report` to `_home_letter`
   (dispatch `elif choice == "e": _menu_reports(cfg)`) and a matching `questionary.Choice("reports ·
   view a past run's report", "reports")` + `elif choice == "reports": _menu_reports(cfg)` in
   `_home_questionary`. (`_menu_reports` returns cfg unchanged; keep the `cfg = ...` assignment style for
   consistency.)
6. **Tests:**
   - `test_reports_render_text` (new, in `tests/test_reports.py` or `test_cli_report.py`): `render_text`
     of a small record contains the key substrings; the `report` command still prints them (regression —
     existing report tests already cover this, just confirm green).
   - `test_cli_home.py`: `test_home_menu_reports_lists_and_renders` — write a run record into
     `tmp_path/runs`, set `output_dir` (via a written grendel.yaml with `run.output_dir: runs`, discovered
     with `GRENDEL_NO_AUTOCONFIG` delenv), drive `e` → pick `1` → assert the report text (`ASR (overall)`)
     and the `full: grendel report` hint appear; `test_home_menu_reports_empty` — `e` with no records →
     the "no run records" line, no crash.

**Checkpoint 1 (phase close):** full suite green + ruff clean; reviewer + tester STATUS: PASS; append
`phase 23: DONE …` to PROGRESS.md.

---

## Risks & mitigations
- **Breaking the `report` command output** → `render_text` reproduces the exact strings; existing
  `test_cli_report.py` substring assertions are the guard.
- **A corrupt/partial record in the list** → per-file load wrapped; label falls back to filename; the
  viewer guards the chosen-record load with an `error:` line (never crashes the menu).
- **output_dir missing / relative** → `_list_run_records` returns `[]` → the empty-state message.
- **cp1254** → plain text via typer.echo through the installed console fallback; no rich, no fancy glyphs.
- **Large records (1517 attempts)** → the text report is metrics-only (no per-attempt dump), so it's
  small regardless of attempt count; the full per-finding view stays in `grendel report --format md`.
