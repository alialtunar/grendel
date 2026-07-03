"""Optional gitignored local secrets: keep API keys off the committed config.

`grendel.local.yaml` (cwd, gitignored) holds a ``secrets: {ENV_NAME: value}`` map. At startup it is
merged into the environment for any var **not already set** (a real env var always wins), so a user
can avoid re-``export``-ing each session without putting a key in the committed ``grendel.yaml``.
Values are never printed by callers (the menu masks them). Malformed files raise ConfigError, not a
raw traceback — mirroring ``config.load_config``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import ConfigError

LOCAL_SECRETS_FILE = "grendel.local.yaml"


class _LocalSecrets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secrets: dict[str, str] = {}


def load_local_secrets(path: Path | str) -> dict[str, str]:
    """Read the ``secrets:`` map from a local secrets file (missing file → {}).

    Malformed content (bad YAML, non-mapping root, unknown keys, non-string values) raises
    ConfigError rather than a raw pydantic/yaml traceback.
    """
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a mapping with a 'secrets' block")
    try:
        model = _LocalSecrets.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid {path}: {exc}") from exc
    return dict(model.secrets)


def merge_secrets_into_env(secrets: Mapping[str, str], env: MutableMapping[str, str]) -> None:
    """Set each secret in ``env`` ONLY if that var is not already present (a real env var wins)."""
    for name, value in secrets.items():
        if name not in env:
            env[name] = value


def save_local_secret(name: str, value: str, path: Path | str = LOCAL_SECRETS_FILE) -> None:
    """Persist one secret into the local (gitignored) secrets file, preserving any existing ones.

    Atomic write. The value is never logged here; callers mask it. NOT written to grendel.yaml.
    """
    name = (name or "").strip()
    if not name:
        raise ConfigError("secret name (env var) is required")
    path = Path(path)
    existing = load_local_secrets(path)
    existing[name] = value
    text = yaml.safe_dump({"secrets": existing}, sort_keys=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
