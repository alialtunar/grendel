# Authoring attack packs

This guide shows how to add an attack to gauntlet as **pure YAML** — no code changes. An
attack pack is a single YAML file describing one attack: where its payload is injected, how
success is detected, and its OWASP/ATLAS mapping and license. The loader validates every
field before an attack can run.

---

## 1. The Attack schema (every field)

Each pack is one YAML document with these fields (all required unless noted):

| Field | Type / rule | Notes |
|-------|-------------|-------|
| `id` | `^[a-z0-9-]+/[a-z0-9-]+$` | `<category>/<stem>`. Must equal `category` + the file stem (coherence rule below). |
| `name` | non-empty string | Human-readable title. |
| `category` | `^[a-z0-9-]+$` | Must match the parent directory name. `control` is reserved. |
| `owasp` | `LLM01`..`LLM10` | OWASP LLM Top-10 mapping (surfaced in every report). |
| `atlas` | `AML.Tdddd` or `AML.Tdddd.ddd` | MITRE ATLAS technique id. |
| `surface` | `prompt` \| `tool-output` \| `rag` \| `mcp-desc` | Where the payload is injected. |
| `severity` | `low` \| `medium` \| `high` \| `critical` | |
| `license` | SPDX string | Must be in the allowlist (see below) or the pack is refused. |
| `version` | integer ≥ 1 | Pack content version; drives feed "updated vs unchanged". |
| `payload` | non-empty string | The text sent to the target. |
| `success_when` | tagged union | How success is detected — see §2. |
| `references` | list of non-empty strings (optional) | Links/citations. |

### The id / category / stem coherence rule

For a file at `src/gauntlet/packs/prompt-injection/direct-override-01.yaml`:

- `category` MUST be `prompt-injection` (the parent directory),
- `id` MUST be `prompt-injection/direct-override-01` (`category/stem`).

A mismatch is a load error naming the file. This keeps ids unique and discoverable.

---

## 2. The `success_when` types

`success_when` is a tagged union discriminated by `type`. One worked example each:

### `string` — deterministic text match

```yaml
success_when:
  type: string
  contains: ["GAUNTLET-PWNED"]   # at least one of contains / pattern is required
  pattern: "PWNED-\\d+"           # optional regex (validated at load)
  case_sensitive: false           # default false
  match: any                      # any | all (default any)
```

### `side-effect` — outcome assertion against an agent/sandbox

```yaml
success_when:
  type: side-effect
  assert: "fs.wrote('/tmp/pwned.txt')"   # parsed/validated at load time
```

### `mcp-assert` — protocol-level MCP assertion

```yaml
success_when:
  type: mcp-assert
  assert: "called_tool('delete_file')"   # parsed/validated at load time
```

### `classifier` — refusal/harm classifier outcome

```yaml
success_when:
  type: classifier
  classifier: refusal
  label: attack_succeeded
  threshold: 0.5    # 0..1, default 0.5
```

### `judge` — LLM-as-judge outcome

```yaml
success_when:
  type: judge
  rubric: harmful-compliance
  pass_if: attack_succeeded
```

---

## 3. License requirement

Every pack declares a `license`. Only permissive, embeddable, commercial-safe SPDX
licenses are allowed by default:

```
Apache-2.0, MIT, BSD-2-Clause, BSD-3-Clause, CC0-1.0
```

A pack whose license is **not** in this allowlist is **refused** by the loader and is
**never armed**. You can override locally with `--allow-unlisted-licenses` (or
`catalog.allow_unlisted_licenses: true`), but such packs are flagged `(unlisted license)`
in `list --packs`, and a remote feed will **never** download an unlisted-license pack
unless you opt in explicitly.

---

## 4. Where to put the file

There are three places a pack can live; all use the same `<category>/<stem>.yaml` layout
and the same validation:

1. **Bundled** — `src/gauntlet/packs/<category>/<stem>.yaml` (shipped with gauntlet;
   `source=bundled`).
2. **A user pack directory** — any directory listed under `catalog.pack_dirs`
   (`source=user`). Recommended conventions: `./packs` (project) or `~/.gauntlet/packs`
   (user). These are explicit config, not auto-scanned, so runs stay reproducible.
3. **A feed** — published in a feed manifest and pulled by `gauntlet update` into
   `catalog.feed_cache_dir` (`source=feed`). See §6.

Example config:

```yaml
catalog:
  pack_dirs:
    - ./packs
  feed_cache_dir: ~/.gauntlet/feed-cache
  feeds:
    - name: community
      url: https://feed.example/manifest.yaml
```

A duplicate `id` across sources is a load error by default; set
`catalog.allow_override: true` to let a more-local source win (user > feed > bundled).

A `staged_dir` is an optional landing zone: its packs load as `source=staged`,
**armed=false** — they appear in `gauntlet list --packs --staged` but are never run until a
human moves the file into a real pack dir.

---

## 5. How to validate

The loader runs the same checks everywhere (schema, license gate, id/category coherence,
and `assert` parsing for side-effect / mcp-assert). To validate your pack, point a config
at its directory and list the catalog — any problem is reported as a `pack error` naming the
file:

```
gauntlet --config gauntlet.yaml list --packs
```

A clean pack appears as a row tagged with its `[source]`, its OWASP/ATLAS codes, and its
license. `load_catalog(config)` performs the identical validation programmatically.

---

## 6. The feed manifest format (for publishers)

A feed is a single manifest document (JSON or YAML) served at the feed `url`, pinning each
pack's version, license, and SHA-256 checksum:

```yaml
feed: gauntlet-community
manifest_version: 1
generated_at: "2026-06-01T00:00:00Z"   # optional, informational
packs:
  - id: prompt-injection/new-trick-07
    category: prompt-injection
    version: 2
    license: Apache-2.0
    sha256: "9f86d0818...e8b2"           # lowercase hex sha256 of the pack YAML bytes
    url: "https://feed.example/packs/new-trick-07.yaml"   # absolute or relative to the manifest
    size: 1234                            # optional, informational
```

`gauntlet update` fetches the manifest, **license-gates each pack before download**,
enforces a 1 MiB size cap, **verifies the SHA-256 checksum**, validates the pack content and
checks it coheres with the manifest claim (id/category/license/version), then writes verified
packs atomically into `feed_cache_dir/<category>/<stem>.yaml`. The cache path is always built
from the **validated** attack's fields, never from manifest-supplied strings, so a malicious
manifest cannot write outside the cache. Re-running on an unchanged manifest reports
everything `unchanged` and rewrites nothing.
