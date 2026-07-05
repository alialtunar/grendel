"""Refresh the GitHub feed from garak's latest Apache-2.0 corpora — run by the feed-refresh
workflow, so the feed grows without anyone installing garak or editing packs by hand.

Imports garak's curated corpora to a temp dir, keeps only attacks whose payload is NOT already
in the bundle or the feed, copies up to CAP new ones into feeds/packs/, then rebuilds the
manifest. A no-op run (nothing new) leaves the tree unchanged.

    python scripts/refresh_feed.py          # needs: pip install garak

Requires the `corpora` extra (garak). Safe to re-run; deterministic dedup by normalized payload.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import build_feed  # noqa: E402  (sibling script)

from grendel import corpus  # noqa: E402
from grendel.corpus import _norm_hash  # noqa: E402
from grendel.packloader import default_packs_dir, load_packs  # noqa: E402

FEED_PACKS = ROOT / "feeds" / "packs"
CAP = 150  # max new packs to add per run (feed stays a pull-per-pack, modest size)
KEEP = {"jailbreak", "prompt-injection"}  # text-scored categories suit the feed


def _existing_payload_hashes() -> set[str]:
    """Normalized-payload hashes already shipped (bundle) or in the feed — never re-add these."""
    seen = {_norm_hash(a.payload) for a in load_packs(default_packs_dir())}
    for f in FEED_PACKS.glob("*/*.yaml"):
        import yaml

        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("payload"), str):
            seen.add(_norm_hash(doc["payload"]))
    return seen


def main() -> None:
    seen = _existing_payload_hashes()
    added = 0
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for src in corpus.default_source_paths("garak"):
            corpus.import_corpus("garak", src, out)
        for pack in sorted(out.glob("*/*.yaml")):
            if added >= CAP:
                break
            import yaml

            doc = yaml.safe_load(pack.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or doc.get("category") not in KEEP:
                continue
            h = _norm_hash(doc.get("payload", ""))
            if h in seen:
                continue
            seen.add(h)
            dest = FEED_PACKS / doc["category"] / pack.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pack, dest)
            added += 1
    build_feed.main()
    print(f"refresh: {added} new pack(s) added to the feed")


if __name__ == "__main__":
    main()
