"""The build state of the incremental site build (``site/data/.build-state.json``).

The state remembers, per published sensor, a fingerprint of its store partition files, the
SHA-256 of every file written for it, its summary and its index entries. A later build reuses
a sensor whose fingerprint and output files are unchanged without reading or checking its
data again; any other change (configuration, registry, off-site log, seasons, ``sivin``
version) makes the whole state invalid, so the result is always the same as a full build.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from sivin.core.ids import SensorId
from sivin.site.files import SiteFile, encode_json
from sivin.site.model import IndexEntries, SensorSummary

logger = logging.getLogger(__name__)

STATE_FILE: Final = ".build-state.json"
"""Name of the build state in the output directory."""

STATE_FORMAT: Final = 1
"""Version of the state layout; a state of another version is ignored (full build)."""


def fingerprint(parts: Iterable[bytes]) -> str:
    """Return a SHA-256 over several byte strings, each length-prefixed (unambiguous).

    Parameters
    ----------
    parts : iterable of bytes
        The inputs, in a fixed order.

    Returns
    -------
    str
        64 hex digits.
    """
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(len(part).to_bytes(8, "big"))
        hasher.update(part)
    return hasher.hexdigest()


class StoreFingerprints:
    """Fingerprints of the stored measurement files of each sensor.

    The store keeps one directory per sensor below ``<data_dir>/raw`` (``docs/storage.md``);
    the fingerprint covers the name and content of every file in it, so any append, rewrite or
    deletion changes it.

    Parameters
    ----------
    raw_dir : pathlib.Path
        The store's ``raw`` directory.
    """

    __slots__ = ("_raw_dir",)

    def __init__(self, raw_dir: Path) -> None:
        self._raw_dir = raw_dir

    def of(self, sensor_id: SensorId) -> str:
        """Return the fingerprint of one sensor's stored files.

        Parameters
        ----------
        sensor_id : SensorId
            The sensor.

        Returns
        -------
        str
            SHA-256 (hex) over the sorted file names and contents.
        """
        directory = self._raw_dir / str(sensor_id)
        files = sorted(p for p in directory.iterdir() if p.is_file()) if directory.is_dir() else []
        parts: list[bytes] = []
        for path in files:
            parts += [path.name.encode("utf-8"), hashlib.sha256(path.read_bytes()).digest()]
        return fingerprint(parts)


@dataclass(frozen=True)
class SensorState:
    """What the state remembers of one published sensor.

    Attributes
    ----------
    inputs : str
        :class:`StoreFingerprints` of the sensor when it was built.
    outputs : Mapping of str to str
        Relative path → SHA-256 of every per-sensor file written for it.
    summary : SensorSummary
        Its summary.
    indices : Mapping of int to IndexEntries
        Season → index id → published entry.
    """

    inputs: str
    outputs: Mapping[str, str]
    summary: SensorSummary
    indices: Mapping[int, IndexEntries] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))
        object.__setattr__(self, "indices", MappingProxyType(dict(self.indices)))

    @classmethod
    def of(
        cls,
        inputs: str,
        files: Iterable[SiteFile],
        summary: SensorSummary,
        indices: Mapping[int, IndexEntries],
    ) -> SensorState:
        """Build the state of a freshly built sensor.

        Parameters
        ----------
        inputs : str
            Its store fingerprint.
        files : iterable of SiteFile
            Its per-sensor files.
        summary : SensorSummary
            Its summary.
        indices : Mapping of int to IndexEntries
            Its index entries per season.

        Returns
        -------
        SensorState
            The state.
        """
        return cls(inputs, {file.path: file.digest for file in files}, summary, indices)

    def to_data(self) -> dict[str, Any]:
        """Return the state as JSON data.

        Returns
        -------
        dict
            ``inputs``, ``outputs`` (sorted), ``summary``, ``indices`` (season as text key).
        """
        return {
            "inputs": self.inputs,
            "outputs": dict(sorted(self.outputs.items())),
            "summary": self.summary.to_state(),
            "indices": {
                str(season): {k: dict(v) for k, v in entries.items()}
                for season, entries in sorted(self.indices.items())
            },
        }

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> SensorState:
        """Rebuild a state from :meth:`to_data` data.

        Parameters
        ----------
        data : Mapping
            Output of :meth:`to_data`.

        Returns
        -------
        SensorState
            The state.

        Raises
        ------
        KeyError, TypeError, ValueError, AttributeError
            If the data are malformed.
        """
        return cls(
            inputs=str(data["inputs"]),
            outputs={str(path): str(sha) for path, sha in data["outputs"].items()},
            summary=SensorSummary.from_state(data["summary"]),
            indices={
                int(season): {str(k): dict(v) for k, v in entries.items()}
                for season, entries in data["indices"].items()
            },
        )


@dataclass(frozen=True)
class BuildState:
    """The state of the last build.

    Attributes
    ----------
    settings : str
        Fingerprint of everything that applies to all sensors (configuration, registry,
        off-site log, ``sivin`` version, output format).
    seasons : tuple of int
        The seasons of the last build.
    sensors : Mapping of str to SensorState
        Sensor id → its state.
    """

    settings: str
    seasons: tuple[int, ...]
    sensors: Mapping[str, SensorState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sensors", MappingProxyType(dict(self.sensors)))

    def to_file(self) -> SiteFile:
        """Return the state as the file :data:`STATE_FILE`.

        Returns
        -------
        SiteFile
            Compact JSON, sensors sorted by id.
        """
        document = {
            "format": STATE_FORMAT,
            "settings": self.settings,
            "seasons": list(self.seasons),
            "sensors": {sid: state.to_data() for sid, state in sorted(self.sensors.items())},
        }
        return SiteFile(STATE_FILE, encode_json(document))

    @classmethod
    def parse(cls, content: bytes | None) -> BuildState | None:
        """Read a state written by :meth:`to_file`.

        Parameters
        ----------
        content : bytes or None
            The file content (``None`` if there is no state).

        Returns
        -------
        BuildState or None
            The state; ``None`` (with a warning) if it is missing, of another format or
            malformed, so the build starts from scratch.
        """
        if content is None:
            return None
        try:
            data = json.loads(content.decode("utf-8"))
            if data["format"] != STATE_FORMAT:
                logger.info("Site build state of format %s ignored.", data["format"])
                return None
            return cls(
                settings=str(data["settings"]),
                seasons=tuple(int(season) for season in data["seasons"]),
                sensors={
                    str(sid): SensorState.from_data(item) for sid, item in data["sensors"].items()
                },
            )
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            logger.warning("Site build state is unreadable (%s); building everything.", error)
            return None
