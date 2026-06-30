"""Offline discovery, loading, and validation of YAML attack packs."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .attacks import ALLOWED_LICENSES, Attack, Severity, Surface
from .errors import PackError


def default_packs_dir() -> Path:
    """The bundled packs directory shipped inside the package."""
    return Path(__file__).parent / "packs"


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
        attacks.append(attack)

    attacks.sort(key=lambda a: a.id)
    return attacks


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


def _check_license(path: Path, attack: Attack, *, allow_unlisted_licenses: bool) -> None:
    """License gating (spec §6)."""
    if attack.license not in ALLOWED_LICENSES and not allow_unlisted_licenses:
        raise PackError(
            f"attack {attack.id!r} in {path} has unlisted license {attack.license!r}; "
            f"allowed licenses: {', '.join(sorted(ALLOWED_LICENSES))} "
            f"(pass allow_unlisted_licenses=True to override)"
        )


def list_packs(
    packs_dir: Path | None = None,
    *,
    allow_unlisted_licenses: bool = False,
) -> list[PackInfo]:
    """Load packs and project each Attack to a lightweight PackInfo row."""
    if packs_dir is None:
        packs_dir = default_packs_dir()
    packs_dir = Path(packs_dir)

    attacks = load_packs(packs_dir, allow_unlisted_licenses=allow_unlisted_licenses)
    infos: list[PackInfo] = []
    for attack in attacks:
        path = packs_dir / attack.category / f"{attack.id.split('/', 1)[1]}.yaml"
        infos.append(
            PackInfo(
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
            )
        )
    return infos
