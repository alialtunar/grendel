# Phase 18 — Test report (add-target intent-based menu redesign)

## Commands run
1. `python -m ruff check src tests` — All checks passed!
2. `python -m ruff format --check src tests` — 103 files already formatted
3. `python -m pytest -q` — 553 passed, 1 skipped in 20.10s (offline; the 1 skip is the expected mcp-optional-dependency skip)

## Targeted verification

Ran the following named tests explicitly (all passed, 23 passed in 2.46s):
- `tests/test_cli_config.py::test_config_add_hosted_model_target`
- `tests/test_cli_config.py::test_config_add_chat_url_target`
- `tests/test_cli_config.py::test_config_add_running_app_points_to_proxy`
- `tests/test_cli_config.py::test_config_add_then_remove_target`
- `tests/test_cli_config.py::test_config_add_unknown_provider_errors_inline`
- `tests/test_cli_config.py::test_config_add_target_picks_provider_by_number`
- `tests/test_cli_config.py::test_config_add_target_shows_summary_then_confirms`
- `tests/test_cli_config.py::test_config_add_target_provider_list_annotated`
- `tests/test_cli_config.py::test_config_add_target_cancel_adds_nothing`
- `tests/test_cli_home.py` (13 tests, all passed)
- `tests/test_cli_walkthrough.py` (1 test, passed)

Also confirmed engine-level direct-call tests still cover python/agent providers even though the
interactive menu no longer surfaces them:
- `tests/test_cli_config.py::test_describe_target_python_is_in_process` — passed
- `tests/test_cli_config.py::test_add_target_helper_duplicate_and_unknown_provider` — passed

## Result

Lint clean, format clean, full suite fully green offline (553 passed / 1 expected skip). No failures,
no regressions. python/agent target types remain functional at the `_add_target`/`describe_target`
engine level; only removed from the interactive menu presentation as intended.

STATUS: PASS
