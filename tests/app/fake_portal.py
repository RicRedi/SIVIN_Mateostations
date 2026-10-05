"""The WP-1.3 fake portal, extended to download SYNTHETIC CSV exports (no browser, no network)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tests.app.project import write_synthetic_export
from tests.ingest.portal.conftest import (
    FIXTURES,
    PASSWORD,
    USERNAME,
    Behaviour,
    FakeDriverFactory,
    FakePortalDriver,
)

from sivin.ingest.portal.credentials import PortalCredentials, Secret
from sivin.ingest.portal.driver import WebDriverFactory
from sivin.ingest.portal.settings import PortalSettings

VIEWMODEL_JSON = (FIXTURES / "viewmodel_sample.json").read_text(encoding="utf-8")
"""Synthetic viewmodel with the devices 77678271 (registered), 77678272 and 77678273 (not)."""


def credentials() -> PortalCredentials:
    """The synthetic credentials the fake portal accepts."""
    return PortalCredentials(USERNAME, Secret(PASSWORD))


class ExportingPortalDriver(FakePortalDriver):
    """A fake portal whose ``ok`` exports are parseable SYNTHETIC CSV files (2 days)."""

    def _export(self, name: str, behaviour: Behaviour) -> None:
        if behaviour != "ok":
            super()._export(name, behaviour)
            return
        self.export_counter += 1
        serial = name.split()[-1]
        write_synthetic_export(
            self.settings.download_dir,
            serial=serial,
            days=2,
            stamp=f"20260605_06000{self.export_counter}",
        )


def drivers(
    behaviours: dict[str, Behaviour] | None = None,
) -> Callable[[PortalSettings], WebDriverFactory]:
    """Return a driver-factory builder that serves :class:`ExportingPortalDriver`."""

    def build(settings: PortalSettings) -> WebDriverFactory:
        driver: Any = ExportingPortalDriver(settings, VIEWMODEL_JSON, behaviours)
        return FakeDriverFactory(settings, driver)

    return build
