# Review -- intent-based add-target flow (uncommitted, post-Phase-18)

Scope: `src/grendel/cli.py` (`_targets_letter`, `_targets_questionary`, `_echo_proxy_hint`,
`_make_target_config`, `_add_target`, `describe_target`) and the corresponding tests
(`tests/test_cli_config.py`, `tests/test_cli_home.py`, `tests/test_cli_walkthrough.py`). The
add-target UX was redesigned from a raw type picker (http/python/agent) to an intent picker
("what are you testing?" -> hosted model / own OpenAI-compatible chat URL / running app-via-proxy).
`src/grendel` is entirely untracked (no prior commit to diff against), so this review is based on
reading the current state of the code plus the task's description of what changed, and running the
full suite + ruff.

## Findings

1. **Option 1 (hosted model) -- OK, minimal and fast.** `_targets_letter`/`_targets_questionary`
   prompt only `provider` (annotated, numbered, default `openai`) + `model` (default
   `gpt-4o-mini`) + optional `api_key_env` -- no `base_url` prompt (`cli.py:1223-1234`,
   `1378-1401`). Builds `type="http"` via `_make_target_config`. `test_config_add_hosted_model_target`
   confirms `provider == "openai"`, `model == "gpt-4o-mini"` with an all-default script.
2. **Option 2 (chat URL) -- OK, produces a correct openai-compatible target.** Hardcodes
   `provider="openai-compatible"`, prompts `base_url` + `model` + `api_key_env`
   (`cli.py:1236-1246`, `1402-1422`). `describe_target` resolves through the same
   `resolve_target_info`/`PRESETS` path the runner uses (`cli.py:1109-1128`), so the confirmation
   line `POST <base_url>/chat/completions` cannot drift from real request building -- verified
   against `http_adapter.py:89` (`f"{self.base_url}/chat/completions"`) which uses the identical
   suffix table (`_API_PATHS` at `cli.py:1098` mirrors `_ENDPOINT` in `proxy.py:41`).
   `test_config_add_chat_url_target` asserts `provider == "openai-compatible"`,
   `base_url == "http://localhost:1234/v1"`, and the printed
   `POST http://localhost:1234/v1/chat/completions`. Anthropic (`/messages`) and Ollama
   (`/api/chat`) branches are also pinned by
   `test_describe_target_openai_compatible_uses_base_url_and_ollama_path`.
3. **Option 3 (running app / no API) -- adds no target, correct in substance.**
   `_echo_proxy_hint()` prints the right subcommand and flags -- `grendel proxy --serve --route
   /openai=openai --pack tool-abuse` matches the real `proxy` command's option names
   (`cli.py:805-829`). Both shells `continue` without calling `_add_target_tc`, and
   `test_config_add_running_app_points_to_proxy` confirms nothing is added to `cfg.targets`.

4. **Minor / non-blocking: the proxy-hint URL includes a `/v1` suffix the live `--serve` banner
   never prints.** `_echo_proxy_hint` says `http://127.0.0.1:8100/openai/v1` (`cli.py:1200`), but
   `proxy.py`'s `startup_banner` (the text actually shown when the proxy is running) prints
   `http://{host}:{port}{prefix}` with **no** `/v1` -- i.e. `http://127.0.0.1:8100/openai`
   (`proxy.py:326-333`). Not functionally broken: routing is prefix-based
   (`path.startswith(prefix)` in `proxy.py:50`) and the upstream URL is built from the provider's
   `api_style` suffix table, not the incoming client path, so an agent configured with the extra
   `/v1` still routes correctly. But it is a wording inconsistency between the two places a user
   sees the proxy URL -- worth aligning in a follow-up so the confirmation text and the live
   banner say the same thing verbatim. Not blocking.
5. **Menu-level python/agent removal is clean; the underlying capability is untouched.**
   `_make_target_config`/`_add_target`/`describe_target` still branch on `kind in ("python",
   "agent")` (`cli.py:1065`, `1110`) and are exercised directly by
   `test_describe_target_python_is_in_process` /
   `test_add_target_helper_duplicate_and_unknown_provider` in `test_cli_config.py`. Grepping
   `cli.py` shows no `Choice("python"...)` / `Choice("agent"...)` in either interactive shell --
   the type is only reachable via the `_make_target_config`/`_add_target` Python API (used by
   `run --python`/`run --agent`, whose Typer options at `cli.py:331,334` are unmodified) --
   matches the stated intent ("no need for advanced" in the menu, capability preserved for the
   CLI).
6. **Provider list in the hosted-model flow (option 1) still includes `openai-compatible`.**
   `_prompt_provider_letter`/the questionary provider select both use `_known_providers(cfg)` (all
   presets + custom), so a user in the "hosted model" flow *can* pick `openai-compatible` --
   which needs `base_url` and none is prompted in that flow. This isn't a crash:
   `_make_target_config` builds the `TargetConfig` with `base_url=None`, and `describe_target`'s
   call into `resolve_target_info` raises `ConfigError` for the missing `base_url`, caught at
   `cli.py:1251`/`1424-1426` and shown inline ("error: ..."), returning to the prompt -- the
   session survives (same pattern already covered by
   `test_config_add_unknown_provider_errors_inline`). The provider annotation
   (`"openai-compatible (openai; needs base_url)"`, asserted by
   `test_config_add_target_provider_list_annotated`) does warn the user before they pick it. Not
   blocking, but a newcomer following option 1 verbatim and typing `openai-compatible` will hit an
   avoidable error instead of being routed to option 2's flow -- a candidate follow-up (filter
   `openai-compatible` out of the option-1 provider list, or special-case-redirect to option 2).

7. **Confirmation + cancel + ConfigError-to-prompt behavior unchanged and correctly wired for the
   new flow.** Both shells still print `describe_target`'s summary, ask to confirm, and only call
   `_add_target_tc` on yes (`cli.py:1254-1262`, `1423-1435`); cancel is a no-op
   (`test_config_add_target_cancel_adds_nothing`); an invalid target's `ConfigError` from either
   `_make_target_config`/`describe_target` is caught and the loop continues
   (`test_config_add_unknown_provider_errors_inline`).

8. **No engine/scoring/exit-code changes.** All edits inspected are confined to the interactive
   target-add helpers/menus in `cli.py` and their tests; `runner.py`, `scoring.py`, `records.py`,
   `reports.py`, `proxy.py` (read only, for cross-checks) show no task-relevant edits, and no test
   outside `test_cli_config.py`/`test_cli_home.py`/`test_cli_walkthrough.py` needed updating for
   this change.

9. **Verification run -- confirmed.** `python -m ruff check src/grendel tests` printed "All checks
   passed!". `python -m pytest -q` printed `553 passed, 1 skipped in 20.18s`, matching the reported
   numbers exactly.

10. **Newcomer usability judgment.** The three-way intent split (a hosted model / my own endpoint
    with an OpenAI-compatible chat URL / a running app that calls an LLM, no API, via proxy) maps
    directly onto the three real-world starting points a first-time user has, each with the
    minimum fields needed to move fast (hosted: 2 required fields; chat URL: 3; running app: 0
    fields, straight to the copy-pasteable proxy command). The pre-add confirmation
    (`describe_target`) closes the loop by showing the literal resolved request before anything is
    saved. A newcomer can pick correctly and start testing without reading docs, modulo finding #6
    above (an edge case only hit by actively choosing the one provider that needs a field the flow
    doesn't collect).

## Verdict
No blocking issues. Options 1-3 behave as specified, `describe_target` reuses the real resolution
path (no drift), cancel/error handling is preserved, python/agent capability is intact outside the
menu, and the full suite + ruff are green as claimed. Findings #4 and #6 are non-blocking polish
items worth a quick follow-up: align the proxy-hint URL with the live `startup_banner` text, and
consider excluding `openai-compatible` from the option-1 provider list.

STATUS: PASS
