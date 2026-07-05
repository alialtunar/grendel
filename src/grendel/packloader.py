"""Offline discovery, loading, and validation of YAML attack packs."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .attacks import ALLOWED_LICENSES, Attack, Severity, Surface
from .errors import PackError

if TYPE_CHECKING:
    from .config import GrendelConfig


def default_packs_dir() -> Path:
    """The bundled packs directory shipped inside the package."""
    return Path(__file__).parent / "packs"


class Source(str, Enum):
    """Where a catalog entry came from (Phase 9)."""

    BUNDLED = "bundled"  # shipped in src/grendel/packs (Vendored tier)
    USER = "user"  # a config-listed user pack directory (Plugin/local tier)
    FEED = "feed"  # pulled by `grendel update` into the feed cache (Feed tier)
    STAGED = "staged"  # awaiting human approval — listed, NOT armed (optional §9)


# Cross-source precedence rank (higher wins under allow_override). user > feed > bundled;
# staged never overrides an armed source (§5.2 + Fix #7 same-rank tie).
_SOURCE_RANK: dict[Source, int] = {
    Source.STAGED: 0,
    Source.BUNDLED: 1,
    Source.FEED: 2,
    Source.USER: 3,
}


class PackInfo(BaseModel):
    """Lightweight discovery row projected from an Attack."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str
    owasp: str
    atlas: str
    surface: Surface
    severity: Severity
    license: str
    license_ok: bool
    success_type: str
    path: Path
    source: Source = Source.BUNDLED


class CatalogEntry(BaseModel):
    """One attack plus the source it came from (the unit `load_catalog` returns)."""

    model_config = ConfigDict(extra="forbid")

    attack: Attack
    source: Source
    path: Path
    armed: bool = True  # False only for STAGED (excluded from run selection)


def load_packs(
    packs_dir: Path | None = None,
    *,
    allow_unlisted_licenses: bool = False,
) -> list[Attack]:
    """Discover, validate, and return every bundled attack, sorted by id.

    Every failure (missing dir, malformed/empty/multi-doc YAML, schema validation,
    path/id mismatch, license gating, duplicate id) raises PackError naming the file.
    """
    if packs_dir is None:
        packs_dir = default_packs_dir()
    packs_dir = Path(packs_dir)
    if not packs_dir.is_dir():
        raise PackError(f"packs directory not found or not a directory: {packs_dir}")

    attacks: list[Attack] = []
    seen: dict[str, Path] = {}

    for path in sorted(packs_dir.glob("*/*.yaml")):
        # The reserved controls/ subtree holds BenignControls, not Attacks (Phase 6).
        if path.parent.name == "controls":
            continue
        attack = _parse_and_validate(path)
        # Cross-file dedup before coherence so a forged duplicate id is reported as
        # such (spec §7 rule 5, naming both paths).
        if attack.id in seen:
            raise PackError(f"duplicate attack id {attack.id!r} in {path} and {seen[attack.id]}")
        seen[attack.id] = path
        _check_coherence(path, attack)
        _check_license(path, attack, allow_unlisted_licenses=allow_unlisted_licenses)
        _check_side_effect_assertion(path, attack)
        _check_mcp_assertion(path, attack)
        attacks.append(attack)

    # Bundled compiled corpus: hundreds of permissively-licensed corpus attacks shipped as ONE
    # JSONL (one Attack per line) rather than one file each — a per-file dir adds seconds to every
    # startup (each pack is read+parsed+validated). Absent in a custom packs_dir → skipped.
    compiled = packs_dir / "_corpora.jsonl"
    if compiled.is_file():
        for attack in _load_compiled(compiled):
            if attack.id in seen:
                raise PackError(
                    f"duplicate attack id {attack.id!r} in {compiled} and {seen[attack.id]}"
                )
            seen[attack.id] = compiled
            _check_license(compiled, attack, allow_unlisted_licenses=allow_unlisted_licenses)
            _check_side_effect_assertion(compiled, attack)
            _check_mcp_assertion(compiled, attack)
            attacks.append(attack)

    attacks.sort(key=lambda a: a.id)
    return attacks


def _load_compiled(path: Path) -> list[Attack]:
    """Load the bundled compiled corpus (one JSON Attack per line); blank lines skipped."""
    out: list[Attack] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(Attack.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise PackError(f"invalid compiled attack at {path}:{i}: {exc}") from exc
    return out


def _parse_and_validate(path: Path) -> Attack:
    content = path.read_text(encoding="utf-8")
    try:
        # Materialize the lazy generator so len() works (review fix #10).
        docs = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        raise PackError(f"invalid YAML in {path}: {exc}") from exc

    if len(docs) != 1:
        raise PackError(f"expected exactly one YAML document in {path}, got {len(docs)}")
    data = docs[0]
    if not isinstance(data, dict):
        raise PackError(f"attack root must be a mapping in {path}, got {type(data).__name__}")

    try:
        return Attack.model_validate(data)
    except PackError:
        raise
    except ValidationError as exc:
        raise PackError(f"invalid attack in {path}: {exc}") from exc


def _check_coherence(path: Path, attack: Attack) -> None:
    """Path/id coherence (spec §7 rule 3)."""
    if attack.category == "control":
        raise PackError(
            f"attack {attack.id!r} in {path} uses reserved category 'control' "
            f"(reserved for benign controls; Fix #7)"
        )
    parent = path.parent.name
    if attack.category != parent:
        raise PackError(
            f"category {attack.category!r} does not match parent directory {parent!r} in {path}"
        )
    expected_id = f"{attack.category}/{path.stem}"
    if attack.id != expected_id:
        raise PackError(
            f"id {attack.id!r} does not match expected {expected_id!r} from path {path}"
        )


def _check_side_effect_assertion(path: Path, attack: Attack) -> None:
    """Fix #8: fail fast on a malformed side-effect assertion (PackError naming the file).

    Non-breaking for string/classifier/judge packs (they carry no ``assert_``).
    """
    check = attack.success_when
    if getattr(check, "type", None) != "side-effect":
        return
    from .sideeffect import AssertionSyntaxError, parse_assertion

    try:
        parse_assertion(check.assert_)
    except AssertionSyntaxError as exc:
        raise PackError(
            f"attack {attack.id!r} in {path} has a malformed side-effect assertion: {exc}"
        ) from exc


def _check_mcp_assertion(path: Path, attack: Attack) -> None:
    """Fix #7: fail fast on a malformed mcp-assert assertion (PackError naming the file).

    A SEPARATE function (not overloading the side-effect check) since it parses the
    mcp-assert grammar. Non-breaking for non-mcp packs (no ``mcp-assert`` success_when).
    """
    check = attack.success_when
    if getattr(check, "type", None) != "mcp-assert":
        return
    from .mcp_assert import McpAssertSyntaxError, parse_mcp_assertion

    try:
        parse_mcp_assertion(check.assert_)
    except McpAssertSyntaxError as exc:
        raise PackError(
            f"attack {attack.id!r} in {path} has a malformed mcp assertion: {exc}"
        ) from exc


def _check_license(path: Path, attack: Attack, *, allow_unlisted_licenses: bool) -> None:
    """License gating (spec §6)."""
    if attack.license not in ALLOWED_LICENSES and not allow_unlisted_licenses:
        raise PackError(
            f"attack {attack.id!r} in {path} has unlisted license {attack.license!r}; "
            f"allowed licenses: {', '.join(sorted(ALLOWED_LICENSES))} "
            f"(pass allow_unlisted_licenses=True to override)"
        )


def _pack_path(packs_dir: Path, attack: Attack) -> Path:
    """Recompute the on-disk path of an attack within a (coherent) source dir."""
    return packs_dir / attack.category / f"{attack.id.split('/', 1)[1]}.yaml"


def load_catalog(
    config: GrendelConfig,
    *,
    allow_unlisted_licenses: bool = False,
) -> list[CatalogEntry]:
    """Merge bundled + user dirs + feed cache + staged into one source-tagged catalog.

    Every source is loaded via the existing ``load_packs`` primitive, so each gets the
    same license-gate / coherence / assert-parse validation. An absent configured dir
    contributes zero (no error); a malformed one raises PackError. Cross-source duplicate
    ids are a PackError by default, or a deterministic precedence win (user > feed >
    bundled) when ``config.catalog.allow_override`` is set — equal source ranks never
    resolve (Fix #7). Returns entries sorted by ``attack.id``.
    """
    allow = allow_unlisted_licenses or config.catalog.allow_unlisted_licenses
    cat = config.catalog

    # (source, dir, armed), loaded in fixed precedence order (spec §5.1).
    plan: list[tuple[Source, Path, bool]] = [(Source.BUNDLED, default_packs_dir(), True)]
    plan += [(Source.USER, Path(d), True) for d in cat.pack_dirs]
    # Feed cache: the configured dir, else grendel's default cache dir (so a zero-config
    # `grendel update` is read back here). An absent dir contributes zero (the .is_dir() gate
    # below), so "empty config == bundled-only" still holds until the user actually pulls.
    from .config import DEFAULT_FEED_CACHE_DIR

    feed_cache = cat.feed_cache_dir if cat.feed_cache_dir is not None else DEFAULT_FEED_CACHE_DIR
    plan.append((Source.FEED, Path(feed_cache), True))
    if cat.staged_dir is not None:
        plan.append((Source.STAGED, Path(cat.staged_dir), False))

    chosen: dict[str, CatalogEntry] = {}
    for source, packs_dir, armed in plan:
        # Bundled always exists; an absent user/feed/staged dir simply contributes zero.
        if source is not Source.BUNDLED and not packs_dir.is_dir():
            continue
        for attack in load_packs(packs_dir, allow_unlisted_licenses=allow):
            entry = CatalogEntry(
                attack=attack,
                source=source,
                path=_pack_path(packs_dir, attack),
                armed=armed,
            )
            existing = chosen.get(attack.id)
            if existing is None:
                chosen[attack.id] = entry
                continue
            _resolve_duplicate(config, existing, entry)
            if _SOURCE_RANK[entry.source] > _SOURCE_RANK[existing.source]:
                chosen[attack.id] = entry

    return sorted(chosen.values(), key=lambda e: e.attack.id)


def _resolve_duplicate(config: GrendelConfig, existing: CatalogEntry, entry: CatalogEntry) -> None:
    """Apply the §5.2 cross-source dedup rule; raise PackError when there is no winner."""
    if not config.catalog.allow_override:
        raise PackError(
            f"duplicate attack id {entry.attack.id!r} across sources: "
            f"{existing.path} [{existing.source.value}] and {entry.path} [{entry.source.value}]"
        )
    if _SOURCE_RANK[entry.source] == _SOURCE_RANK[existing.source]:
        # Fix #7: override only resolves DIFFERENT ranks; equal ranks have no winner.
        raise PackError(
            f"duplicate attack id {entry.attack.id!r} in same-rank sources "
            f"{existing.path} [{existing.source.value}] and {entry.path} "
            f"[{entry.source.value}]; allow_override cannot pick a winner"
        )


def _project(attack: Attack, path: Path, source: Source) -> PackInfo:
    return PackInfo(
        id=attack.id,
        name=attack.name,
        category=attack.category,
        owasp=attack.owasp,
        atlas=attack.atlas,
        surface=attack.surface,
        severity=attack.severity,
        license=attack.license,
        license_ok=attack.license in ALLOWED_LICENSES,
        success_type=attack.success_when.type,
        path=path,
        source=source,
    )


def list_packs(
    packs_dir: Path | None = None,
    *,
    config: GrendelConfig | None = None,
    allow_unlisted_licenses: bool = False,
) -> list[PackInfo]:
    """Project attacks to lightweight PackInfo rows.

    With ``config`` given, project the merged multi-source catalog (each row tagged with
    its source); otherwise load a single dir (default bundled, ``source=BUNDLED``).
    """
    if config is not None:
        entries = load_catalog(config, allow_unlisted_licenses=allow_unlisted_licenses)
        return [_project(e.attack, e.path, e.source) for e in entries]

    if packs_dir is None:
        packs_dir = default_packs_dir()
    packs_dir = Path(packs_dir)
    attacks = load_packs(packs_dir, allow_unlisted_licenses=allow_unlisted_licenses)
    return [_project(a, _pack_path(packs_dir, a), Source.BUNDLED) for a in attacks]
