"""Remote feed: manifest schema + the offline-injectable `update_feeds` pipeline (Phase 9).

A feed is a single manifest document (JSON or YAML) listing packs with pinned versions +
SHA-256 checksums + licenses. `update_feeds` fetches the manifest over an injectable
``httpx.AsyncClient`` (a ``MockTransport`` in tests), license-gates each pack BEFORE
download, size-caps + checksum-verifies the bytes, validates the content as an ``Attack``
that coheres with the manifest claim, and writes verified packs atomically into the feed
cache. Per-entry problems are collected into the result (never raised); manifest-level
failures are per-feed errors so one bad feed does not abort the rest.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urljoin

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .attacks import ALLOWED_LICENSES, Attack
from .config import FeedSource, GauntletConfig
from .errors import FeedError, PackError
from .packloader import _check_mcp_assertion, _check_side_effect_assertion

# This build understands manifest schema version 1.
SUPPORTED_MANIFEST_VERSION = 1
# Hard cap on a single pack body (Fix #10); a feed pack is a small YAML file.
MAX_PACK_BYTES = 1024 * 1024  # 1 MiB


class FeedPackEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Fix #2: pattern-validated at PARSE so a traversal id/category is rejected before
    # any network/filesystem work.
    id: str = Field(pattern=r"^[a-z0-9-]+/[a-z0-9-]+$")
    category: str = Field(pattern=r"^[a-z0-9-]+$")
    version: int = Field(ge=1)
    license: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    url: str
    size: int | None = None


class FeedManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feed: str
    manifest_version: int = Field(ge=1)
    generated_at: str | None = None
    packs: list[FeedPackEntry] = []


class FeedDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feed: str
    id: str
    action: str  # pulled | updated | unchanged | skipped_license | checksum_failed | error
    reason: str = ""


class FeedUpdateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pulled: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_license: int = 0
    checksum_failed: int = 0
    errors: int = 0
    details: list[FeedDetail] = []


def _resolve_url(manifest_url: str, entry_url: str) -> str:
    """Absolute ``entry_url`` is used as-is; a relative one joins against the manifest."""
    return urljoin(manifest_url, entry_url)


def _atomic_write_bytes(dest: Path, content: bytes) -> None:
    """Write bytes atomically (temp in dest dir + os.replace), like runner._atomic_write."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
    tmp.write_bytes(content)
    os.replace(tmp, dest)


def _parse_attack_bytes(content: bytes, label: Path) -> Attack:
    """Validate pack bytes as an Attack with the same checks the loader runs."""
    try:
        docs = list(yaml.safe_load_all(content.decode("utf-8")))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise PackError(f"invalid YAML in {label}: {exc}") from exc
    if len(docs) != 1:
        raise PackError(f"expected exactly one YAML document in {label}, got {len(docs)}")
    data = docs[0]
    if not isinstance(data, dict):
        raise PackError(f"attack root must be a mapping in {label}")
    try:
        attack = Attack.model_validate(data)
    except ValidationError as exc:
        raise PackError(f"invalid attack in {label}: {exc}") from exc
    _check_side_effect_assertion(label, attack)
    _check_mcp_assertion(label, attack)
    return attack


async def _fetch_manifest(client: httpx.AsyncClient, feed: FeedSource) -> FeedManifest:
    try:
        resp = await client.get(feed.url)
    except httpx.HTTPError as exc:
        raise FeedError(f"feed {feed.name!r}: cannot reach {feed.url}: {exc}") from exc
    if not (200 <= resp.status_code < 300):
        raise FeedError(f"feed {feed.name!r}: manifest HTTP {resp.status_code}")
    try:
        data = yaml.safe_load(resp.text)
    except yaml.YAMLError as exc:
        raise FeedError(f"feed {feed.name!r}: invalid manifest YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise FeedError(f"feed {feed.name!r}: manifest root must be a mapping")
    try:
        manifest = FeedManifest.model_validate(data)
    except ValidationError as exc:
        raise FeedError(f"feed {feed.name!r}: invalid manifest: {exc}") from exc
    if manifest.manifest_version > SUPPORTED_MANIFEST_VERSION:
        raise FeedError(
            f"feed {feed.name!r}: unsupported manifest_version {manifest.manifest_version}; "
            f"this gauntlet understands up to {SUPPORTED_MANIFEST_VERSION}"
        )
    return manifest


def _record(result: FeedUpdateResult, feed: str, entry_id: str, action: str, reason: str) -> None:
    result.details.append(FeedDetail(feed=feed, id=entry_id, action=action, reason=reason))


async def _process_entry(
    client: httpx.AsyncClient,
    feed: FeedSource,
    entry: FeedPackEntry,
    cache_dir: Path,
    result: FeedUpdateResult,
    *,
    allow: bool,
    dry_run: bool,
) -> None:
    # 1. License gate BEFORE download (§4 invariant: never auto-arm an ambiguous license).
    if entry.license not in ALLOWED_LICENSES and not allow:
        result.skipped_license += 1
        _record(
            result, feed.name, entry.id, "skipped_license", f"unlisted license {entry.license!r}"
        )
        return

    # 2. Download the pack bytes.
    url = _resolve_url(feed.url, entry.url)
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        result.errors += 1
        _record(result, feed.name, entry.id, "error", f"download failed: {exc}")
        return
    if not (200 <= resp.status_code < 300):
        result.errors += 1
        _record(result, feed.name, entry.id, "error", f"pack HTTP {resp.status_code}")
        return
    content = resp.content
    if len(content) > MAX_PACK_BYTES:  # Fix #10: refuse oversize bodies.
        result.errors += 1
        _record(result, feed.name, entry.id, "error", f"pack exceeds {MAX_PACK_BYTES} byte cap")
        return

    # 3. Checksum verify (Fix #8: direct lowercase compare; both sides are lowercase hex).
    digest = hashlib.sha256(content).hexdigest()
    if digest != entry.sha256:
        result.checksum_failed += 1
        _record(result, feed.name, entry.id, "checksum_failed", "sha256 mismatch")
        return

    # 4. Validate content + check it coheres with the manifest claim.
    try:
        attack = _parse_attack_bytes(content, Path(f"{entry.id}.yaml"))
    except PackError as exc:
        result.errors += 1
        _record(result, feed.name, entry.id, "error", f"invalid pack: {exc}")
        return
    if (
        attack.id != entry.id
        or attack.category != entry.category
        or attack.license != entry.license
        or attack.version != entry.version
    ):
        result.errors += 1
        _record(result, feed.name, entry.id, "error", "content does not match manifest claim")
        return

    # 5. Cache write — path built from the VALIDATED attack (Fix #2), atomic (Fix #4).
    stem = attack.id.split("/", 1)[1]
    dest = cache_dir / attack.category / f"{stem}.yaml"
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == digest:
        result.unchanged += 1
        _record(result, feed.name, entry.id, "unchanged", f"version {entry.version}")
        return
    action = "updated" if dest.exists() else "pulled"
    if not dry_run:
        try:
            _atomic_write_bytes(dest, content)
        except OSError as exc:
            result.errors += 1
            _record(result, feed.name, entry.id, "error", f"cache write failed: {exc}")
            return
    if action == "pulled":
        result.pulled += 1
    else:
        result.updated += 1
    _record(result, feed.name, entry.id, action, f"version {entry.version}")


async def _process_feeds(
    client: httpx.AsyncClient,
    feeds: list[FeedSource],
    cache_dir: Path,
    result: FeedUpdateResult,
    *,
    allow: bool,
    dry_run: bool,
) -> None:
    for feed in feeds:
        try:
            manifest = await _fetch_manifest(client, feed)
        except FeedError as exc:
            result.errors += 1
            _record(result, feed.name, "", "error", str(exc))
            continue
        for entry in manifest.packs:
            await _process_entry(
                client, feed, entry, cache_dir, result, allow=allow, dry_run=dry_run
            )


async def update_feeds(
    config: GauntletConfig,
    *,
    client: httpx.AsyncClient | None = None,
    feed_name: str | None = None,
    dry_run: bool = False,
    allow_unlisted_licenses: bool = False,
) -> FeedUpdateResult:
    """Pull packs from configured feeds into ``config.catalog.feed_cache_dir``.

    Offline-testable: inject ``client`` (an ``httpx.AsyncClient`` backed by a
    ``MockTransport``). When ``client is None`` the connection is owned via ``async with``
    so fds are released (Fix #6). ``feed_name`` restricts to one feed; ``dry_run`` runs
    fetch+verify but writes nothing. Raises ``FeedError`` only for the no-cache-dir case.
    """
    cache_dir = config.catalog.feed_cache_dir
    if cache_dir is None:
        raise FeedError("no catalog.feed_cache_dir configured")
    cache_dir = Path(cache_dir)
    allow = allow_unlisted_licenses or config.catalog.allow_unlisted_licenses

    feeds = list(config.catalog.feeds)
    if feed_name is not None:
        feeds = [f for f in feeds if f.name == feed_name]

    result = FeedUpdateResult()
    if client is None:
        async with httpx.AsyncClient() as owned:
            await _process_feeds(owned, feeds, cache_dir, result, allow=allow, dry_run=dry_run)
    else:
        await _process_feeds(client, feeds, cache_dir, result, allow=allow, dry_run=dry_run)
    return result
