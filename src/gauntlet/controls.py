"""Benign control prompts: the BenignControl model + an offline loader.

Controls are legitimate requests the model *should* answer; scoring an over-refusal
as a utility miss lets us report utility-under-attack next to ASR (spec §7). They are a
separate data type from ``Attack`` (the attack schema is strict) and live in the reserved
``control/`` id namespace so the resume skip-set (keyed by attack_id) can never collide
with a real attack (Fix #7).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .attacks import ALLOWED_LICENSES
from .errors import PackError


def default_controls_dir() -> Path:
    """The bundled controls directory shipped inside the package."""
    return Path(__file__).parent / "packs" / "controls"


class BenignControl(BaseModel):
    """One benign control prompt (spec §7), gated like packs against the license allowlist."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^control/[a-z0-9-]+$")
    name: str
    category: str = "control"
    prompt: str
    license: str

    @field_validator("prompt", "name")
    @classmethod
    def _non_empty_after_strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty after stripping whitespace")
        return v

    @field_validator("category")
    @classmethod
    def _category_is_control(cls, v: str) -> str:
        if v != "control":
            raise ValueError("benign control category must be 'control'")
        return v


def load_controls(
    controls_dir: Path | None = None,
    *,
    allow_unlisted_licenses: bool = False,
) -> list[BenignControl]:
    """Discover, validate, and return every bundled control, sorted by id.

    Every failure (missing dir, malformed/empty/multi-doc YAML, schema validation,
    id/path mismatch, license gating, duplicate id) raises PackError naming the file.
    """
    if controls_dir is None:
        controls_dir = default_controls_dir()
    controls_dir = Path(controls_dir)
    if not controls_dir.is_dir():
        raise PackError(f"controls directory not found or not a directory: {controls_dir}")

    controls: list[BenignControl] = []
    seen: dict[str, Path] = {}

    for path in sorted(controls_dir.glob("*.yaml")):
        control = _parse_and_validate(path)
        if control.id in seen:
            raise PackError(f"duplicate control id {control.id!r} in {path} and {seen[control.id]}")
        seen[control.id] = path
        _check_coherence(path, control)
        _check_license(path, control, allow_unlisted_licenses=allow_unlisted_licenses)
        controls.append(control)

    controls.sort(key=lambda c: c.id)
    return controls


def _parse_and_validate(path: Path) -> BenignControl:
    content = path.read_text(encoding="utf-8")
    try:
        docs = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        raise PackError(f"invalid YAML in {path}: {exc}") from exc

    if len(docs) != 1:
        raise PackError(f"expected exactly one YAML document in {path}, got {len(docs)}")
    data = docs[0]
    if not isinstance(data, dict):
        raise PackError(f"control root must be a mapping in {path}, got {type(data).__name__}")

    try:
        return BenignControl.model_validate(data)
    except ValidationError as exc:
        raise PackError(f"invalid control in {path}: {exc}") from exc


def _check_coherence(path: Path, control: BenignControl) -> None:
    """id must be ``control/<filename stem>`` (Fix #7 — reserved namespace)."""
    expected_id = f"control/{path.stem}"
    if control.id != expected_id:
        raise PackError(
            f"id {control.id!r} does not match expected {expected_id!r} from path {path}"
        )


def _check_license(path: Path, control: BenignControl, *, allow_unlisted_licenses: bool) -> None:
    if control.license not in ALLOWED_LICENSES and not allow_unlisted_licenses:
        raise PackError(
            f"control {control.id!r} in {path} has unlisted license {control.license!r}; "
            f"allowed licenses: {', '.join(sorted(ALLOWED_LICENSES))} "
            f"(pass allow_unlisted_licenses=True to override)"
        )
