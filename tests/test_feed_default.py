"""The bundled default feed (feeds/) + zero-config `grendel update`.

Verifies the committed feed is self-consistent (every manifest SHA-256 matches its pack file, so
a live pull over GitHub raw succeeds) and that update_feeds pulls it end-to-end via a MockTransport
that serves the repo's own feed files — no real network.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx

from grendel.config import DEFAULT_FEED, CatalogConfig, FeedSource, GrendelConfig
from grendel.feed import FeedManifest, update_feeds

FEEDS = Path(__file__).resolve().parent.parent / "feeds"
MANIFEST = FEEDS / "manifest.json"
BASE = "https://feed.test/"


def test_manifest_validates_and_checksums_match() -> None:
    # The committed manifest must parse AND each SHA-256 must match its file byte-for-byte,
    # or a live `grendel update` would reject every pack as checksum_failed.
    manifest = FeedManifest.model_validate(json.loads(MANIFEST.read_text(encoding="utf-8")))
    assert manifest.packs, "feed manifest is empty"
    for entry in manifest.packs:
        pack = FEEDS / entry.url
        assert pack.is_file(), f"manifest references a missing pack: {entry.url}"
        assert hashlib.sha256(pack.read_bytes()).hexdigest() == entry.sha256, (
            f"SHA-256 mismatch for {entry.id} — run scripts/build_feed.py"
        )
        assert entry.url == f"packs/{entry.category}/{pack.name}"  # url coheres with category


def test_default_feed_points_at_repo_raw() -> None:
    assert DEFAULT_FEED.url.startswith("https://raw.githubusercontent.com/")
    assert DEFAULT_FEED.url.endswith("/feeds/manifest.json")


def _serve_feeds(request: httpx.Request) -> httpx.Response:
    rel = request.url.path.lstrip("/")  # "manifest.json" | "packs/<cat>/<file>.yaml"
    f = FEEDS / rel
    return httpx.Response(200, content=f.read_bytes()) if f.is_file() else httpx.Response(404)


def test_update_pulls_the_repo_feed(tmp_path: Path) -> None:
    cfg = GrendelConfig(
        catalog=CatalogConfig(
            feed_cache_dir=tmp_path,
            feeds=[FeedSource(name="grendel", url=BASE + "manifest.json")],
        )
    )
    n = len(FeedManifest.model_validate(json.loads(MANIFEST.read_text(encoding="utf-8"))).packs)

    async def go() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(_serve_feeds))
        res = await update_feeds(cfg, client=client)
        await client.aclose()
        assert res.pulled == n
        assert res.errors == 0 and res.checksum_failed == 0 and res.skipped_license == 0
        assert len(list(tmp_path.rglob("*.yaml"))) == n
        # idempotent: a second pull changes nothing
        client2 = httpx.AsyncClient(transport=httpx.MockTransport(_serve_feeds))
        res2 = await update_feeds(cfg, client=client2)
        await client2.aclose()
        assert res2.pulled == 0 and res2.unchanged == n

    asyncio.run(go())
