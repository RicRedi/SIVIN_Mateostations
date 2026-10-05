"""Tests of the check extension point and of the event value objects. SYNTHETIC data only."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import Field, ValidationError
from tests.quality.synthetic import flat_trace

from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.checks import (
    CheckOutcome,
    CheckRegistry,
    CheckSettings,
    QualityCheck,
    RangeCheck,
    RangeSettings,
    SpikeSettings,
    check_registry,
)
from sivin.quality.events import (
    DeploymentEvent,
    EventKind,
    EventSource,
    QualityEvent,
    Severity,
)
from sivin.quality.samples import SampleArrays, Variable

T0 = pd.Timestamp("2026-04-01T00:00:00Z")


class _DemoSettings(CheckSettings):
    limit_c: float = Field(1.0, description="Demo limit in °C (test only).")


class _DemoCheck(QualityCheck[_DemoSettings]):
    check_id = "demo"
    settings_model = _DemoSettings

    def check(self, series: MeasurementSeries) -> CheckOutcome:
        samples = SampleArrays.of(series)
        return CheckOutcome.from_mask(samples.temp_c > self.settings.limit_c, QcFlag.STEP)


class TestRegistry:
    def test_builtin_checks_are_registered(self) -> None:
        expected = (
            "battery",
            "missing",
            "persistence",
            "precip_counter",
            "precip_range",
            "range",
            "sampling",
            "spike",
            "step",
        )
        assert check_registry.ids() == expected
        assert "range" in check_registry
        assert len(check_registry) == len(expected)

    def test_create_validates_settings(self) -> None:
        check = check_registry.create("range", {"temp_climate_max_c": 35.0})
        assert isinstance(check, RangeCheck)
        assert check.settings.temp_climate_max_c == 35.0
        with pytest.raises(ValidationError):
            check_registry.create("range", {"unknown_key": 1})

    def test_unknown_check(self) -> None:
        with pytest.raises(KeyError, match="Unknown quality check 'nope'"):
            check_registry.get("nope")
        with pytest.raises(KeyError, match="none"):
            CheckRegistry().get("nope")

    def test_register_and_use_a_new_check(self) -> None:
        registry = CheckRegistry()
        assert registry.register(_DemoCheck) is _DemoCheck
        check = registry.create("demo", {"limit_c": 2.0})
        outcome = check.check(flat_trace([1.0, 3.0]).series())
        assert outcome.flags.tolist() == [0, int(QcFlag.STEP)]
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_DemoCheck)

    def test_register_rejects_invalid_classes(self) -> None:
        registry = CheckRegistry()

        class NoId(_DemoCheck):
            check_id = ""

        class NoModel(_DemoCheck):
            settings_model = dict  # type: ignore[assignment]

        class Abstract(QualityCheck[_DemoSettings]):
            check_id = "abstract"
            settings_model = _DemoSettings

        with pytest.raises(TypeError, match="Only QualityCheck"):
            registry.register(int)  # type: ignore[type-var]
        with pytest.raises(TypeError, match="check_id"):
            registry.register(NoId)
        with pytest.raises(TypeError, match="settings_model"):
            registry.register(NoModel)
        with pytest.raises(TypeError, match="abstract"):
            registry.register(Abstract)

    def test_wrong_settings_type(self) -> None:
        with pytest.raises(TypeError, match="expects RangeSettings"):
            RangeCheck(SpikeSettings())  # type: ignore[arg-type]
        assert "RangeCheck(" in repr(RangeCheck(RangeSettings()))


class TestCheckOutcome:
    def test_flags_are_read_only_and_events_sorted(self) -> None:
        late = QualityEvent(EventKind.GAP, T0 + pd.Timedelta(hours=2), "late")
        early = QualityEvent(EventKind.GAP, T0, "early")
        outcome = CheckOutcome(np.array([0, 4]), (late, early))
        assert outcome.events == (early, late)
        assert outcome.flags.dtype == np.int32
        with pytest.raises(ValueError, match="read-only"):
            outcome.flags[0] = 1
        assert outcome.count(QcFlag.SPIKE) == 1

    @pytest.mark.parametrize("flags", [np.array([[0]]), np.array([1024]), np.array([-1])])
    def test_invalid_flags(self, flags: np.ndarray) -> None:
        with pytest.raises(ValueError, match="flags"):
            CheckOutcome(flags)


class TestEvents:
    def test_quality_event_normalises_to_utc(self) -> None:
        event = QualityEvent(
            EventKind.GAP,
            pd.Timestamp("2026-04-01T02:00:00+02:00"),
            "gap",
            end_utc=pd.Timestamp("2026-04-01T01:00:00Z"),
        )
        assert event.t_utc == T0
        assert str(event.t_utc.tz) == "UTC"
        assert event.severity is Severity.INFO
        assert event.source is EventSource.DETECTED

    def test_quality_event_validation(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            QualityEvent(EventKind.GAP, pd.Timestamp("2026-04-01"), "naive")
        with pytest.raises(ValueError, match="precedes"):
            QualityEvent(EventKind.GAP, T0, "x", end_utc=T0 - pd.Timedelta(seconds=1))
        with pytest.raises(ValueError, match="confidence"):
            QualityEvent(EventKind.GAP, T0, "x", confidence=1.5)

    def test_deployment_event(self) -> None:
        event = DeploymentEvent(EventKind.RETRIEVAL, T0, "back to office", confidence=0.8)
        assert event.type is EventKind.RETRIEVAL
        with pytest.raises(ValueError, match="cannot have kind"):
            DeploymentEvent(EventKind.GAP, T0, "x", confidence=0.5)
        with pytest.raises(ValueError, match="needs a confidence"):
            DeploymentEvent(EventKind.DEPLOYMENT, T0, "x")


class TestSamples:
    def test_arrays_are_read_only_views_of_the_series(self) -> None:
        trace = flat_trace([1.0, 2.0])
        samples = SampleArrays.of(trace.series())
        assert len(samples) == 2
        assert samples.t_s[1] - samples.t_s[0] == pytest.approx(1825.0)
        assert samples.values(Variable.RH).tolist() == [60.0, 60.0]
        assert samples.timestamp(0) == T0
        assert Variable.TEMP.unit == "°C"
        with pytest.raises(ValueError, match="read-only"):
            samples.temp_c[0] = 5.0
