"""Tests of ViewModelParser on the synthetic viewmodel sample and broken variants."""

from __future__ import annotations

import json
from typing import Any

import pytest

from sivin.core.ids import SensorId
from sivin.ingest.portal.errors import ViewModelError
from sivin.ingest.portal.models import PortalDevice
from sivin.ingest.portal.viewmodel import ViewModelParser


def _document(sections: Any) -> str:
    return json.dumps({"viewModel": {"Scene": {"Sections": sections}}})


def test_parses_devices_of_the_saved_sample(viewmodel_json: str) -> None:
    devices = ViewModelParser().parse(viewmodel_json)

    assert devices == [
        PortalDevice("8615620 77678271"),
        PortalDevice("8615621 77678272"),
        PortalDevice("8615622 77678273"),
    ]
    assert devices[0].sensor_id == SensorId("77678271")


def test_finds_devices_outside_the_first_section() -> None:
    raw = _document(
        [
            {"Name": "Summary"},
            {"Devices": [{"DeviceName": "8615620 77678271"}]},
            {"Devices": [{"DeviceName": " 8615621 77678272 "}, {"DeviceName": "8615620 77678271"}]},
        ]
    )

    names = [device.name for device in ViewModelParser().parse(raw)]

    assert names == ["8615620 77678271", "8615621 77678272"]


def test_empty_device_lists_give_no_devices() -> None:
    assert ViewModelParser().parse(_document([{"Devices": []}])) == []


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{not json", "not valid JSON"),
        (json.dumps({"viewModel": {}}), "viewModel.Scene"),
        (json.dumps([1, 2]), "'viewModel'"),
        (json.dumps({"viewModel": {"Scene": {"Sections": {}}}}), "is not a list"),
        (_document([{"Name": "x"}, "text"]), "has a 'Devices' list"),
        (_document([{"Devices": [{"Name": "x"}]}]), "no 'DeviceName'"),
        (_document([{"Devices": [{"DeviceName": "  "}]}]), "no 'DeviceName'"),
        (_document([{"Devices": ["8615620 77678271"]}]), "no 'DeviceName'"),
    ],
)
def test_changed_structure_raises_a_clear_error(raw: str, message: str) -> None:
    with pytest.raises(ViewModelError, match=message):
        ViewModelParser().parse(raw)


def test_device_without_sensor_serial_has_no_sensor_id() -> None:
    assert PortalDevice("Weather station Mikulov").sensor_id is None
    assert str(PortalDevice("8615620 77678271")) == "8615620 77678271"


def test_empty_device_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        PortalDevice(" ")
