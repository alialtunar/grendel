"""Open-corpus import: convert public red-team corpora into validated Attack YAML packs.

`grendel import --source garak --path <corpus> --out <catalog-dir>` reads a corpus from a LOCAL
path, converts each prompt to a schema-valid ``Attack`` (via the real model), license-gates,
de-duplicates by normalized payload (against the out dir AND within the run, so the import is
incremental/re-runnable), and writes path-safe ``<out>/<category>/<id>.yaml`` — packs the existing
``packloader`` loads and ``--pack-dir`` consumes. Offline: the source reads a local path; no
network, no requirement that ``garak`` be installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .attacks import ALLOWED_LICENSES, Attack
from .errors import PackError

_GARAK_REF = "https://github.com/NVIDIA/garak"


@dataclass(frozen=True)
class RawEntry:
    """One normalized prompt pulled from a corpus, before conversion to an Attack."""

    text: str
    category: str  # "jailbreak" | "dan" (a valid Attack.category pattern)
    source_name: str
    license: str


class ImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seen: int = 0
    imported: int = 0
    duplicate: int = 0
    license_skipped: int = 0
    written: list[str] = []


# --- normalization + id helpers ---------------------------------------------------------------
def _norm(payload: str) -> str:
    """Normalize for dedup: strip, collapse internal whitespace, casefold."""
    return re.sub(r"\s+", " ", payload).strip().casefold()


def _norm_hash(payload: str) -> str:
    return hashlib.sha256(_norm(payload).encode("utf-8")).hexdigest()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "import"


def _category_for(stem: str) -> str:
    s = stem.lower()
    if s.startswith("dan"):
        return "dan"
    if "harmbench" in s:
        return "harmbench"
    if s.startswith("rtp") or "toxic" in s:
        return "toxicity"
    return "jailbreak"


# --- source connectors ------------------------------------------------------------------------
class GarakSource:
    """Reads garak's Apache-2.0 prompt corpora (.txt paragraphs / .json lists) from a local path."""

    license = "Apache-2.0"

    def read(self, path: Path) -> Iterator[RawEntry]:
        path = Path(path)
        files = [path] if path.is_file() else sorted(path.rglob("*"))
        for f in files:
            if f.suffix.lower() == ".txt":
                yield from self._read_txt(f)
            elif f.suffix.lower() == ".json":
                yield from self._read_json(f)

    def _entry(self, text: str, stem: str) -> RawEntry:
        return RawEntry(
            text=text.strip(),
            category=_category_for(stem),
            source_name=stem,
            license=self.license,
        )

    def _read_txt(self, f: Path) -> Iterator[RawEntry]:
        text = f.read_text(encoding="utf-8")
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        # If the file has no blank-line paragraph structure (a single chunk), it is a
        # one-prompt-per-line list (harmbench/tap/rtp) — split on newlines instead.
        chunks = paras if len(paras) > 1 else [ln for ln in text.splitlines() if ln.strip()]
        for chunk in chunks:
            yield self._entry(chunk, f.stem)

    def _read_json(self, f: Path) -> Iterator[RawEntry]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise PackError(f"invalid JSON corpus {f}: {exc}") from exc
        if not isinstance(data, list):
            raise PackError(f"corpus {f} must be a JSON list of prompts")
        for item in data:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                text = item.get("prompt") or item.get("text") or ""
            else:
                text = ""
            if isinstance(text, str) and text.strip():
                yield self._entry(text, f.stem)


SOURCES: dict[str, GarakSource] = {"garak": GarakSource()}


def get_source(name: str) -> GarakSource:
    src = SOURCES.get(name)
    if src is None:
        raise PackError(f"unknown source {name!r}; known sources: {', '.join(sorted(SOURCES))}")
    return src


# The garak corpora auto-imported when `--path` is omitted — the jailbreak/DAN sets plus the
# harmful-behavior (harmbench), automated-jailbreak (tap/autodan), and toxicity (realtoxicity)
# sets. Relative to garak's installed data dir; missing entries are skipped.
GARAK_CURATED: tuple[str, ...] = (
    "inthewild_jailbreak_llms.json",  # ~666 in-the-wild jailbreaks
    "dan",  # DAN prompt family
    "harmbench/harmbench_prompts.txt",  # ~200 harmful-behavior requests
    "tap/tap_jailbreaks.txt",  # automated jailbreaks
    "autodan",  # adversarial-suffix seeds
    "realtoxicityprompts",  # ~700 toxicity-eliciting prompts
)


def garak_data_dir() -> Path:
    """The installed garak package's ``data`` directory (raises PackError if garak is absent)."""
    try:
        import garak
    except ImportError as exc:
        raise PackError(
            "garak is not installed — run `pip install garak`, or pass --path to a corpus"
        ) from exc
    return Path(garak.__file__).resolve().parent / "data"


def default_source_paths(source_name: str) -> list[Path]:
    """Local paths a source auto-imports when no ``--path`` is given (garak: the curated set)."""
    if source_name != "garak":
        raise PackError(f"--path is required for source {source_name!r} (no auto-discovery)")
    data = garak_data_dir()
    paths = [data / name for name in GARAK_CURATED if (data / name).exists()]
    if not paths:
        raise PackError(f"no garak corpora found under {data}; pass --path explicitly")
    return paths


# --- conversion -------------------------------------------------------------------------------
def to_attack(entry: RawEntry, *, seq: int) -> Attack:
    """Convert a RawEntry to a validated Attack; wrap schema errors as PackError."""
    h = _norm_hash(entry.text)[:8]
    attack_id = f"{entry.category}/{_slugify(entry.source_name)}-{h}"
    try:
        return Attack(
            id=attack_id,
            name=f"garak {entry.category} import {h}",
            category=entry.category,
            owasp="LLM01",
            atlas="AML.T0054",
            surface="prompt",
            severity="medium",
            license=entry.license,
            version=1,
            payload=entry.text,
            success_when={
                "type": "classifier",
                "classifier": "lexical",
                "label": "attack_succeeded",
                "threshold": 0.5,
            },
            references=[_GARAK_REF],
        )
    except ValidationError as exc:
        raise PackError(f"invalid converted attack from {entry.source_name!r}: {exc}") from exc


def _attack_yaml(attack: Attack) -> str:
    # mode="json" so Surface/Severity enums become plain scalars (yaml.safe_dump can't
    # represent the str-Enum subclasses otherwise).
    return yaml.safe_dump(attack.model_dump(by_alias=True, mode="json"), sort_keys=False)


def _atomic_write(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, dest)


def _payload_hashes(out_dir: Path) -> set[str]:
    """Normalized-payload hashes of packs already in ``out_dir`` (unparseable files ignored)."""
    hashes: set[str] = set()
    if not out_dir.is_dir():
        return hashes
    for f in out_dir.glob("*/*.yaml"):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            payload = doc.get("payload") if isinstance(doc, dict) else None
        except (ValueError, yaml.YAMLError, OSError):
            continue
        if isinstance(payload, str) and payload.strip():
            hashes.add(_norm_hash(payload))
    return hashes


# --- the pipeline -----------------------------------------------------------------------------
def import_entries(
    entries: Iterable[RawEntry],
    out_dir: Path,
    *,
    limit: int | None = None,
    allow_unlisted_licenses: bool = False,
    dry_run: bool = False,
) -> ImportResult:
    """Convert + license-gate + dedup + write a stream of RawEntry into ``out_dir``.

    Dedup runs BEFORE the license gate (cheaper; a duplicate-and-bad-license entry counts as a
    duplicate). ``--limit`` stops the whole run after N new packs are written. A conversion error
    raises PackError after any earlier atomic writes (a re-run converges — the writes are per-file).
    """
    out_dir = Path(out_dir)
    existing = _payload_hashes(out_dir)
    seen_hashes: set[str] = set()
    result = ImportResult()

    for entry in entries:
        result.seen += 1
        h = _norm_hash(entry.text)
        if h in existing or h in seen_hashes:
            result.duplicate += 1
            continue
        if entry.license not in ALLOWED_LICENSES and not allow_unlisted_licenses:
            result.license_skipped += 1
            continue
        attack = to_attack(entry, seq=result.imported)
        seen_hashes.add(h)
        stem = attack.id.split("/", 1)[1]
        rel = f"{attack.category}/{stem}.yaml"
        if not dry_run:
            _atomic_write(out_dir / attack.category / f"{stem}.yaml", _attack_yaml(attack))
        result.imported += 1
        result.written.append(rel)
        if limit is not None and result.imported == limit:
            break
    return result


def import_corpus(
    source_name: str,
    src_path: Path,
    out_dir: Path,
    *,
    limit: int | None = None,
    allow_unlisted_licenses: bool = False,
    dry_run: bool = False,
) -> ImportResult:
    """Resolve a named source, read the corpus at ``src_path``, and import it into ``out_dir``."""
    source = get_source(source_name)
    return import_entries(
        source.read(src_path),
        out_dir,
        limit=limit,
        allow_unlisted_licenses=allow_unlisted_licenses,
        dry_run=dry_run,
    )
