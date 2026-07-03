# Phase 26 — implementation plan

Derived from `phases/phase-26/spec.md`. One milestone, ending in a checkpoint (ruff clean + pytest
green + reviewer/tester STATUS: PASS).

---

## Milestone 1 — first-run welcome

**Steps**
1. **`banner.py` — `render_welcome(*, color=False, unicode=True) -> str`:** a compact orientation block:
   - a 🐺/`>` title line "New here? Grendel red-teams your AI — it fires authorized attack packs at a
     target and shows which got through.";
   - `Get started:` then three numbered lines mapping to the menu keys `[t]` add a target (hosted model
     + key, or your agent's URL) · `[x]` fire attacks · results (live dashboard + browse which got
     through);
   - a dim "New? [o] doctor — health check & next steps." Uses `_c(...)` for optional color and an
     ASCII/unicode split like `config_header`/`render_banner` (no em-dash/glyph that cp1254 can't take;
     rely on the existing `install_console_fallback` too). Pure string; no I/O.
2. **`cli.py` — show it in the home menu when empty:** in `_home_letter` AND `_home_questionary`,
   right after `_clear_and_logo` + `config_header`, if `not cfg.targets` print `render_welcome(
   color=<tty>, unicode=unicode)` (a blank line after). Gated ONLY on `not cfg.targets` so it vanishes
   once a target exists; both shells call the same helper. (questionary shell: `typer.echo` the block
   before the `questionary.select`, same as it already echoes the logo.)
3. **`banner.py` — banner quickstart parity (non-TTY):** the landing banner's "New here?" section
   already exists; align its wording with the 3-step framing (add-target → run → results) so the
   piped/`--no-menu`/CI banner teaches the same path. Keep the COMMANDS table + authorized-use notice
   (a test asserts the command set stays in sync — don't touch the command list).
4. **Tests** (`tests/test_cli_home.py` + `tests/test_banner*.py` if present, else `test_cli_home.py`):
   - `render_welcome` (unit): contains "Get started", the `[t]`/`[x]`/`[o]` keys, and (ascii variant)
     leaks none of `🐺 … · —`.
   - `test_home_menu_welcome_shown_when_no_targets`: bare menu (GRENDEL_FORCE_MENU, empty config) →
     output contains the welcome ("Get started"); `test_home_menu_welcome_hidden_with_a_target`: a
     grendel.yaml with a configured target (discovered via GRENDEL_NO_AUTOCONFIG delenv) → the welcome
     is ABSENT (only the normal menu). Existing menu tests still pass (welcome is additive echo lines;
     they assert substrings / the "no changes saved" quit line, which are unaffected — verify the
     banner-vs-menu gate tests and the run/target tests, most of which use an empty config and will now
     also print the welcome, but none assert the ABSENCE of these lines).

**Checkpoint 1 (phase close):** full suite green + ruff clean; reviewer + tester STATUS: PASS; append
`phase 26: DONE …` to PROGRESS.md.

---

## Plan review — addressed
- (1) welcome prints right after `_clear_and_logo`, BEFORE `config_header` in BOTH shells → identical
  order (logo → welcome → header/options). In `_home_questionary` config_header is the select's title,
  so the welcome is `typer.echo`'d before the `questionary.select` call.
- (2,5,6) DROP the banner change entirely — the banner already has "New here? · grendel doctor" + a
  quickstart run example (test_first_run_walkthrough relies on those literals). The welcome is
  MENU-only; no banner/COMMANDS/cp1254-banner-test risk. (Spec's banner-parity is already satisfied.)
- (3) `color=sys.stdout.isatty()` (explicit, matches `_clear_and_logo`), unicode from the caller's
  `unicode` flag.
- (7) the welcome uses menu ITEM NAMES (targets / run / doctor) — accurate in BOTH the letter shell
  (`[t] targets`) and questionary (`targets · …`); NO bracket-key hints (no `[o]` that questionary
  can't honour).
- (4) Checkpoint names the three high-risk files explicitly.

## Risks & mitigations
- **Existing empty-config menu tests** now also render the welcome → additive `typer.echo` lines; they
  assert substrings (e.g. attack ids, "saved ->", "no changes saved"), not exact full output, so they
  stay green. Explicitly re-run the whole `test_cli_home.py` + `test_cli_walkthrough.py`.
- **cp1254** → `render_welcome` has a unicode/ascii split (no em-dash/`·`/🐺 in the ascii branch) AND
  the output boundary already degrades via `install_console_fallback`; the ascii unit test asserts no
  fancy glyph.
- **Noise for existing users** → gated on `not cfg.targets`, so anyone who configured a target never
  sees it; it's purely a newcomer aid.
- **Banner test coupling** → only the "New here?" wording changes; the drift-guarded COMMANDS list and
  the notice are untouched.
