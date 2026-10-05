"""Reading the device list from the portal's DotVVM viewmodel.

The portal keeps its page state as JSON in a hidden input (``#__dot_viewmodel_root``). The
legacy script read ``viewModel.Scene.Sections[0].Devices[*].DeviceName``; this parser searches
every section, so a reordering of sections does not lose the devices.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Final

from sivin.ingest.portal.errors import ViewModelError
from sivin.ingest.portal.models import PortalDevice

logger = logging.getLogger(__name__)

ROOT_KEY: Final = "viewModel"
SCENE_KEY: Final = "Scene"
SECTIONS_KEY: Final = "Sections"
DEVICES_KEY: Final = "Devices"
DEVICE_NAME_KEY: Final = "DeviceName"


class ViewModelParser:
    """Pure parser of the DotVVM viewmodel JSON into :class:`PortalDevice` objects."""

    def parse(self, raw_json: str) -> list[PortalDevice]:
        """Return the devices of every section, in order, without duplicates.

        Parameters
        ----------
        raw_json : str
            The ``value`` of the viewmodel input.

        Returns
        -------
        list[PortalDevice]
            Devices in the order of the sections and of the devices in them; empty when the
            sections have empty device lists.

        Raises
        ------
        ViewModelError
            If the text is not JSON, the path ``viewModel.Scene.Sections`` is missing, no
            section has a ``Devices`` list, or a device has no non-empty ``DeviceName``.
        """
        sections = self._sections(self._load(raw_json))
        device_lists = [
            section[DEVICES_KEY]
            for section in sections
            if isinstance(section, Mapping) and isinstance(section.get(DEVICES_KEY), list)
        ]
        if not device_lists:
            raise ViewModelError(
                f"No section of {ROOT_KEY}.{SCENE_KEY}.{SECTIONS_KEY} has a '{DEVICES_KEY}' list; "
                "the portal's page structure has probably changed."
            )
        devices: list[PortalDevice] = []
        for entries in device_lists:
            for entry in entries:
                device = PortalDevice(self._device_name(entry))
                if device not in devices:
                    devices.append(device)
        logger.debug("Viewmodel lists %d device(s).", len(devices))
        return devices

    @staticmethod
    def _load(raw_json: str) -> Any:
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as error:
            raise ViewModelError(f"The viewmodel is not valid JSON: {error}") from error

    @staticmethod
    def _sections(document: Any) -> Sequence[Any]:
        node = document
        path: list[str] = []
        for key in (ROOT_KEY, SCENE_KEY, SECTIONS_KEY):
            path.append(key)
            if not isinstance(node, Mapping) or key not in node:
                raise ViewModelError(
                    f"The viewmodel has no '{'.'.join(path)}'; the portal's page structure has "
                    "probably changed."
                )
            node = node[key]
        if not isinstance(node, list):
            raise ViewModelError(f"'{'.'.join(path)}' in the viewmodel is not a list.")
        return node

    @staticmethod
    def _device_name(entry: Any) -> str:
        name = entry.get(DEVICE_NAME_KEY) if isinstance(entry, Mapping) else None
        if not isinstance(name, str) or not name.strip():
            raise ViewModelError(f"A device in the viewmodel has no '{DEVICE_NAME_KEY}': {entry!r}")
        return name.strip()
