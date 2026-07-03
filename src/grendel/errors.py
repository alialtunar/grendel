"""Exception hierarchy for grendel."""


class GrendelError(Exception):
    """Base class for all grendel errors."""


class ConfigError(GrendelError):
    """Raised when configuration is invalid (bad field, unknown provider, collision)."""


class AdapterError(GrendelError):
    """Raised when a target adapter fails (e.g. non-2xx HTTP response).

    Carries an optional ``status_code`` so the runner can classify 429/5xx as
    transient. ``AdapterError("msg")`` still works (status_code defaults to None),
    and ``str(exc)`` stays the human-readable message.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderError(GrendelError):
    """Raised when a provider cannot be used (e.g. a required API key is missing)."""


class PackError(GrendelError):
    """Raised for any pack/loader failure (malformed YAML, validation, path/id
    mismatch, license gating, duplicate id)."""


class FeedError(GrendelError):
    """Raised for feed-level failures: manifest parse, unsupported manifest_version,
    unreachable feed, or no feed_cache_dir configured (Phase 9)."""
