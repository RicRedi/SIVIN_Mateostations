"""Tests of the quality-control pipeline and of the synthetic generator. SYNTHETIC data only."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from tests.quality.synthetic import SENSOR, SyntheticSensor, flat_trace

from sivin.core.flags import QcFlag
from sivin.core.schema import Column, MeasurementSeries
from sivin.quality import (
    EventKind,
    QualityPipeline,
    QualityPipelineSettings,
)
from sivin.quality.checks import RangeCheck, SpikeCheck


def _flags(series: MeasurementSeries) -> np.ndarray:
    return series.frame[Column.QC].to_numpy()


def _rows_with(series: MeasurementSeries, flag: QcFlag) -> list[int]:
    return [int(i) for i in np.flatnonzero(_flags(series) & int(flag))]


@pytest.fixture
def pipeline() -> QualityPipeline:
    return QualityPipeline.from_settings(QualityPipelineSettings())


class TestPipeline:
    def test_deployment_jump_is_not_a_spike_or_step(self, pipeline: QualityPipeline) -> None:
        trace = SyntheticSensor(1).trace([("indoor", 3), ("outdoor", 10)])
        result = pipeline.run(trace.series())
        boundary = trace.boundaries[0]
        assert _rows_with(result.series, QcFlag.PRE_DEPLOYMENT) == list(range(boundary))
        assert result.flag_counts[QcFlag.SPIKE] == 0
        assert result.flag_counts[QcFlag.STEP] == 0
        assert result.flag_counts[QcFlag.PRE_DEPLOYMENT] == boundary
        assert [e.kind for e in result.events] == [EventKind.DEPLOYMENT]
        assert result.deployment is not None

    def test_outdoor_anomalies_are_flagged_indoor_ones_are_not(
        self, pipeline: QualityPipeline
    ) -> None:
        trace = (
            SyntheticSensor(2)
            .trace([("indoor", 3), ("outdoor", 10)])
            .with_stuck(20, 50)  # indoor, 30 samples ≈ 15 h: not checked
            .with_spike(300, delta_c=9.0)
            .with_stuck(400, 430)  # outdoor: stuck
            .with_step(600, 7.0)
        )
        result = pipeline.run(trace.series())
        assert _rows_with(result.series, QcFlag.SPIKE) == [300]
        assert _rows_with(result.series, QcFlag.STUCK) == list(range(400, 430))
        assert 600 in _rows_with(result.series, QcFlag.STEP)
        step_events = [e for e in result.events if e.kind is EventKind.STEP]
        assert trace.timestamp(600) in [e.t_utc for e in step_events]

    def test_screening_runs_on_the_whole_series(self, pipeline: QualityPipeline) -> None:
        trace = (
            SyntheticSensor(3)
            .trace([("indoor", 3), ("outdoor", 10)])
            .with_missing([5, 400])
            .with_spike(10, delta_pct=70.0)  # indoor RH > 100 %
        )
        result = pipeline.run(trace.series())
        assert _rows_with(result.series, QcFlag.MISSING) == [5, 400]
        assert _rows_with(result.series, QcFlag.OUT_OF_RANGE) == [10]

    def test_events_are_sorted_and_existing_flags_kept(self, pipeline: QualityPipeline) -> None:
        trace = SyntheticSensor(4).trace([("indoor", 3), ("outdoor", 10)]).without_rows(300, 310)
        manual = np.zeros(len(trace), dtype=np.int32)
        manual[-1] = int(QcFlag.MANUAL_EXCLUDE)
        result = pipeline.run(trace.series().with_flags(manual))
        assert [e.kind for e in result.events] == [EventKind.DEPLOYMENT, EventKind.GAP]
        assert result.flag_counts[QcFlag.MANUAL_EXCLUDE] == 1

    def test_known_deployment_is_passed_to_the_detector(self, pipeline: QualityPipeline) -> None:
        trace = SyntheticSensor(5).trace([("indoor", 3), ("outdoor", 10)])
        known = trace.timestamp(trace.boundaries[0])
        result = pipeline.run(trace.series(), known_deployments=[known])
        assert [e.source.value for e in result.events] == ["registry"]

    def test_without_deployment_detection(self) -> None:
        settings = QualityPipelineSettings(detect_deployment=False)
        trace = SyntheticSensor(6).trace([("indoor", 3), ("outdoor", 10)])
        result = QualityPipeline.from_settings(settings).run(trace.series())
        assert result.deployment is None
        assert result.flag_counts[QcFlag.PRE_DEPLOYMENT] == 0
        # Without the detector the office-to-field jump is checked like any outdoor data.
        assert result.flag_counts[QcFlag.STEP] >= 1

    def test_check_settings_reach_the_checks(self) -> None:
        settings = QualityPipelineSettings(
            check_settings={"range": {"temp_climate_max_c": 15.0, "temp_climate_min_c": 5.0}}
        )
        trace = flat_trace([4.0, 10.0, 16.0])
        result = QualityPipeline.from_settings(settings).run(trace.series())
        assert _rows_with(result.series, QcFlag.OUT_OF_RANGE) == [0, 2]

    def test_empty_series(self, pipeline: QualityPipeline) -> None:
        result = pipeline.run(MeasurementSeries.empty(SENSOR))
        assert result.events == ()
        assert all(count == 0 for count in result.flag_counts.values())

    def test_direct_construction(self) -> None:
        pipeline = QualityPipeline([RangeCheck()], [SpikeCheck()], detector=None)
        result = pipeline.run(flat_trace([10.0, 10.0, 50.0, 10.0, 10.0]).series())
        assert _rows_with(result.series, QcFlag.OUT_OF_RANGE) == [2]
        assert _rows_with(result.series, QcFlag.SPIKE) == [2]
        with pytest.raises(TypeError):
            result.flag_counts[QcFlag.SPIKE] = 0  # type: ignore[index]


class TestPipelineSettings:
    def test_unknown_check(self) -> None:
        with pytest.raises(ValidationError, match="unknown checks"):
            QualityPipelineSettings(screening_checks=("missing", "nope"))

    def test_duplicate_check(self) -> None:
        with pytest.raises(ValidationError, match="listed twice"):
            QualityPipelineSettings(deployed_checks=("spike", "spike"))

    def test_settings_for_disabled_check(self) -> None:
        with pytest.raises(ValidationError, match="not enabled"):
            QualityPipelineSettings(deployed_checks=(), check_settings={"spike": {}})

    def test_invalid_check_settings_fail_at_build(self) -> None:
        settings = QualityPipelineSettings(check_settings={"spike": {"bogus": 1}})
        with pytest.raises(ValidationError):
            QualityPipeline.from_settings(settings)

    def test_unknown_key(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            QualityPipelineSettings.model_validate({"checks": []})


class TestSyntheticGenerator:
    def test_seeded_and_deterministic(self) -> None:
        first = SyntheticSensor(11).trace([("outdoor", 2)])
        second = SyntheticSensor(11).trace([("outdoor", 2)])
        np.testing.assert_array_equal(first.temp_c, second.temp_c)
        np.testing.assert_array_equal(first.t_s, second.t_s)

    def test_plausible_shape(self) -> None:
        trace = SyntheticSensor(12).trace([("indoor", 3), ("outdoor", 30)])
        intervals = np.diff(trace.t_s)
        assert intervals.min() >= 1805.0
        assert intervals.max() <= 1845.0
        indoor = slice(0, trace.boundaries[0])
        outdoor = slice(trace.boundaries[0], None)
        assert 20.0 < np.median(trace.temp_c[indoor]) < 24.0
        assert 35.0 <= np.median(trace.rh_pct[indoor]) <= 45.0
        assert trace.rh_pct.min() >= 0.0
        assert trace.rh_pct.max() <= 100.0
        # Humidity falls when temperature rises outdoors.
        correlation = np.corrcoef(trace.temp_c[outdoor], trace.rh_pct[outdoor])[0, 1]
        assert correlation < -0.5
        series = trace.series()
        assert isinstance(series.timestamps.iloc[0], pd.Timestamp)
