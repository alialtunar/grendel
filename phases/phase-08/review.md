# Phase 8 Review — MCP-aware attacks

Reviewed commit: `5d221f7` (feat(phase-08): MCP-aware attacks).
Suite result: **348 passed, 1 skipped** (expected). `ruff check .` and `ruff format --check .` both clean.

---

## Findings

1. **KEY PROPERTY — FAIL/T4 vs fake server, SKIPPED vs non-mcp target**: Confirmed correct.
   `test_pack_scores_fail_t4_against_fake_server` drives all 4 attacks against `MCPTargetAdapter(make_fake_client())` and asserts each returns `Verdict.FAIL` / `score_tier="T4"`, with `asr == 1.0`. `test_pack_skipped_against_plain_adapter` uses `FakeAdapter` (mcp=None, tool_calls=None) and asserts all 4 return `Verdict.SKIPPED`. Both tests pass.

2. **score_async branch position (critical)**: In `scoring.py`, the `if check.type == "side-effect"` branch is at lines 393–395 and the `if check.type == "mcp-assert"` branch is at lines 396–399, both placed **before** the `if not self._judge_enabled(): return base` guard at line 401. The `test_score_async_t4_fires_with_judge_disabled` test proves the branch fires with the judge off. Correct.

3. **Security — safe MCP evaluator**: `mcp_assert.py` uses only `re` and `dataclasses`. No `eval`/`exec`/`compile` anywhere. All four predicates are backed by anchored regexes (`^...$`). The `_BOOLTAIL` optional group only accepts `== true|false` or `!= true|false`; anything else falls through to `raise McpAssertSyntaxError`. The `test_module_uses_no_eval` test reads the source file and asserts no `eval(` or `exec(` string. The `test_safety_set_rejected` parametrize covers 11 malicious/malformed inputs. `_check_mcp_assertion` in the packloader parses every `mcp-assert` assertion at load time and raises `PackError` on failure, blocking injection at the data-load boundary.

4. **MCP surface model**: `AdapterResponse.mcp: McpObservation | None = None` is additive in `base.py` — all prior construction sites default to `None`. `MCPTargetAdapter.send()` takes `approved = snapshot_descriptions()` before `call_tool`, then `current = snapshot_descriptions()` after, and attaches `McpObservation(tools=..., approved_descriptions=approved, current_descriptions=current)`. The rug-pull diff is deterministic and order-independent.

5. **Rug-pull `[revN]` judgment call — sound**: Each `call_tool` increments `_rug_count` and appends `[revN]` to the mutated description. This ensures `approved != current` on every `send()` when the universal client is reused across the 4 sequential attack probes. Verified manually: `description_changed('search')` and `description_changed('mailer')` (non-rug-pull tools) correctly return `False` because only `send_email` is in the `rug_pull` dict. The `approved` snapshot is taken before `call_tool` (so it captures the pre-mutation description) and `current` after (post-mutation). No false positives for unrelated tools.

6. **Edge cases**:
   - `description_changed` on a vanished tool: `prior is not None and prior != current.get(a.arg0)` — `current.get(name)` returns `None` when the tool is absent, `None != prior`, so returns `True`. Test `test_description_changed_vanished_tool_true` confirms.
   - `description_changed` for never-approved tool: `prior = approved.get(name)` is `None`, guard fails, returns `False`. Test `test_description_changed_unknown_tool_false` confirms.
   - `tool_shadowed` absent-target: early `if not targets: return False` before scanning other tools. Test `test_tool_shadowed_absent_target_false` confirms.
   - `weak_mcp_agent` uses `tools.call(target, ...)` not `tools.<name>(...)`, so unregistered dynamic tool names (e.g. `exfiltrate`) record without `AttributeError`.

7. **Inertness — prior tests untouched**: 348 passed, 1 skipped. The 4 `test_bundled_packs.py` changes are all additive and enumerated in the plan: `test_loads_exactly_twenty_one` (was 17), `test_category_counts` adds `"mcp": 4`, `test_all_fields_well_formed` uses `a.category == "mcp"` branch accepting `{"mcp-assert", "side-effect"}`, `test_list_packs_twenty_one_rows_license_ok` (was 17). `import gauntlet` does not import `mcp` or any mcp-related module.

8. **`McpObservation` not persisted on `AttemptRecord`**: Confirmed — `records.py` has no `mcp` field. The observation is consumed only inside `score_async`, as the plan specified (Fix #12).

9. **Config seam (`McpConfig.fake_client`)**: The `GauntletConfig` model-validator accepts `command or url or fake_client` for an mcp target. `build_target` resolves and zero-arg-calls the factory to get an in-memory client. `resolve_target_info` returns `mcp.fake_client or name` as the model string (never empty). `test_fake_client_target_validates_and_builds_offline` confirms the full offline path.

10. **Pack coherence and license gate**: All 4 MCP YAMLs carry `license: Apache-2.0`, `category: mcp`, IDs matching path stems, and valid OWASP/Atlas references. `_check_mcp_assertion` is a separate function from `_check_side_effect_assertion` (Fix #7). The `test_malformed_mcp_assertion_raises_packerror` test confirms a crafted `os.system(...)` assertion raises `PackError`.

11. **Sync `score()` mcp-assert placeholder**: The explicit `if check.type == "mcp-assert"` branch in `score()` returns SKIPPED with a specific reason string (`"success_when type 'mcp-assert' requires async score_async"`), placed before the `side-effect`/`judge` catch-all. `test_sync_score_mcp_assert_is_skipped` asserts `"mcp-assert"` appears in the reason.

12. **M5 CLI/list polish**: `test_list_packs_includes_mcp_category` asserts `"mcp (4):"` and `"mcp/rug-pull-03"` appear in `gauntlet list --packs` output. Passes.

13. **No minor issues found**: No dead imports, no unused code, no `TODO`s, no network/key access in tests, Pydantic models all use `extra="forbid"`.

---

STATUS: PASS
