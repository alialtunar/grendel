# Phase 17 re-review (round 3) — boundary-level Unicode fix

Re-reviewed after the residual-crash findings from the prior review (three sites left
unconditionally emitting `—`/`·` outside the `unicode=` threading: `grendel config` letter-menu
labels, `grendel list`'s "(none configured) — ..." line + four other unconditional `—` sites, and
`grendel report --format md/html` without `--out`). The new fix abandons per-string `unicode=`
threading for those remaining sites and instead installs a codec error handler at the console
output boundary.

## What changed

- `src/grendel/banner.py`: `install_console_fallback()` registers a codec error handler
  (`grendel_console_fallback` → `_console_fallback`, mapping known glyphs via `_GLYPH_FALLBACKS`
  and anything unmapped to `?`) and calls `sys.stdout.reconfigure(errors=...)` /
  `sys.stderr.reconfigure(errors=...)`, guarded by `try/except (AttributeError, ValueError)` so it
  is a safe no-op on streams that can't be reconfigured (e.g. a test capture buffer or a
  duck-typed stand-in without `.reconfigure`).
- `src/grendel/cli.py`: `main()` (the `@app.callback`) calls `install_console_fallback()`
  unconditionally, before any output — including the bare-`grendel` banner branch and every
  subcommand, since Typer always runs the callback first.
- `tests/test_cli_encoding.py` (new): a fast unit test of the codec handler itself, plus a
  subprocess-based test (not `CliRunner`, which always captures UTF-8 and would hide this bug
  class) that runs bare `grendel`, `doctor`, `list` (no targets), and `config` (piped `q`) under
  `PYTHONIOENCODING=iso-8859-5` and `iso-8859-9`, asserting exit 0 and no traceback in stderr.

## Verification performed

1. **`config` letter-menu (`·`), `list` empty-targets (`—`)** — the two concretely-reproduced
   crashes from the prior review. Re-ran directly (not via CliRunner) under the exact codepages
   that previously crashed:
   - `PYTHONIOENCODING=iso-8859-5 grendel config` (piped `q`) → exit 0, no `UnicodeEncodeError`,
     no traceback.
   - `PYTHONIOENCODING=iso-8859-9 grendel list` (no targets) → exit 0, no `UnicodeEncodeError`,
     no traceback.
   Both previously-crashing invocations now succeed.

2. **`report --format md/html` without `--out` (the third, previously-unfixed path)** — built a
   real `RunRecord` JSON, then ran `grendel report --run <file> --format md` under
   `PYTHONIOENCODING=iso-8859-9` and `--format html` under `PYTHONIOENCODING=iso-8859-5`, both
   with output redirected to a file (simulating a piped/CI console):
   - `main()`'s callback runs `install_console_fallback()` before `report`'s body executes (Typer
     always invokes the `@app.callback` first), so `_emit`'s `typer.echo(rendered)` at
     `cli.py:553` benefits from the same boundary fix even though `reports.py` itself was **not**
     touched and still unconditionally emits `—`/`·` in its Markdown/HTML templates
     (`reports.py:62`, `122`, `128-129` confirmed unchanged by inspection).
   - iso-8859-9 result: exit 0, em-dash → `-` (`# Grendel report - \`rep1\``); middle dot
     round-tripped natively as raw `0xB7` (iso-8859-9 happens to retain Latin-1's `0xB7` for `·`,
     so no fallback was even needed there — confirmed by decoding the raw output bytes as
     iso-8859-9, which reproduces `·` correctly; the apparent "�" was only a terminal-display
     artifact of `cat`-ing iso-8859-9 bytes in a UTF-8 shell, not a real encoding failure).
   - iso-8859-5 result (a codepage that genuinely lacks `·`): exit 0, `·` correctly degraded to
     `.` in the decoded HTML output (`Category: inj . OWASP: LLM01 . ATLAS: AML.T0051`).
   Conclusion: the boundary fix does close this third path. Reasoning confirmed empirically, not
   just by code inspection, since the callback-runs-before-subcommand-body Typer behavior is the
   crux of the claim.

3. **Files remain UTF-8.** `_emit` (`cli.py:547-553`) writes `--out` files via
   `out.write_text(rendered, encoding="utf-8")` — this path never touches `sys.stdout`/its
   reconfigured error handler, so `report --out file.md` is unaffected by the boundary change, as
   claimed. Record JSON writes (`RunRecord.to_json` / file writes in the runner) are likewise
   untouched — the fix only reconfigures `sys.stdout`/`sys.stderr`.

4. **Fallback-installation safety.** Directly exercised `install_console_fallback()` against a
   `sys.stdout`/`sys.stderr` stand-in with no `.reconfigure` attribute at all (a plain object) —
   confirmed no exception propagates out of `install_console_fallback()` itself (the
   `try/except (AttributeError, ValueError)` correctly absorbs it), so pytest's capture streams and
   any other non-standard stream can't break this call.

5. **`ruff check .`** → `All checks passed!`. **`ruff format --check .`** → `101 files already
   formatted`.

6. **Full suite**: `python -m pytest -q` → `524 passed, 1 skipped in 22.07s`, offline, matches the
   reported count.

7. **`doctor` secret handling** — re-confirmed by reading `_env_key_lines`
   (`src/grendel/doctor.py:54-65`): only ever emits the presence glyph (`✓`/`✗` or
   `[set]`/`[   ]`) plus the env-var *name* (`var`), never `env.get(var)`'s value. No regression
   introduced by this change (it doesn't touch `doctor.py`'s logic at all, only the console
   encoding layer underneath it).

8. **§0 usability / no regression** — the fix is purely additive at the output boundary; no
   command's help text, exit codes, or "next:" hints changed. The originally-blocking §0 violation
   (a newcomer's `doctor` → `config` → `list` chain dying with a bare `UnicodeEncodeError`
   traceback on a non-UTF-8 console) is now closed for all three previously-identified residual
   sites, verified directly rather than only by code reading.

## Minor observations (non-blocking)

- `reports.py`'s Markdown/HTML templates still hardcode `—`/`·` with no `unicode` parameter, which
  is fine given the boundary fix protects the stdout path — but note that `--out <file>.md/html`
  files still contain the raw Unicode glyphs (correctly, since they're UTF-8 files opened by an
  editor, not a legacy-codepage terminal). This is intentional per the design note in `_emit`'s
  docstring and does not need further action.
- The unmapped-glyph fallback (`_GLYPH_FALLBACKS.get(ch, "?")`) means any future new glyph
  introduced elsewhere in the codebase that isn't in the small allow-list degrades silently to
  `?` rather than crashing — an acceptable, deliberate trade-off (graceful degradation over a
  hard crash), consistent with the stated design intent.

## Verdict

All three previously-BLOCKING residual crash paths (`config` letter-menu `·`, `list`/other
unconditional `—` sites, `report`-to-stdout `—`/`·`) are closed by the boundary-level fix,
confirmed by direct non-CliRunner reproduction on the exact codepages that previously crashed.
File writes remain UTF-8 and unaffected. `ruff` and the full offline suite are clean. No secret
leakage or usability regression found.

STATUS: PASS
