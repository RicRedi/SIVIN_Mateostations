"""``sivin build-site``: the static site data of the web portal from the stored measurements.

The measurements of every published sensor are read **through quality control**
(:meth:`~sivin.app.quality.QualityService.checked`: QC with the off-site log and the
precipitation set-aside), the indices come from :class:`~sivin.app.indices.IndicesService`;
:class:`~sivin.site.builder.SiteBuilder` writes the files (``docs/site.md``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from sivin import __version__
from sivin.analytics.base import IndexRegistry
from sivin.app.indices import IndicesService
from sivin.config import SivinConfig
from sivin.core.ids import SensorId
from sivin.quality.pipeline import QualityResult
from sivin.registry.registry import SensorRegistry
from sivin.site.builder import SiteBuilder, SiteInputs, SiteReport
from sivin.site.files import SiteOutput
from sivin.site.indices import IndexBatch
from sivin.site.labels import IndexSpec
from sivin.site.state import fingerprint
from sivin.storage.store import MeasurementStore

logger = logging.getLogger(__name__)

SITE_OUTPUT_FORMAT: Final = 1
"""Version of the files the builder writes; raise it when the output of the same data changes,
so the next build is a full one."""

FINGERPRINT_EXCLUDED_SECTIONS: Final = frozenset({"paths", "ingest"})
"""Configuration sections that do not change the site data (locations, portal, parsers)."""


class SiteIndices:
    """The configured climate indices for the site (:class:`~sivin.site.indices.IndexSource`).

    Parameters
    ----------
    service : IndicesService
        A dry-run indices service (it writes no derived file).
    registry : IndexRegistry
        The registered indices (ids and units for the manifest).
    """

    __slots__ = ("_registry", "_service")

    def __init__(self, service: IndicesService, registry: IndexRegistry) -> None:
        self._service = service
        self._registry = registry

    def specs(self) -> tuple[IndexSpec, ...]:
        """Return id and unit of every registered index, sorted by id.

        Returns
        -------
        tuple of IndexSpec
            The indices of the manifest.
        """
        return tuple(IndexSpec(i, self._registry.get(i).unit) for i in self._registry.ids())

    def compute(self, season: int, checked: Mapping[SensorId, QualityResult]) -> IndexBatch:
        """Compute every configured index of a season for the given sensors.

        Parameters
        ----------
        season : int
            The season year.
        checked : Mapping of SensorId to QualityResult
            QC results over the whole record; only these sensors are computed.

        Returns
        -------
        IndexBatch
            Results and failures.
        """
        if not checked:
            return IndexBatch()
        report = self._service.run(season, list(checked), checked=checked)
        return IndexBatch(report.results, report.failures)


class SiteInputsLoader:
    """Decide which sensors are published and fingerprint the shared inputs.

    Published are the registry sensors that have stored data, retired ones included (with
    their status, so the web can grey them out). A stored sensor that is not in the registry
    has no position or label and is left out with a warning.

    Parameters
    ----------
    store : MeasurementStore
        The measurement store.
    registry : SensorRegistry
        The validated registry.
    registry_file : pathlib.Path
        The registry file (copied to ``sensors.geojson``).
    offsite_log_file : pathlib.Path
        The off-site log (part of the fingerprint).
    config : SivinConfig
        The resolved configuration.
    """

    __slots__ = ("_config", "_offsite_log_file", "_registry", "_registry_file", "_store")

    def __init__(
        self,
        store: MeasurementStore,
        registry: SensorRegistry,
        registry_file: Path,
        offsite_log_file: Path,
        config: SivinConfig,
    ) -> None:
        self._store = store
        self._registry = registry
        self._registry_file = registry_file
        self._offsite_log_file = offsite_log_file
        self._config = config

    def load(self) -> SiteInputs:
        """Return the inputs of a build.

        Returns
        -------
        SiteInputs
            Published sensors with status, registry bytes, shared fingerprint, display zone.
        """
        sensors: dict[SensorId, str] = {}
        for sensor_id in self._store.sensors():
            if sensor_id not in self._registry:
                logger.warning(
                    "Sensor %s has stored data but is not in the registry; not published.",
                    sensor_id,
                )
                continue
            sensors[sensor_id] = str(self._registry.get(sensor_id).status)
        registry = self._registry_file.read_bytes()
        offsite = self._offsite_log_file.read_bytes() if self._offsite_log_file.is_file() else b""
        settings = self._config.model_dump(mode="json", exclude=set(FINGERPRINT_EXCLUDED_SECTIONS))
        shared = fingerprint(
            [
                str(SITE_OUTPUT_FORMAT).encode(),
                __version__.encode(),
                json.dumps(settings, sort_keys=True).encode(),
                registry,
                offsite,
            ]
        )
        return SiteInputs(sensors, registry, shared, self._config.time.display_timezone)


class SiteService:
    """Build the site data of the workspace.

    Parameters
    ----------
    builder : SiteBuilder
        Generates the files.
    inputs : SiteInputsLoader
        Published sensors and the shared fingerprint.
    default_out : pathlib.Path
        Output directory when none is given (``<paths.site_dir>/data``).
    """

    __slots__ = ("_builder", "_default_out", "_inputs")

    def __init__(self, builder: SiteBuilder, inputs: SiteInputsLoader, default_out: Path) -> None:
        self._builder = builder
        self._inputs = inputs
        self._default_out = default_out

    def build(
        self,
        out: Path | None = None,
        seasons: Sequence[int] | None = None,
        full: bool = False,
        checked: Mapping[SensorId, QualityResult] | None = None,
    ) -> SiteReport:
        """Build the site data.

        Parameters
        ----------
        out : pathlib.Path, optional
            Output directory; ``<paths.site_dir>/data`` when omitted.
        seasons : sequence of int, optional
            Season years of the indices files; every calendar year with data when omitted.
        full : bool, optional
            Rebuild everything, ignoring the previous build state.
        checked : Mapping of SensorId to QualityResult, optional
            QC results already computed over the whole record (``sivin run``).

        Returns
        -------
        SiteReport
            The report of the build.
        """
        output = SiteOutput(out if out is not None else self._default_out)
        return self._builder.build(output, self._inputs.load(), seasons, full, checked)
