"""Exceptions raised by the sensor registry."""

from __future__ import annotations


class RegistryError(ValueError):
    """Raised when a set of sensors violates a registry rule (duplicates, area)."""


class RegistryFormatError(ValueError):
    """Raised when a registry file cannot be read or does not follow the registry format."""


class GpxFormatError(ValueError):
    """Raised when a GPX file cannot be read or a waypoint is incomplete."""


class SensorLookupError(LookupError):
    """Raised when a name does not resolve to exactly one sensor of the registry."""


class AmbiguousSensorNameError(SensorLookupError):
    """Raised when a legacy 4-digit short name matches more than one sensor."""
