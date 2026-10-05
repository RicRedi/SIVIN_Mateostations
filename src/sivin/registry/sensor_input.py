"""Preparation of a sensor's raw registry properties before validation.

Two steps run on the mapping read from ``sensors/sensors.geojson`` (or given to
:class:`~sivin.registry.model.Sensor`), in this order:

1. :func:`migrate_site`: the key ``site`` of files written before 2026-10-05 becomes ``track``
   (``municipality`` null), with a warning;
2. :func:`normalise_names`: leading and trailing whitespace of the name fields is stripped and
   internal runs of whitespace are collapsed to one space, with a warning when a value changed.
   Names group the sensors in the web (owner decision 2026-10-05); ``"Mikulov "`` and
   ``"Mikulov"`` must not be two groups.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Final

logger = logging.getLogger(__name__)

DEPRECATED_SITE_KEY: Final = "site"
"""Registry key of the site name before 2026-10-05, replaced by ``municipality`` and ``track``.

Owner decision 2026-10-05 (MIGRATION_PLAN §0.5): the web groups sensors by municipality and
vineyard track. An old file with ``site`` still loads; the value is read as ``track``.
"""

SITE_REPLACEMENT_KEYS: Final = ("municipality", "track")
"""The keys that replaced :data:`DEPRECATED_SITE_KEY`."""

NAME_KEYS: Final = ("label", "municipality", "track", "variety")
"""Name fields whose whitespace is normalised on load."""

_WHITESPACE_RUN: Final = re.compile(r"\s+")


def normalised_name(text: str) -> str:
    """Strip a name and collapse internal runs of whitespace to one space.

    Parameters
    ----------
    text : str
        A name, e.g. ``"  Velké   Pavlovice "``.

    Returns
    -------
    str
        E.g. ``"Velké Pavlovice"``; empty if ``text`` is only whitespace.
    """
    return _WHITESPACE_RUN.sub(" ", text).strip()


def migrate_site(data: Mapping[str, object]) -> dict[str, object]:
    """Replace the deprecated ``site`` key by ``municipality`` (null) and ``track``.

    Parameters
    ----------
    data : Mapping
        Raw sensor properties.

    Returns
    -------
    dict
        The properties; unchanged (as a copy) without ``site``.

    Raises
    ------
    ValueError
        If ``site`` is given together with ``municipality`` or ``track``, or its value is
        neither a non-blank string nor null. The message names ``site`` and the fix.
    """
    if DEPRECATED_SITE_KEY not in data:
        return dict(data)
    site = data[DEPRECATED_SITE_KEY]
    present = [key for key in SITE_REPLACEMENT_KEYS if key in data]
    if present:
        missing = [key for key in SITE_REPLACEMENT_KEYS if key not in data]
        also = f" and add {', '.join(repr(key) for key in missing)} (null if unknown)"
        raise ValueError(
            f"'{DEPRECATED_SITE_KEY}' was replaced by 'municipality' and 'track' (2026-10-05); "
            f"remove '{DEPRECATED_SITE_KEY}'{also if missing else ''}"
        )
    if site is not None and (not isinstance(site, str) or not normalised_name(site)):
        raise ValueError(
            f"'{DEPRECATED_SITE_KEY}' (deprecated, read as 'track') must be a non-empty string "
            f"or null, got {site!r}; better replace it by 'municipality' and 'track' "
            "(docs/sensors.md)"
        )
    logger.warning(
        "Sensor %s: the registry key '%s' is deprecated (replaced by 'municipality' and "
        "'track', 2026-10-05); its value %r is read as 'track' and 'municipality' as null. "
        "Save the registry to write the new keys, then fill in 'municipality' "
        "(docs/sensors.md).",
        data.get("id"),
        DEPRECATED_SITE_KEY,
        site,
    )
    migrated = {key: value for key, value in data.items() if key != DEPRECATED_SITE_KEY}
    return migrated | {"municipality": None, "track": site}


def normalise_names(data: Mapping[str, object]) -> dict[str, object]:
    """Normalise the whitespace of the name fields (:data:`NAME_KEYS`).

    Parameters
    ----------
    data : Mapping
        Raw sensor properties.

    Returns
    -------
    dict
        A copy with normalised names; other values unchanged. A name that is only whitespace
        becomes empty and is rejected by validation.
    """
    result = dict(data)
    for key in NAME_KEYS:
        value = result.get(key)
        if not isinstance(value, str):
            continue
        cleaned = normalised_name(value)
        if cleaned != value:
            logger.warning(
                "Sensor %s: '%s' %r has extra whitespace; read as %r. Save the registry to "
                "write the cleaned value.",
                result.get("id"),
                key,
                value,
                cleaned,
            )
            result[key] = cleaned
    return result
