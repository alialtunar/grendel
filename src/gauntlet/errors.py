"""Exception hierarchy for gauntlet."""


class GauntletError(Exception):
    """Base class for all gauntlet errors."""


class ConfigError(GauntletError):
    """Raised when configuration is invalid (bad field, unknown provider, collision)."""


class AdapterError(GauntletError):
    """Raised when a target adapter fails (e.g. non-2xx HTTP response)."""


class ProviderError(GauntletError):
    """Raised when a provider cannot be used (e.g. a required API key is missing)."""


class PackError(GauntletError):
    """Raised for any pack/loader failure (malformed YAML, validation, path/id
    mismatch, license gating, duplicate id)."""
