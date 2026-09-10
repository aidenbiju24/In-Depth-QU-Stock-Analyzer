"""Typed errors used across the backend so failures are explicit, never silent."""
from __future__ import annotations


class QuantError(Exception):
    """Base class for all backend errors."""


class ProviderError(QuantError):
    """A data provider request failed (network, API error, rate limit)."""

    def __init__(self, provider: str, detail: str):
        self.provider = provider
        self.detail = detail
        super().__init__(f"[{provider}] {detail}")


class RateLimitError(ProviderError):
    """Provider signalled a rate limit / daily quota exhaustion."""


class MissingDataError(QuantError):
    """Data required for a calculation is unavailable."""

    def __init__(self, what: str, reason: str = "unavailable"):
        self.what = what
        self.reason = reason
        super().__init__(f"missing data: {what} ({reason})")


class ValidationError(QuantError):
    """Data failed validation and must not enter the quant engine."""


class CalculationError(QuantError):
    """A financial calculation could not be performed on the given inputs."""


class InvalidAssumptionError(CalculationError):
    """Model assumptions are mathematically invalid (e.g. terminal g >= WACC)."""
