"""Tests of AlignedPanel validation, AlignmentConfig and ClassRegistry. All data are synthetic."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.alignment import AlignedPanel, AlignedValues, AlignmentConfig
from sivin.alignment.registry import ClassRegistry
from sivin.core.ids import SensorId

T0 = pd.Timestamp("2026-06-01T00:00:00Z")
S1, S2 = SensorId("11111111"), SensorId("22222222")


def times(n_points: int) -> pd.DatetimeIndex:
    return pd.date_range(T0, periods=n_points, freq="30min").as_unit("ns")


def values(*grid_values: float, offsets: bool = True) -> AlignedValues:
    data = np.array(grid_values, dtype=np.float64)
    offset_s = np.zeros_like(data) if offsets else None
    return AlignedValues(data, ~np.isnan(data), offset_s)


def test_panel_accessors_return_copies() -> None:
    panel = AlignedPanel(times(2), [S1], "test", {"temp_c": {S1: values(1.0, 2.0)}})

    temp = panel.variable("temp_c")
    temp.iloc[0, 0] = 99.0
    valid = panel.validity("temp_c")
    valid.iloc[0, 0] = False

    assert panel.variable("temp_c")["11111111"].tolist() == [1.0, 2.0]
    assert panel.validity("temp_c")["11111111"].tolist() == [True, True]
    assert panel.times[0] == T0
    assert "points=2" in repr(panel)


def test_panel_without_variables() -> None:
    panel = AlignedPanel(times(1), [S1], "test", {})

    assert panel.variables == ()
    assert not panel.is_empty


def test_panel_unknown_variable() -> None:
    panel = AlignedPanel(times(1), [S1], "test", {"temp_c": {S1: values(1.0)}})

    for accessor in (
        panel.variable,
        panel.validity,
        panel.offsets_s,
        panel.complete_rows,
        panel.pairwise_differences,
    ):
        with pytest.raises(KeyError, match="'rh_pct' is not in the panel"):
            accessor("rh_pct")


def test_panel_offsets_only_if_every_sensor_has_them() -> None:
    panel = AlignedPanel(
        times(1),
        [S1, S2],
        "test",
        {"temp_c": {S1: values(1.0), S2: values(2.0, offsets=False)}},
    )

    assert panel.offsets_s("temp_c") is None


def test_panel_rejects_no_sensors() -> None:
    with pytest.raises(ValueError, match="at least one sensor"):
        AlignedPanel(times(1), [], "test", {})


def test_panel_rejects_duplicate_sensors() -> None:
    with pytest.raises(ValueError, match="unique"):
        AlignedPanel(times(1), [S1, S1], "test", {})


def test_panel_rejects_non_utc_times() -> None:
    with pytest.raises(ValueError, match="Grid times"):
        AlignedPanel(pd.date_range("2026-06-01", periods=1), [S1], "test", {})


def test_panel_rejects_missing_or_extra_sensors() -> None:
    with pytest.raises(ValueError, match=r"missing sensors \['22222222'\], extra \[\]"):
        AlignedPanel(times(1), [S1, S2], "test", {"temp_c": {S1: values(1.0)}})
    with pytest.raises(ValueError, match=r"extra \['22222222'\]"):
        AlignedPanel(times(1), [S1], "test", {"temp_c": {S1: values(1.0), S2: values(1.0)}})


def test_panel_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="1 values for 2 grid points"):
        AlignedPanel(times(2), [S1], "test", {"temp_c": {S1: values(1.0)}})


def test_config_defaults() -> None:
    config = AlignmentConfig()

    assert config.strategy == "nearest_within_tolerance"
    assert config.params == {}
    assert config.grid_step_s == 1800.0
    assert config.span == "union"
    for field in AlignmentConfig.model_fields.values():
        assert field.description


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"strategy": "cubic"}, "unknown strategy 'cubic'"),
        ({"span": "intersection"}, "unknown span rule 'intersection'"),
        ({"params": {"tolerance_s": -1.0}}, "params.tolerance_s"),
        ({"strategy": "linear_interpolation", "params": {"tolerance_s": 60}}, "params.tolerance_s"),
        ({"grid_step_s": 0}, "grid_step_s"),
        ({"step_s": 1800}, "step_s"),
    ],
)
def test_config_rejects_invalid_values(raw: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AlignmentConfig.model_validate(raw)


def test_config_params_are_read_only_and_serialisable() -> None:
    config = AlignmentConfig(params={"tolerance_s": 600.0})

    with pytest.raises(TypeError):
        config.params["tolerance_s"] = 1.0  # type: ignore[index]
    assert config.model_dump()["params"] == {"tolerance_s": 600.0}
    assert '"params":{"tolerance_s":600.0}' in config.model_dump_json()
    assert AlignmentConfig.model_validate(config.model_dump()) == config


def test_config_rejects_step_that_is_not_whole_nanoseconds() -> None:
    with pytest.raises(ValidationError, match="whole number of nanoseconds"):
        AlignmentConfig(grid_step_s=1.0000000001)


def test_config_is_frozen() -> None:
    config = AlignmentConfig()

    with pytest.raises(ValidationError):
        config.span = "overlap"  # type: ignore[misc]


class _Base(ABC):
    key: ClassVar[str]

    @abstractmethod
    def run(self) -> int: ...


def _registry() -> ClassRegistry[_Base]:
    return ClassRegistry[_Base](_Base, "key", "test item")


def test_registry_registers_and_looks_up() -> None:
    registry = _registry()

    @registry.register
    class One(_Base):
        key: ClassVar[str] = "one"

        def run(self) -> int:
            return 1

    assert registry.get("one") is One
    assert "one" in registry
    assert len(registry) == 1
    assert registry.ids() == ("one",)


def test_registry_rejects_invalid_classes() -> None:
    registry = _registry()

    class Abstract(_Base):
        key: ClassVar[str] = "abstract"

    class NoKey(_Base):
        def run(self) -> int:
            return 0

    class Good(_Base):
        key: ClassVar[str] = "good"

        def run(self) -> int:
            return 0

    class Again(Good):
        pass

    with pytest.raises(TypeError, match="Only _Base subclasses"):
        registry.register(int)
    with pytest.raises(TypeError, match="abstract"):
        registry.register(Abstract)
    with pytest.raises(TypeError, match="non-empty class variable 'key'"):
        registry.register(NoKey)
    registry.register(Good)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Again)


def test_registry_unknown_key() -> None:
    with pytest.raises(KeyError, match="Unknown test item 'x'; registered: none"):
        _registry().get("x")
