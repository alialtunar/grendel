# Phase 16 — Code review (final)

Scope reviewed: `src/grendel/banner.py`, `src/grendel/cli.py` (config/targets/run/import/proxy
sections), `src/grendel/proxy.py`, `examples/langgraph-agent/*`, `tests/test_banner.py`,
`tests/test_cli_config.py`, `tests/test_example_agent.py`, `tests/test_proxy_core.py`,
`phases/phase-16/{spec,plan,test-report}.md`, `PROGRESS.md`.

Note: the repo's git history predates the gauntlet→grendel rename (last commit `c03d7e6` is
phase-10, still on `src/gauntlet`); `src/grendel/` is entirely untracked on disk, so this review
was done by reading current file state (not `git diff`) and cross-checking mtimes to confirm
out-of-scope modules were not touched.

## Findings

1. (Info, non-blocking) `banner.config_header(path, *, color=False)` does not take a `cfg`
   parameter, while `plan.md` step M1.1 specified `config_header(cfg, path, *, color)`. Harmless —
   only the path is shown in the header, both call sites (`cli.py:1058-1062`, `cli.py:1112-1117`)
   use it correctly, and `test_banner.py::test_config_header_has_brand_and_path` covers it.
   Cosmetic deviation from the plan only.

2. RESOLVED. `cli.py:780` now calls the public `session.enable_persistence(record_path)`
   (`proxy.py:207-209`) instead of assigning the private `_record_path` attribute directly.
   Confirmed by direct read of both files.

3. RESOLVED. `phases/phase-16/test-report.md` now has a "6. Live end-to-end validation" section:
   (a) direct real-API run — 6 prompt-injection attacks, asr 83.33%, report rendered with
   category/OWASP/ATLAS breakdown; (b) zero-touch proxy in front of the LangGraph agent —
   tool-abuse injected, the real `gpt-4o-mini`-backed agent emitted `send_email` to attacker
   addresses, asr 100% (LLM06/AML.T0051); documents the found+fixed proxy bug (bare `tool` message
   → valid assistant-tool_call + tool-result pair) and the incremental-persistence addition
   (survived a force-kill); ends with an explicit key-revoke reminder. No secret values appear
   (grep for the `sk-proj` prefix across the tree still returns nothing). `PROGRESS.md` now
   contains a `post-15: PIVOT` note (TUI removal → pure inline CLI + banner + `grendel config`)
   and a `phase 16: DONE …` entry, both appended before the trailing `ALL PHASES COMPLETE` line.

## What checks out (matches the plan)

- `_add_target` reuses `cfg.with_cli_target` (`config.py:167-178`), so duplicate name and unknown
  provider are both rejected **at add time**, not deferred to save
  (`test_add_target_helper_duplicate_and_unknown_provider`,
  `test_config_add_unknown_provider_errors_inline`).
- `_remove_target` raises `ConfigError` on an absent name and clears a dangling
  `cfg.judge.target` on removal (`test_remove_target_helper_clears_judge_reference`).
- Both the letter-menu (`_targets_letter`) and questionary (`_targets_questionary`) submenus catch
  `ConfigError` inline and loop back to the targets menu without crashing; `list` performs no
  mutation (`test_config_targets_list_no_mutation`).
- `inject_attack`'s `tool-output` surface emits a valid OpenAI pair: an `assistant` message with
  `tool_calls[0].id == "grendel-injected"` followed by a `role="tool"` message with the matching
  `tool_call_id` carrying `attack.payload` — verified by
  `test_inject_attack_tool_output_surface`; input body is not mutated (deep-copied).
- `ProxySession._persist()` writes atomically (`tmp` + `os.replace`) under `self._lock`, called
  after every successful attempt (`handle`) and every error attempt (`_append_error`); enabled via
  the public `enable_persistence(path)`; `test_handle_persists_record_incrementally` confirms a
  record with 1 attempt exists after a single `handle()` call.
- The LangGraph agent (`examples/langgraph-agent/agent.py`) is not imported anywhere in the test
  suite — `test_example_agent.py` only `ast.parse`s its source; its deps (`langgraph`,
  `langchain-openai`) live only in `examples/langgraph-agent/requirements.txt`, confirmed absent
  from `pyproject.toml`.
- No occurrence of the `sk-proj` key prefix anywhere in the tree.
- `scoring.py`, `runner.py`, `records.py`, `packloader.py` have materially older mtimes than the
  phase-16 touched files, consistent with "no scoring/records/runner/catalog behaviour change".
- `ruff check .` — all checks passed; `ruff format --check .` — 96 files already formatted;
  `pytest -q` — 488 passed, 1 skipped (independently re-verified in this final pass).
- Live validation (M3) and its documentation (test-report.md §6, PROGRESS.md phase-16 entry) are
  now present and consistent with the plan's Checkpoint 3 / spec §6/§9.5 requirements. No secrets
  on disk.

STATUS: PASS
