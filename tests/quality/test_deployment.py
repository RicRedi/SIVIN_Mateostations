"""Acceptance tests of deployment detection (MIGRATION_PLAN §4 WP-1.5). SYNTHETIC data only."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from tests.quality.synthetic import SENSOR, SyntheticSensor, Trace

from sivin.core.flags import QcFlag
from sivin.core.schema import MeasurementSeries
from sivin.quality.deployment import DeploymentDetector, DeploymentResult, DeploymentSettings
from sivin.quality.events import DeploymentEvent, EventKind, EventSource, Severity
from sivin.quality.regime import Regime
from sivin.quality.timeline import DeploymentTimeline, KnownDeploymentReconciler

SEEDS = range(8)
SEASON_STARTS = ("2026-01-05", "2026-04-01", "2026-07-01", "2026-10-01")
HOUR = pd.Timedelta(hours=1)


def _position(trace: Trace, event: DeploymentEvent) -> int:
    """Row position of the sample at the event time."""
    return int(np.flatnonzero(trace.t_s >= event.t_utc.value / 1e9 - 1e-3)[0])


def _transitions(result: DeploymentResult) -> list[EventKind]:
    return [event.kind for event in result.transitions]


class TestOfficeThenVineyard:
    @pytest.mark.parametrize("seed", SEEDS)
    @pytest.mark.parametrize("start", SEASON_STARTS)
    def test_deployment_found_within_one_sample(self, seed: int, start: str) -> None:
        trace = SyntheticSensor(seed, pd.Timestamp(start, tz="UTC")).trace(
            [("indoor", 3), ("outdoor", 10)]
        )
        result = DeploymentDetector().detect(trace.series())
        (deployment,) = result.transitions
        assert deployment.kind is EventKind.DEPLOYMENT
        assert abs(_position(trace, deployment) - trace.boundaries[0]) <= 1
        assert deployment.source is EventSource.DETECTED
        assert deployment.confidence is not None
        assert deployment.confidence > 0.9
        # Every sample before the deployment, and none after it, is PRE_DEPLOYMENT.
        indoor = np.flatnonzero(result.pre_deployment)
        assert indoor.tolist() == list(range(_position(trace, deployment)))
        assert [s.regime for s in result.segments] == [Regime.INDOOR, Regime.OUTDOOR]

    def test_event_detail_and_flags(self) -> None:
        trace = SyntheticSensor(1).trace([("indoor", 3), ("outdoor", 10)])
        result = DeploymentDetector().detect(trace.series())
        assert result.transitions[0].detail.startswith("indoor → outdoor: step -")
        outcome = result.outcome()
        assert outcome.count(QcFlag.PRE_DEPLOYMENT) == int(result.pre_deployment.sum())
        assert result.deployed_ranges() == ((int(result.pre_deployment.sum()), len(trace)),)


class TestNoTransition:
    @pytest.mark.parametrize("seed", SEEDS)
    @pytest.mark.parametrize("start", SEASON_STARTS)
    def test_sixty_outdoor_days_raise_no_false_alarm(self, seed: int, start: str) -> None:
        trace = SyntheticSensor(seed, pd.Timestamp(start, tz="UTC")).trace([("outdoor", 60)])
        result = DeploymentDetector().detect(trace.series())
        assert result.events == ()
        assert not result.pre_deployment.any()
        assert result.deployed_ranges() == ((0, len(trace)),)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_cold_front_is_not_a_transition(self, seed: int) -> None:
        # -8 °C within 2 h after five days; the sensor stays outdoors.
        trace = SyntheticSensor(seed).trace([("outdoor", 10)]).with_ramp(240, -8.0, 7200.0)
        result = DeploymentDetector().detect(trace.series())
        assert result.events == ()
        assert all(s.regime is Regime.OUTDOOR for s in result.segments)

    def test_sensor_still_in_the_office(self) -> None:
        trace = SyntheticSensor(2).trace([("indoor", 2)])
        result = DeploymentDetector().detect(trace.series())
        assert result.events == ()
        assert result.pre_deployment.all()
        assert result.deployed_ranges() == ()

    def test_empty_series(self) -> None:
        result = DeploymentDetector().detect(MeasurementSeries.empty(SENSOR))
        assert result.events == ()
        assert result.segments == ()
        assert result.pre_deployment.shape == (0,)


class TestService:
    @pytest.mark.parametrize("seed", SEEDS)
    def test_retrieval_and_redeployment(self, seed: int) -> None:
        trace = SyntheticSensor(seed).trace([("outdoor", 10), ("indoor", 3), ("outdoor", 10)])
        result = DeploymentDetector().detect(trace.series())
        assert _transitions(result) == [EventKind.RETRIEVAL, EventKind.DEPLOYMENT]
        positions = [_position(trace, event) for event in result.transitions]
        assert all(abs(p - b) <= 1 for p, b in zip(positions, trace.boundaries, strict=True))
        retrieved, redeployed = positions
        assert np.flatnonzero(result.pre_deployment).tolist() == list(range(retrieved, redeployed))
        assert result.deployed_ranges() == ((0, retrieved), (redeployed, len(trace)))

    def test_office_service_and_final_retrieval(self) -> None:
        trace = SyntheticSensor(5).trace(
            [("indoor", 2), ("outdoor", 8), ("indoor", 3), ("outdoor", 8), ("indoor", 2)]
        )
        result = DeploymentDetector().detect(trace.series())
        assert _transitions(result) == [
            EventKind.DEPLOYMENT,
            EventKind.RETRIEVAL,
            EventKind.DEPLOYMENT,
            EventKind.RETRIEVAL,
        ]
        last_retrieval = _position(trace, result.transitions[-1])
        assert result.pre_deployment[last_retrieval:].all()


class TestKnownDeployments:
    def _trace(self) -> Trace:
        return SyntheticSensor(3).trace([("indoor", 3), ("outdoor", 10)])

    def test_known_time_overrides_detection(self) -> None:
        trace = self._trace()
        known = (trace.timestamp(trace.boundaries[0]) + 2 * HOUR).floor("s")
        result = DeploymentDetector().detect(trace.series(), [known.to_pydatetime()])
        (deployment,) = result.events
        assert isinstance(deployment, DeploymentEvent)
        assert (deployment.t_utc, deployment.source, deployment.confidence) == (
            known,
            EventSource.REGISTRY,
            1.0,
        )
        assert "detected -2.00 h from it" in deployment.detail  # rounded to 0.01 h
        # Ground truth decides the flags: four more samples (2 h) are pre-deployment.
        first_outdoor = int(np.searchsorted(trace.t_s, known.value / 1e9))
        assert np.flatnonzero(result.pre_deployment).tolist() == list(range(first_outdoor))

    def test_mismatch_beyond_tolerance_warns(self) -> None:
        trace = self._trace()
        known = trace.timestamp(trace.boundaries[0]) + 48 * HOUR
        result = DeploymentDetector().detect(trace.series(), [known])
        warnings = [e for e in result.events if e.kind is EventKind.DEPLOYMENT_MISMATCH]
        assert len(warnings) == 2
        assert all(w.severity is Severity.WARNING for w in warnings)
        assert {w.detail.split(":")[0] for w in warnings} == {
            "known deployment not confirmed by the data",
            "detected deployment ignored",
        }
        assert [t.t_utc for t in result.transitions] == [known]
        first_outdoor = int(np.searchsorted(trace.t_s, known.value / 1e9))
        assert result.pre_deployment[:first_outdoor].all()
        assert not result.pre_deployment[first_outdoor:].any()

    def test_known_deployment_before_the_data(self) -> None:
        trace = SyntheticSensor(4).trace([("outdoor", 5)])
        known = trace.timestamp(0) - 24 * HOUR
        result = DeploymentDetector().detect(trace.series(), [known])
        assert not result.pre_deployment.any()
        assert [e.kind for e in result.events] == [
            EventKind.DEPLOYMENT,
            EventKind.DEPLOYMENT_MISMATCH,
        ]
        assert "no deployment was detected" in result.events[1].detail

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

    def test_naive_known_time_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            DeploymentDetector().detect(self._trace().series(), [pd.Timestamp("2026-04-04")])


class TestRobustness:
    def test_temperature_only(self) -> None:
        trace = SyntheticSensor(6).trace([("indoor", 3), ("outdoor", 10)])
        trace = trace.with_missing(range(len(trace)), rh_only=True)
        result = DeploymentDetector().detect(trace.series())
        (deployment,) = result.transitions
        assert abs(_position(trace, deployment) - trace.boundaries[0]) <= 1
        assert result.segments[0].verdict.features.rh_median_pct is None

    def test_flagged_gross_error_is_ignored(self) -> None:
        trace = SyntheticSensor(7).trace([("outdoor", 6)]).with_spike(150, delta_c=-500.0)
        series = trace.series()
        qc = np.zeros(len(trace), dtype=np.int32)
        qc[150] = int(QcFlag.OUT_OF_RANGE)
        result = DeploymentDetector().detect(series.with_flags(qc))
        assert result.events == ()

    def test_missing_rows_take_the_state_of_their_time(self) -> None:
        trace = SyntheticSensor(8).trace([("indoor", 3), ("outdoor", 10)])
        boundary = trace.boundaries[0]
        trace = trace.with_missing([boundary - 2, boundary + 2])
        result = DeploymentDetector().detect(trace.series())
        assert result.pre_deployment[boundary - 2]
        assert not result.pre_deployment[boundary + 2]


class TestTimeline:
    T0 = pd.Timestamp("2026-04-01T00:00:00Z")

    def _event(self, kind: EventKind, hours: float) -> DeploymentEvent:
        return DeploymentEvent(kind, self.T0 + hours * HOUR, "detected", confidence=0.9)

    def test_indoor_mask_state_machine(self) -> None:
        t_ns = (self.T0 + pd.to_timedelta(np.arange(6), unit="h")).as_unit("ns").asi8
        transitions = [
            self._event(EventKind.DEPLOYMENT, 2),
            self._event(EventKind.DEPLOYMENT, 3),  # already outdoor: no change
            self._event(EventKind.RETRIEVAL, 4),
        ]
        mask = DeploymentTimeline(transitions, starts_indoor=True).indoor_mask(t_ns)
        assert mask.tolist() == [True, True, False, False, True, True]
        assert not DeploymentTimeline([], starts_indoor=False).indoor_mask(t_ns).any()

    def test_reconcile_without_known_times_keeps_detection(self) -> None:
        detected = [self._event(EventKind.RETRIEVAL, 5), self._event(EventKind.DEPLOYMENT, 1)]
        result = KnownDeploymentReconciler(3600.0).reconcile(detected, [])
        assert [e.t_utc for e in result.transitions] == [self.T0 + HOUR, self.T0 + 5 * HOUR]
        assert result.warnings == ()

    def test_reconcile_keeps_retrievals_and_matches_nearest(self) -> None:
        detected = [
            self._event(EventKind.DEPLOYMENT, 10),
            self._event(EventKind.RETRIEVAL, 50),
            self._event(EventKind.DEPLOYMENT, 100),
        ]
        known = [self.T0 + 10.5 * HOUR, self.T0 + 99 * HOUR]
        result = KnownDeploymentReconciler(3600.0).reconcile(detected, known)
        assert [(e.kind, e.source) for e in result.transitions] == [
            (EventKind.DEPLOYMENT, EventSource.REGISTRY),
            (EventKind.RETRIEVAL, EventSource.DETECTED),
            (EventKind.DEPLOYMENT, EventSource.REGISTRY),
        ]
        assert result.warnings == ()
