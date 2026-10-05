"""Writers of the site-wide files: ``manifest.json``, ``sensors.geojson``, ``latest.json`` and
``indices/<season>.json`` (MIGRATION_PLAN §2.6).

They are written from a :class:`~sivin.site.model.SiteSnapshot` on every build (they carry
``generated_at`` or depend on every sensor); each kind is one class behind
:class:`SiteFileWriter`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Final

from sivin.redaction import SecretRedactor
from sivin.site.columns import iso_utc_seconds, unix_second
from sivin.site.files import SiteFile, encode_json
from sivin.site.labels import VARIABLES, IndexCatalog, VariableSpec
from sivin.site.model import SiteSnapshot

SCHEMA_VERSION: Final = 1
"""``schema_version`` of the site data contract (MIGRATION_PLAN §2.6)."""

MANIFEST_FILE: Final = "manifest.json"
REGISTRY_FILE: Final = "sensors.geojson"
LATEST_FILE: Final = "latest.json"


def indices_path(season: int) -> str:
    """Return ``indices/<season>.json``."""
    return f"indices/{season}.json"


class SiteFileWriter(ABC):
    """Builds one kind of site-wide file.

    Parameters
    ----------
    redactor : SecretRedactor, optional
        Applied to every string written; nothing is redacted when omitted.
    """

    __slots__ = ("_redactor",)

    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        self._redactor = redactor

    @abstractmethod
    def files(self, snapshot: SiteSnapshot) -> list[SiteFile]:
        """Return the files of this kind.

        Parameters
        ----------
        snapshot : SiteSnapshot
            The published sensors, seasons and indices.

        Returns
        -------
        list of SiteFile
            The files.
        """

    def _file(self, path: str, document: dict[str, Any]) -> SiteFile:
        return SiteFile(path, encode_json(document, self._redactor))


class ManifestWriter(SiteFileWriter):
    """``manifest.json``: variables, sensors with their availability, seasons and indices.

    Every sensor entry has ``first_t``, ``last_t``, ``raw_months`` (§2.6) and ``status``, the
    registry life-cycle state (``active``, ``inactive``, ``retired``), so the web can grey out
    retired sensors whose history is still published.

    Parameters
    ----------
    catalog : IndexCatalog
        Labels and documentation links of the indices.
    variables : sequence of VariableSpec, optional
        The variables; :data:`~sivin.site.labels.VARIABLES` when omitted.
    redactor : SecretRedactor, optional
        Applied to every string written.
    """

    __slots__ = ("_catalog", "_variables")

    def __init__(
        self,
        catalog: IndexCatalog,
        variables: Sequence[VariableSpec] = VARIABLES,
        redactor: SecretRedactor | None = None,
    ) -> None:
        super().__init__(redactor)
        self._catalog = catalog
        self._variables = tuple(variables)

    def files(self, snapshot: SiteSnapshot) -> list[SiteFile]:
        """Return ``[manifest.json]``.

        Parameters
        ----------
        snapshot : SiteSnapshot
            The site.

        Returns
        -------
        list of SiteFile
            The manifest.
        """
        sensors = {
            str(sensor.sensor_id): {
                "first_t": sensor.summary.first_t,
                "last_t": sensor.summary.last_t,
                "raw_months": list(sensor.summary.raw_months),
                "status": sensor.status,
            }
            for sensor in snapshot.sensors
        }
        document = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": iso_utc_seconds(snapshot.generated_at),
            "display_timezone": snapshot.display_timezone,
            "variables": [variable.as_dict() for variable in self._variables],
            "sensors": sensors,
            "seasons": list(snapshot.seasons),
            "indices": [self._catalog.entry(spec) for spec in snapshot.indices],
        }
        return [self._file(MANIFEST_FILE, document)]


class RegistryCopyWriter(SiteFileWriter):
    """``sensors.geojson``: the sensor registry file, byte for byte (§2.6 "kopie registru")."""

    __slots__ = ()

    def files(self, snapshot: SiteSnapshot) -> list[SiteFile]:
        """Return ``[sensors.geojson]``.

        Parameters
        ----------
        snapshot : SiteSnapshot
            The site (its ``registry`` bytes).

        Returns
        -------
        list of SiteFile
            The copy.
        """
        return [SiteFile(REGISTRY_FILE, snapshot.registry)]


class LatestWriter(SiteFileWriter):
    """``latest.json``: the last valid sample of each sensor and whether it is stale.

    A sensor without any valid sample (e.g. off site all the time) is left out.

    Parameters
    ----------
    stale_after_s : float
        A sample older than this (seconds before ``generated_at``) is ``stale``.
    redactor : SecretRedactor, optional
        Applied to every string written.
    """

    __slots__ = ("_stale_after_s",)

    def __init__(self, stale_after_s: float, redactor: SecretRedactor | None = None) -> None:
        super().__init__(redactor)
        self._stale_after_s = stale_after_s

    def files(self, snapshot: SiteSnapshot) -> list[SiteFile]:
        """Return ``[latest.json]``.

        Parameters
        ----------
        snapshot : SiteSnapshot
            The site.

        Returns
        -------
        list of SiteFile
            The latest values.
        """
        now_s = unix_second(snapshot.generated_at)
        sensors: dict[str, Any] = {}
        for sensor in snapshot.sensors:
            latest = sensor.summary.latest
            if latest is None:
                continue
            sensors[str(sensor.sensor_id)] = {
                "t": latest.t,
                "temp_c": latest.temp_c,
                "rh_pct": latest.rh_pct,
                "qc": latest.qc,
                "stale": now_s - latest.t > self._stale_after_s,
            }
        document = {"generated_at": iso_utc_seconds(snapshot.generated_at), "sensors": sensors}
        return [self._file(LATEST_FILE, document)]


class SeasonIndicesWriter(SiteFileWriter):
    """``indices/<season>.json`` for every season of the snapshot.

    ``computed_at`` is the ``generated_at`` of the build that wrote the file. A sensor without
    data in the season window is absent; an index that failed for a sensor is left out of its
    entry (the failure is reported by the build).
    """

    __slots__ = ()

    def files(self, snapshot: SiteSnapshot) -> list[SiteFile]:
        """Return one file per season.

        Parameters
        ----------
        snapshot : SiteSnapshot
            The site.

        Returns
        -------
        list of SiteFile
            In increasing season order.
        """
        computed_at = iso_utc_seconds(snapshot.generated_at)
        files = []
        for season in snapshot.seasons:
            sensors = {
                str(sensor.sensor_id): dict(sensor.indices[season])
                for sensor in snapshot.sensors
                if season in sensor.indices
            }
            document = {"season": season, "computed_at": computed_at, "sensors": sensors}
            files.append(self._file(indices_path(season), document))
        return files


def default_site_writers(
    stale_after_s: float,
    catalog: IndexCatalog | None = None,
    redactor: SecretRedactor | None = None,
) -> tuple[SiteFileWriter, ...]:
    """Return the site-wide writers of the contract: manifest, registry copy, latest, indices.

    Parameters
    ----------
    stale_after_s : float
        Staleness threshold of ``latest.json`` in seconds (``site.stale_after_s``).
    catalog : IndexCatalog, optional
        Index labels; the built-in ones when omitted.
    redactor : SecretRedactor, optional
        Applied to every string written.

    Returns
    -------
    tuple of SiteFileWriter
        The writers.
    """
    return (
        ManifestWriter(catalog if catalog is not None else IndexCatalog(), redactor=redactor),
        RegistryCopyWriter(redactor),
        LatestWriter(stale_after_s, redactor),
        SeasonIndicesWriter(redactor),
    )
