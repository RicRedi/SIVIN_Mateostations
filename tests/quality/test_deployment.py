"""Acceptance tests of deployment detection (MIGRATION_PLAN §4 WP-1.5). SYNTHETIC data only."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from tests.quality.synthetic import OFFICES, SENSOR, SyntheticSensor, Trace, Weather

from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.boundaries import TransportSettings
from sivin.quality.deployment import DeploymentDetector, DeploymentResult, DeploymentSettings
from sivin.quality.events import DeploymentEvent, EventKind, EventSource, QualityEvent, Severity
from sivin.quality.timeline import IndoorInterval, KnownDeploymentReconciler, indoor_mask

SEEDS = range(6)
SEASON_STARTS = ("2026-01-05", "2026-04-01", "2026-07-01", "2026-10-01")
HOUR = pd.Timedelta(hours=1)
DAY = pd.Timedelta(days=1)


def _sensor(seed: int, start: str = "2026-04-01") -> SyntheticSensor:
    return SyntheticSensor(seed, pd.Timestamp(start, tz="UTC"))


def _position(trace: Trace, event: QualityEvent) -> int:
    """Row position of the sample at the event time."""
    return int(np.flatnonzero(trace.t_s >= event.t_utc.value / 1e9 - 1e-3)[0])


def _kinds(result: DeploymentResult) -> list[EventKind]:
    return [event.kind for event in result.transitions]


def _assert_transitions(
    trace: Trace, result: DeploymentResult, kinds: list[EventKind], truth: list[int]
) -> None:
    assert _kinds(result) == kinds
    for event, boundary in zip(result.transitions, truth, strict=True):
        assert abs(_position(trace, event) - boundary) <= 1


class TestOfficeThenVineyard:
    @pytest.mark.parametrize("seed", SEEDS)
    @pytest.mark.parametrize("start", SEASON_STARTS)
    def test_deployment_found_within_one_sample(self, seed: int, start: str) -> None:
        trace = _sensor(seed, start).trace([("indoor", 3), ("outdoor", 10)])
        result = DeploymentDetector().detect(trace.series())
        _assert_transitions(trace, result, [EventKind.DEPLOYMENT], list(trace.boundaries))
        deployment = result.transitions[0]
        assert deployment.source is EventSource.DETECTED
        assert deployment.confidence is not None
        assert deployment.confidence >= 0.5
        indoor = np.flatnonzero(result.pre_deployment)
        assert indoor.tolist() == list(range(_position(trace, deployment)))
        assert result.warnings == ()

    @pytest.mark.parametrize(
        ("office", "start"),
        [
            ("unheated", "2026-01-05"),
            ("cool", "2026-03-15"),
            ("warm", "2026-07-01"),
            ("hot", "2026-07-15"),
            ("humid", "2026-06-01"),
        ],
    )
    @pytest.mark.parametrize("seed", range(4))
    def test_office_variants(self, office: str, start: str, seed: int) -> None:
        # 12 °C and 30 °C rooms lie outside a comfort band; the relative contrast finds them.
        trace = _sensor(seed, start).trace([("indoor", 3, OFFICES[office]), ("outdoor", 12)])
        result = DeploymentDetector().detect(trace.series())
        _assert_transitions(trace, result, [EventKind.DEPLOYMENT], list(trace.boundaries))

    @pytest.mark.parametrize("start", ["2026-01-05", "2026-07-01"])
    @pytest.mark.parametrize("seed", range(4))
    def test_overcast_deployment(self, start: str, seed: int) -> None:
        trace = _sensor(seed, start).trace(
            [("indoor", 3), ("outdoor", 12, Weather(cloudiness=1.0))]
        )
        result = DeploymentDetector().detect(trace.series())
        _assert_transitions(trace, result, [EventKind.DEPLOYMENT], list(trace.boundaries))

    @pytest.mark.parametrize("seed", range(4))
    def test_car_transport_counts_as_pre_deployment_when_enabled(self, seed: int) -> None:
        trace = _sensor(seed).trace([("indoor", 3), ("car", 1.5 / 24, 35.0), ("outdoor", 12)])
        settings = DeploymentSettings(transport=TransportSettings(enabled=True))
        result = DeploymentDetector(settings).detect(trace.series())
        arrival = trace.boundaries[1]
        _assert_transitions(trace, result, [EventKind.DEPLOYMENT], [arrival])
        assert result.pre_deployment[trace.boundaries[0] : arrival].all()

    @pytest.mark.parametrize("seed", range(4))
    def test_car_transport_stays_outdoor_by_default(self, seed: int) -> None:
        # Trimming is off by default: no vineyard sample is lost, the car rows may stay outdoor.
        trace = _sensor(seed).trace([("indoor", 3), ("car", 1.5 / 24, 35.0), ("outdoor", 12)])
        result = DeploymentDetector().detect(trace.series())
        assert _kinds(result) == [EventKind.DEPLOYMENT]
        deployed = _position(trace, result.transitions[0])
        assert trace.boundaries[0] - 1 <= deployed <= trace.boundaries[1]
        assert not result.pre_deployment[trace.boundaries[1] :].any()

    def test_event_detail_comes_from_local_windows(self) -> None:
        trace = _sensor(1).trace([("indoor", 3), ("outdoor", 10)])
        result = DeploymentDetector().detect(trace.series())
        detail = result.transitions[0].detail
        assert detail.startswith("indoor → outdoor: level ")
        assert "daily spread x" in detail
        assert "votes " in detail
        outcome = result.outcome()
        assert outcome.count(QcFlag.PRE_DEPLOYMENT) == int(result.pre_deployment.sum())
        assert result.deployed_ranges() == ((int(result.pre_deployment.sum()), len(trace)),)


class TestGapsAtTheBoundary:
    @pytest.mark.parametrize(("before_h", "after_h"), [(12, 12), (48, 0), (0, 48)])
    def test_deployment_after_a_gap(self, before_h: int, after_h: int) -> None:
        trace = _sensor(0).trace([("indoor", 3), ("outdoor", 12)])
        boundary_s = trace.t_s[trace.boundaries[0]]
        start = int(np.searchsorted(trace.t_s, boundary_s - before_h * 3600))
        stop = int(np.searchsorted(trace.t_s, boundary_s + after_h * 3600))
        gapped = trace.without_rows(start, stop)
        result = DeploymentDetector().detect(gapped.series())
        _assert_transitions(gapped, result, [EventKind.DEPLOYMENT], [start])


class TestNoTransition:
    @pytest.mark.parametrize("seed", SEEDS)
    @pytest.mark.parametrize("start", SEASON_STARTS)
    def test_sixty_outdoor_days_raise_no_false_alarm(self, seed: int, start: str) -> None:
        trace = _sensor(seed, start).trace([("outdoor", 60)])
        result = DeploymentDetector().detect(trace.series())
        assert result.events == ()
        assert not result.pre_deployment.any()

    def test_cloudy_summer_false_alarm_rate(self) -> None:
        # 20 seeds x (changing, overcast) x 92 summer days = 10.1 sensor-years.
        n_false = 0
        for seed in range(20):
            for weather in (Weather(), Weather(cloudiness=1.0)):
                trace = _sensor(seed, "2026-06-01").trace([("outdoor", 92, weather)])
                result = DeploymentDetector().detect(trace.series())
                n_false += len(result.transitions)
                assert not result.pre_deployment.any()
        assert n_false / (40 * 92 / 365) <= 0.1

    @pytest.mark.parametrize("seed", range(3))
    def test_year_with_fog_heat_wave_and_fronts(self, seed: int) -> None:
        weather = Weather(
            fog=((5, 9, 0.0), (290, 292, 8.0), (320, 325, 3.0)),
            heat_waves=((190, 200, 6.0),),
            fronts=((150, -8.0, 2.0), (210, -10.0, 1.0), (240, -7.0, 0.5)),
        )
        trace = _sensor(seed, "2026-01-01").trace([("outdoor", 365, weather)])
        result = DeploymentDetector().detect(trace.series())
        assert result.transitions == ()
        assert not result.pre_deployment.any()

    @pytest.mark.parametrize("seed", range(4))
    def test_cold_front_is_not_a_transition(self, seed: int) -> None:
        trace = _sensor(seed).trace([("outdoor", 10)]).with_ramp(240, -8.0, 7200.0)
        assert DeploymentDetector().detect(trace.series()).events == ()

    def test_sensor_still_in_the_office_is_not_flagged(self) -> None:
        # No outdoor data to contrast with: nothing is decided, nothing is excluded.
        trace = _sensor(2).trace([("indoor", 4)])
        result = DeploymentDetector().detect(trace.series())
        assert result.events == ()
        assert not result.pre_deployment.any()

    def test_empty_series(self) -> None:
        result = DeploymentDetector().detect(MeasurementSeries.empty(SENSOR))
        assert result.events == ()
        assert result.segments == ()
        assert result.pre_deployment.shape == (0,)


class TestService:
    @pytest.mark.parametrize("seed", SEEDS)
    @pytest.mark.parametrize("start", SEASON_STARTS)
    def test_retrieval_and_redeployment(self, seed: int, start: str) -> None:
        trace = _sensor(seed, start).trace([("outdoor", 10), ("indoor", 3), ("outdoor", 10)])
        result = DeploymentDetector().detect(trace.series())
        _assert_transitions(
            trace, result, [EventKind.RETRIEVAL, EventKind.DEPLOYMENT], list(trace.boundaries)
        )
        retrieved, redeployed = (_position(trace, e) for e in result.transitions)
        assert np.flatnonzero(result.pre_deployment).tolist() == list(range(retrieved, redeployed))
        assert result.deployed_ranges() == ((0, retrieved), (redeployed, len(trace)))

    def test_retrieval_without_redeployment_only_warns(self) -> None:
        trace = _sensor(5).trace([("indoor", 2), ("outdoor", 8), ("indoor", 3)])
        result = DeploymentDetector().detect(trace.series())
        assert _kinds(result) == [EventKind.DEPLOYMENT]
        (warning,) = result.warnings
        assert warning.kind is EventKind.UNCONFIRMED_TRANSITION
        assert "retrieval without a later redeployment" in warning.detail
        assert abs(_position(trace, warning) - trace.boundaries[1]) <= 1
        assert not result.pre_deployment[trace.boundaries[0] :].any()


class TestLongSeries:
    def test_service_found_identically_in_one_three_and_five_years(self) -> None:
        trace = _sensor(4, "2026-03-01").trace(
            [("indoor", 3), ("outdoor", 5 * 365 - 200), ("indoor", 3), ("outdoor", 197)]
        )
        end_s = trace.t_s[-1]
        results = {}
        for years in (1, 3, 5):
            start = int(np.searchsorted(trace.t_s, end_s - years * 365 * 86_400.0))
            part = trace.since(start)
            result = DeploymentDetector().detect(part.series())
            results[years] = [
                (e.kind, e.t_utc, e.confidence, e.detail)
                for e in result.transitions
                if e.t_utc >= trace.timestamp(trace.boundaries[1]) - DAY
            ]
            assert int(result.pre_deployment[part.boundaries[-2] : part.boundaries[-1]].sum()) > 0
        assert [k for k, *_ in results[5]] == [EventKind.RETRIEVAL, EventKind.DEPLOYMENT]
        assert results[1] == results[3] == results[5]


class TestKnownDeployments:
    def _trace(self) -> Trace:
        return _sensor(3).trace([("indoor", 3), ("outdoor", 10)])

    def _first_outdoor(self, trace: Trace, t_utc: pd.Timestamp) -> int:
        return int(np.searchsorted(trace.t_s, t_utc.value / 1e9))

    def test_known_time_within_tolerance_overrides_detection(self) -> None:
        trace = self._trace()
        known = (trace.timestamp(trace.boundaries[0]) + 2 * HOUR).floor("s")
        result = DeploymentDetector().detect(trace.series(), [known.to_pydatetime()])
        (deployment,) = result.transitions
        assert (deployment.t_utc, deployment.source, deployment.confidence) == (
            known,
            EventSource.REGISTRY,
            1.0,
        )
        assert "detected -2.00 h from it" in deployment.detail
        first_outdoor = self._first_outdoor(trace, known)
        assert np.flatnonzero(result.pre_deployment).tolist() == list(range(first_outdoor))
        # Registry is ground truth, but excluding data classified as outdoor is warned about.
        (warning,) = result.warnings
        assert warning.kind is EventKind.DEPLOYMENT_MISMATCH
        assert warning.t_utc == known
        assert "2.00 h of data classified as outdoor become PRE_DEPLOYMENT" in warning.detail

    def test_known_time_earlier_than_detection_does_not_warn(self) -> None:
        trace = self._trace()
        known = trace.timestamp(trace.boundaries[0]) - 2 * HOUR
        result = DeploymentDetector().detect(trace.series(), [known])
        assert result.warnings == ()
        assert [t.t_utc for t in result.transitions] == [known]

    def test_mismatch_beyond_tolerance_warns_and_keeps_detection(self) -> None:
        trace = self._trace()
        known = trace.timestamp(trace.boundaries[0]) + 48 * HOUR
        result = DeploymentDetector().detect(trace.series(), [known])
        assert len(result.warnings) == 2
        assert all(w.kind is EventKind.DEPLOYMENT_MISMATCH for w in result.warnings)
        assert [(t.source, t.t_utc == known) for t in result.transitions] == [
            (EventSource.DETECTED, False),
            (EventSource.REGISTRY, True),
        ]
        # Only the detected office stay is flagged, not the 48 h up to the known time.
        detected = _position(trace, result.transitions[0])
        assert abs(detected - trace.boundaries[0]) <= 1
        assert np.flatnonzero(result.pre_deployment).tolist() == list(range(detected))

    def test_known_time_inside_the_office_stay_ends_it(self) -> None:
        trace = self._trace()
        known = trace.timestamp(trace.boundaries[0]) - 30 * HOUR
        result = DeploymentDetector().detect(trace.series(), [known])
        assert [t.source for t in result.transitions] == [EventSource.REGISTRY]
        assert result.transitions[0].t_utc == known
        assert any("data from the known deployment on" in w.detail for w in result.warnings)
        assert not result.pre_deployment[self._first_outdoor(trace, known) :].any()

    def test_service_missing_in_the_registry_is_applied_with_a_warning(self) -> None:
        trace = _sensor(2).trace([("indoor", 3), ("outdoor", 12), ("indoor", 3), ("outdoor", 12)])
        known = trace.timestamp(trace.boundaries[0])
        result = DeploymentDetector().detect(trace.series(), [known])
        assert _kinds(result) == [EventKind.DEPLOYMENT, EventKind.RETRIEVAL, EventKind.DEPLOYMENT]
        assert [t.source for t in result.transitions] == [
            EventSource.REGISTRY,
            EventSource.DETECTED,
            EventSource.DETECTED,
        ]
        (warning,) = result.warnings
        assert "detected service visit applied" in warning.detail
        assert not result.pre_deployment[trace.boundaries[2] + 1 :].any()
        assert result.pre_deployment[trace.boundaries[1] + 1 : trace.boundaries[2] - 1].all()

    def test_known_relocation_raises_no_warning(self) -> None:
        trace = _sensor(6).trace(
            [("indoor", 3), ("outdoor", 12), ("car", 1 / 24, 30.0), ("outdoor", 12)]
        )
        known = [trace.timestamp(trace.boundaries[0]), trace.timestamp(trace.boundaries[2])]
        result = DeploymentDetector().detect(trace.series(), known)
        assert result.warnings == ()
        assert [t.t_utc for t in result.transitions] == known
        assert "known relocation" in result.transitions[1].detail
        assert not result.pre_deployment[trace.boundaries[0] :].any()

    def test_only_a_later_relocation_known(self) -> None:
        trace = _sensor(1).trace([("indoor", 3), ("outdoor", 30)])
        known = trace.timestamp(trace.boundaries[0]) + 20 * DAY
        result = DeploymentDetector().detect(trace.series(), [known])
        assert not result.pre_deployment[trace.boundaries[0] + 1 :].any()
        assert result.pre_deployment[: trace.boundaries[0] - 1].all()
        assert len(result.warnings) == 2

    def test_known_deployment_before_the_data(self) -> None:
        trace = _sensor(4).trace([("outdoor", 5)])
        known = trace.timestamp(0) - DAY
        result = DeploymentDetector().detect(trace.series(), [known])
        assert not result.pre_deployment.any()
        assert [(e.kind, e.severity) for e in result.events] == [
            (EventKind.DEPLOYMENT, Severity.INFO)
        ]

    def test_known_time_inside_a_detected_service_visit(self) -> None:
        trace = _sensor(2).trace([("indoor", 3), ("outdoor", 12), ("indoor", 3), ("outdoor", 12)])
        known = [
            trace.timestamp(trace.boundaries[0]),
            trace.timestamp(trace.boundaries[1]) + 30 * HOUR,
        ]
        result = DeploymentDetector().detect(trace.series(), known)
        assert any("inside a detected service visit" in w.detail for w in result.warnings)
        assert result.pre_deployment[trace.boundaries[1] + 1 : trace.boundaries[2] - 1].all()

    def test_tolerance_is_configurable(self) -> None:
        trace = self._trace()
        known = trace.timestamp(trace.boundaries[0]) + 2 * HOUR
        strict = DeploymentDetector(DeploymentSettings(known_tolerance_s=3600.0))
        assert strict.settings.known_tolerance_s == 3600.0
        kinds = [e.kind for e in strict.detect(trace.series(), [known]).events]
        assert EventKind.DEPLOYMENT_MISMATCH in kinds

    def test_ignore_mask_must_be_qc_flags(self) -> None:
        with pytest.raises(ValidationError, match="not QcFlag values"):
            DeploymentSettings(ignore_mask=1024)
        assert DeploymentSettings(ignore_mask=int(QcFlag.MISSING)).ignore_mask == 1

    def test_naive_known_time_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            DeploymentDetector().detect(self._trace().series(), [pd.Timestamp("2026-04-04")])


class TestRobustness:
    def test_temperature_only(self) -> None:
        trace = _sensor(6).trace([("indoor", 3), ("outdoor", 10)])
        trace = trace.with_missing(range(len(trace)), rh_only=True)
        result = DeploymentDetector().detect(trace.series())
        _assert_transitions(trace, result, [EventKind.DEPLOYMENT], list(trace.boundaries))
        assert result.segments[0].assessment.features.rh_median_pct is None

    def test_flagged_gross_error_is_ignored(self) -> None:
        trace = _sensor(7).trace([("outdoor", 6)]).with_spike(150, delta_c=-500.0)
        qc = np.zeros(len(trace), dtype=np.int32)
        qc[150] = int(QcFlag.OUT_OF_RANGE)
        result = DeploymentDetector().detect(trace.series().with_flags(qc))
        assert result.events == ()

    def test_missing_rows_take_the_state_of_their_time(self) -> None:
        trace = _sensor(8).trace([("indoor", 3), ("outdoor", 10)])
        boundary = trace.boundaries[0]
        trace = trace.with_missing([boundary - 2, boundary + 2])
        result = DeploymentDetector().detect(trace.series())
        assert result.pre_deployment[boundary - 2]
        assert not result.pre_deployment[boundary + 2]


class TestTimeline:
    T0 = pd.Timestamp("2026-04-01T00:00:00Z")

    def _event(self, kind: EventKind, hours: float) -> DeploymentEvent:
        return DeploymentEvent(kind, self.T0 + hours * HOUR, "detected", confidence=0.9)

    def test_indoor_mask(self) -> None:
        t_ns = (self.T0 + pd.to_timedelta(np.arange(8), unit="h")).as_unit("ns").asi8
        office = IndoorInterval(
            None, self.T0 + 2 * HOUR, None, self._event(EventKind.DEPLOYMENT, 2)
        )
        service = IndoorInterval(
            self.T0 + 4 * HOUR,
            self.T0 + 6 * HOUR,
            self._event(EventKind.RETRIEVAL, 4),
            self._event(EventKind.DEPLOYMENT, 6),
        )
        mask = indoor_mask([office, service], t_ns)
        assert mask.tolist() == [True, True, False, False, True, True, False, False]
        assert service.contains(self.T0 + 5 * HOUR)
        assert not service.contains(self.T0 + 6 * HOUR)
        assert len(service.events) == 2

    def test_reconcile_without_known_times_keeps_detection(self) -> None:
        office = IndoorInterval(None, self.T0 + HOUR, None, self._event(EventKind.DEPLOYMENT, 1))
        result = KnownDeploymentReconciler(3600.0).reconcile([office], [], self.T0)
        assert result.intervals == (office,)
        assert result.transitions == (office.deployment,)
        assert result.warnings == ()
