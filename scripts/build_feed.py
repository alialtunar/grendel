"""Regenerate feeds/manifest.json from the pack files under feeds/packs/.

The feed is what `grendel update` pulls from (hosted on GitHub raw). Each pack entry pins the
file's SHA-256 + license so the client can verify what it downloads. Run after adding/changing a
feed pack; the scheduled feed-refresh workflow runs this too. Deterministic (no timestamp) so a
no-op run produces no diff.

    python scripts/build_feed.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

FEEDS = Path(__file__).resolve().parent.parent / "feeds"
PACKS = FEEDS / "packs"
MANIFEST = FEEDS / "manifest.json"


def build() -> dict:
    packs = []
    for path in sorted(PACKS.glob("*/*.yaml")):
        raw = path.read_bytes()  # hash the exact bytes served over raw.githubusercontent
        doc = yaml.safe_load(raw.decode("utf-8"))
        packs.append({
            "id": doc["id"],
            "category": doc["category"],
            "version": doc["version"],
            "license": doc["license"],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "url": f"packs/{doc['category']}/{path.name}",  # relative to the manifest URL
        })
    packs.sort(key=lambda p: p["id"])
    return {"feed": "grendel", "manifest_version": 1, "packs": packs}


def main() -> None:
    manifest = build()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST} with {len(manifest['packs'])} pack(s)")


if __name__ == "__main__":
    main()
