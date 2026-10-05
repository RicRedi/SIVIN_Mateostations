"""Off-site log in quality control and the advisory detector (MIGRATION_PLAN §2.8, WP-1.8).

SYNTHETIC data only. Expected flags are computed by hand from the period bounds; local times
use the Europe/Prague rules (CET = UTC+1, CEST = UTC+2; changes on 2026-03-29 and 2026-10-25).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest
from tests.quality.synthetic import SENSOR, SyntheticSensor, Trace, flat_trace

from sivin.core.flags import QcFlag
from sivin.core.ids import SensorId
from sivin.core.schema import Column, MeasurementSeries
from sivin.quality import (
    DeploymentDetector,
    DeploymentSettings,
    DetectorMode,
    EventKind,
    EventSource,
    QualityEvent,
    QualityPipeline,
    QualityPipelineSettings,
    Severity,
)
from sivin.quality.checks import OffSiteCheck, OffSiteSettings, SpikeCheck
from sivin.quality.deployment import (
    AdvisoryPolicy,
    Detection,
    DetectionPolicy,
    LoggedCoverage,
    register_policy,
)
from sivin.registry.model import Sensor
from sivin.registry.offsite import OffSiteLog, OffSitePeriod
from sivin.registry.registry import SensorRegistry

OTHER = SensorId("77799986")
HOUR = pd.Timedelta(hours=1)


def _registry() -> SensorRegistry:
    def sensor(serial: str) -> Sensor:
        return Sensor.model_validate(
            {
                "id": serial,
                "portal_name": f"8615620 {serial}",
                "label": f"{serial} (synthetic)",
                "site": None,
                "variety": None,
                "status": "active",
                "placements": [
                    {
                        "from": "2025-01-01T00:00:00Z",
                        "to": None,
                        "lon": 16.6,
                        "lat": 48.8,
                        "elevation_m": None,
                        "note": None,
                    }
                ],
                "notes": None,
            }
        )

    return SensorRegistry([sensor(str(SENSOR)), sensor(str(OTHER))])


def _period(
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None,
    reason: str = "office",
    sensor: SensorId = SENSOR,
    note: str | None = None,
) -> OffSitePeriod:
    def value(t: str | pd.Timestamp | None) -> object:
        return t.to_pydatetime() if isinstance(t, pd.Timestamp) else t

    return OffSitePeriod.model_validate(
        {"sensor": sensor, "from": value(start), "to": value(end), "reason": reason, "note": note}
    )


def _log(*periods: OffSitePeriod) -> OffSiteLog:
    return OffSiteLog(periods, _registry())


def _half_hourly(start_utc: str, n_samples: int) -> MeasurementSeries:
    times = pd.date_range(start_utc, periods=n_samples, freq="30min")
    return MeasurementSeries.from_records(
        SENSOR, times, np.full(n_samples, 15.0), np.full(n_samples, 70.0)
    )


def _flagged(series: MeasurementSeries, flag: QcFlag) -> list[int]:
    qc = series.frame[Column.QC].to_numpy()
    return [int(i) for i in np.flatnonzero(qc & int(flag))]


def _kinds(events: Sequence[QualityEvent]) -> list[EventKind]:
    return [event.kind for event in events]


class TestOffSiteCheck:
    def test_flags_exactly_inside_the_period_across_spring_forward(self) -> None:
        # 2026-03-28 12:00 CET = 11:00Z (row 22 from 00:00Z, step 30 min);
        # 2026-03-30 12:00 CEST = 10:00Z (row 116); exclusive end.
        series = _half_hourly("2026-03-28T00:00Z", 150)
        check = OffSiteCheck(_log(_period("2026-03-28 12:00", "2026-03-30 12:00")))
        outcome = check.check(series)
        assert np.flatnonzero(outcome.flags).tolist() == list(range(22, 116))
        assert set(outcome.flags[22:116].tolist()) == {int(QcFlag.PRE_DEPLOYMENT)}

    def test_flags_exactly_inside_the_period_across_fall_back(self) -> None:
        # 2026-10-24 12:00 CEST = 10:00Z (row 20); 2026-10-26 12:00 CET = 11:00Z (row 118).
        series = _half_hourly("2026-10-24T00:00Z", 150)
        outcome = OffSiteCheck(_log(_period("2026-10-24 12:00", "2026-10-26 12:00"))).check(series)
        assert np.flatnonzero(outcome.flags).tolist() == list(range(20, 118))

    def test_one_event_per_overlapping_period(self) -> None:
        series = _half_hourly("2026-07-01T00:00Z", 48)  # 00:00Z - 23:30Z
        log = _log(
            _period("2026-06-01T00:00Z", "2026-06-30T00:00Z"),  # before the series
            _period("2026-06-30T12:00Z", "2026-07-01T00:30Z", "transport", note="car"),
            _period("2026-07-01T10:00Z", "2026-07-01T11:00Z", "service"),
            _period("2026-07-01T23:30Z", None, "storage", note="winter"),
            _period("2026-07-01T05:00Z", "2026-07-01T06:00Z", sensor=OTHER),
        )
        outcome = OffSiteCheck(log).check(series)
        assert np.flatnonzero(outcome.flags).tolist() == [0, 20, 21, 47]
        assert [(e.t_utc, e.end_utc, e.detail) for e in outcome.events] == [
            (
                pd.Timestamp("2026-06-30T12:00Z"),
                pd.Timestamp("2026-07-01T00:30Z"),
                "transport: car",
            ),
            (pd.Timestamp("2026-07-01T10:00Z"), pd.Timestamp("2026-07-01T11:00Z"), "service"),
            (pd.Timestamp("2026-07-01T23:30Z"), None, "storage: winter"),
        ]
        event = outcome.events[0]
        assert event.kind is EventKind.OFF_SITE
        assert event.source is EventSource.LOG
        assert event.severity is Severity.INFO
        assert event.origin == "offsite"

    def test_empty_series_and_empty_log(self) -> None:
        log = _log(_period("2026-07-01T00:00Z", None))
        outcome = OffSiteCheck(log).check(MeasurementSeries.empty(SENSOR))
        assert outcome.flags.shape == (0,)
        assert outcome.events == ()
        assert (
            OffSiteCheck(OffSiteLog.empty())
            .check(_half_hourly("2026-07-01T00:00Z", 4))
            .count(QcFlag.PRE_DEPLOYMENT)
            == 0
        )

    def test_settings_and_log(self) -> None:
        log = OffSiteLog.empty()
        check = OffSiteCheck(log, OffSiteSettings())
        assert check.log is log
        assert check.settings == OffSiteSettings()


def _two_indoor_stays(seed: int = 1) -> Trace:
    """Office 3 days, vineyard 10 days, service 3 days, vineyard 10 days (boundaries known)."""
    return SyntheticSensor(seed).trace(
        [("indoor", 3), ("outdoor", 10), ("indoor", 3), ("outdoor", 10)]
    )


def _logged_stay(trace: Trace, first: int | None, stop: int) -> OffSitePeriod:
    """A period covering rows ``[first, stop)`` (``None`` = from before the data)."""
    start = trace.timestamp(0) - HOUR if first is None else trace.timestamp(first).floor("min")
    return _period(start, trace.timestamp(stop).floor("min"))


class TestPipelineWithLog:
    def test_flags_only_from_the_log_and_a_warning_for_the_unlogged_stay(self) -> None:
        trace = _two_indoor_stays()
        office_end, service_start, service_end = trace.boundaries
        log = _log(_logged_stay(trace, None, office_end))
        pipeline = QualityPipeline.from_settings(QualityPipelineSettings(), off_site_log=log)
        result = pipeline.run(trace.series())
        assert _flagged(result.series, QcFlag.PRE_DEPLOYMENT) == list(range(office_end))
        assert result.deployment is not None
        assert not result.deployment.pre_deployment.any()
        off_site = [e for e in result.events if e.kind is EventKind.OFF_SITE]
        assert len(off_site) == 1
        warnings = [e for e in result.events if e.severity is Severity.WARNING]
        assert _kinds(warnings) == [EventKind.UNLOGGED_OFF_SITE]
        (warning,) = warnings
        assert abs(warning.t_utc - trace.timestamp(service_start)) <= HOUR
        assert warning.end_utc is not None
        assert abs(warning.end_utc - trace.timestamp(service_end)) <= HOUR
        # Local time (CEST) first, UTC in brackets, plus ready-to-paste log values.
        assert warning.detail.startswith("possible unlogged off-site period 2026-04-14 01:")
        assert "CEST (2026-04-13 23:" in warning.detail
        assert 'from: "2026-04-14T01:' in warning.detail
        assert '+02:00" and to: "2026-04-17T01:' in warning.detail
        assert "sensors/offsite_log.yaml" in warning.detail
        assert not {EventKind.DEPLOYMENT, EventKind.RETRIEVAL} & set(_kinds(result.events))

    def test_no_warning_when_the_log_covers_every_stay(self) -> None:
        trace = _two_indoor_stays()
        office_end, service_start, service_end = trace.boundaries
        log = _log(
            _logged_stay(trace, None, office_end),
            _logged_stay(trace, service_start, service_end),
        )
        result = QualityPipeline.from_settings(QualityPipelineSettings(), off_site_log=log).run(
            trace.series()
        )
        expected = [*range(office_end), *range(service_start, service_end)]
        assert _flagged(result.series, QcFlag.PRE_DEPLOYMENT) == expected
        assert [e for e in result.events if e.severity is Severity.WARNING] == []
        # The logged boundaries split the deployed checks: the jumps are no steps or spikes.
        assert result.flag_counts[QcFlag.STEP] == 0
        assert result.flag_counts[QcFlag.SPIKE] == 0

    def test_log_within_the_tolerance_counts_as_covering(self) -> None:
        trace = _two_indoor_stays()
        office_end, service_start, service_end = trace.boundaries
        shifted = _period(
            trace.timestamp(service_start).floor("min") + 2 * HOUR,
            trace.timestamp(service_end).floor("min") - 2 * HOUR,
            "service",
        )
        log = _log(_logged_stay(trace, None, office_end), shifted)
        result = QualityPipeline.from_settings(QualityPipelineSettings(), off_site_log=log).run(
            trace.series()
        )
        assert [e for e in result.events if e.severity is Severity.WARNING] == []
        strict = QualityPipelineSettings(deployment=DeploymentSettings(log_tolerance_s=3600.0))
        result = QualityPipeline.from_settings(strict, off_site_log=log).run(trace.series())
        assert _kinds([e for e in result.events if e.severity is Severity.WARNING]) == [
            EventKind.UNLOGGED_OFF_SITE
        ]

    def test_without_log_every_detected_stay_is_only_a_warning(self) -> None:
        trace = _two_indoor_stays()
        result = QualityPipeline.from_settings(QualityPipelineSettings()).run(trace.series())
        assert result.flag_counts[QcFlag.PRE_DEPLOYMENT] == 0
        warnings = [e for e in result.events if e.kind is EventKind.UNLOGGED_OFF_SITE]
        assert len(warnings) == 2
        assert warnings[0].t_utc == trace.timestamp(0)

    def test_log_and_enforcing_detector_are_combined(self) -> None:
        trace = _two_indoor_stays()
        office_end, service_start, service_end = trace.boundaries
        log = _log(_logged_stay(trace, None, office_end))
        enforce = QualityPipelineSettings(deployment=DeploymentSettings(mode=DetectorMode.ENFORCE))
        result = QualityPipeline.from_settings(enforce, off_site_log=log).run(trace.series())
        flagged = _flagged(result.series, QcFlag.PRE_DEPLOYMENT)
        assert flagged[:office_end] == list(range(office_end))
        assert abs(flagged[office_end] - service_start) <= 1
        assert abs(flagged[-1] + 1 - service_end) <= 1

    def test_log_without_detector_and_deployed_checks_skip_logged_rows(self) -> None:
        trace = flat_trace([10.0, 10.0, 10.0, 30.0, 10.0, 10.0, 10.0, 10.0])
        series = trace.series()
        logged = _period(trace.timestamp(2).floor("min"), trace.timestamp(5).floor("min"))
        pipeline = QualityPipeline([], [SpikeCheck()], detector=None, off_site_log=_log(logged))
        result = pipeline.run(series)
        assert _flagged(result.series, QcFlag.PRE_DEPLOYMENT) == [2, 3, 4]
        assert result.flag_counts[QcFlag.SPIKE] == 0
        assert _kinds(result.events) == [EventKind.OFF_SITE]


class TestAdvisoryDetector:
    def test_default_mode_is_advisory_and_sets_no_flags(self) -> None:
        trace = SyntheticSensor(1).trace([("indoor", 3), ("outdoor", 10)])
        detector = DeploymentDetector()
        assert detector.settings.mode is DetectorMode.ADVISORY
        result = detector.detect(trace.series())
        assert not result.pre_deployment.any()
        assert result.transitions == ()
        assert _kinds(result.events) == [EventKind.UNLOGGED_OFF_SITE]
        assert result.events[0].confidence is not None
        assert result.deployed_ranges() == ((0, len(trace)),)
        assert result.outcome().count(QcFlag.PRE_DEPLOYMENT) == 0

    def test_unconfirmed_transition_warning_kept_unless_logged(self) -> None:
        trace = SyntheticSensor(5).trace([("indoor", 2), ("outdoor", 8), ("indoor", 3)])
        series = trace.series()
        result = DeploymentDetector().detect(series)
        assert EventKind.UNCONFIRMED_TRANSITION in _kinds(result.events)
        retrieval = trace.boundaries[1]
        logged = [
            _period(trace.timestamp(0) - HOUR, trace.timestamp(trace.boundaries[0]).floor("min")),
            _period(trace.timestamp(retrieval).floor("min"), None, "service"),
        ]
        result = DeploymentDetector().detect(series, logged_off_site=logged)
        assert result.events == ()

    def test_empty_series(self) -> None:
        result = DeploymentDetector().detect(MeasurementSeries.empty(SENSOR))
        assert result.events == ()
        assert result.pre_deployment.shape == (0,)

    def test_custom_policy_is_used(self) -> None:
        class Silent(AdvisoryPolicy):
            def resolve(
                self, detection: Detection, logged: Sequence[OffSitePeriod]
            ) -> tuple[tuple[QualityEvent, ...], npt.NDArray[np.bool_]]:
                return (), np.ones_like(detection.indoor)

        settings = DeploymentSettings()
        detector = DeploymentDetector(settings, policy=Silent(settings))
        result = detector.detect(SyntheticSensor(1).trace([("outdoor", 2)]).series())
        assert result.events == ()
        assert result.pre_deployment.all()

    def test_a_mode_has_one_policy(self) -> None:
        class Duplicate(DetectionPolicy):
            mode = DetectorMode.ADVISORY

            def resolve(
                self, detection: Detection, logged: Sequence[OffSitePeriod]
            ) -> tuple[tuple[QualityEvent, ...], npt.NDArray[np.bool_]]:
                return (), detection.indoor

        with pytest.raises(ValueError, match="already registered"):
            register_policy(Duplicate)

    def test_invalid_mode(self) -> None:
        with pytest.raises(ValueError, match="mode"):
            DeploymentSettings.model_validate({"mode": "loud"})

    def test_display_timezone(self) -> None:
        trace = SyntheticSensor(1).trace([("indoor", 3), ("outdoor", 10)])
        settings = DeploymentSettings(display_timezone="UTC")
        (warning,) = DeploymentDetector(settings).detect(trace.series()).events
        assert "UTC (" in warning.detail
        assert "+00:00" in warning.detail
        with pytest.raises(ValueError, match="unknown IANA time zone"):
            DeploymentSettings(display_timezone="Mars/Olympus")


class TestLoggedCoverage:
    t = staticmethod(pd.Timestamp)

    def test_touching_periods_are_merged(self) -> None:
        coverage = LoggedCoverage(
            [
                _period("2026-07-03T00:00Z", "2026-07-05T00:00Z", "office"),
                _period("2026-07-01T00:00Z", "2026-07-03T00:00Z", "transport"),
            ],
            tolerance_s=0.0,
        )
        assert coverage.covers(self.t("2026-07-01T00:00Z"), self.t("2026-07-05T00:00Z"))
        assert not coverage.covers(self.t("2026-06-30T23:59Z"), self.t("2026-07-02T00:00Z"))
        assert not coverage.covers(self.t("2026-07-04T00:00Z"), self.t("2026-07-05T00:01Z"))

    def test_tolerance_and_gaps(self) -> None:
        coverage = LoggedCoverage(
            [
                _period("2026-07-01T00:00Z", "2026-07-02T00:00Z"),
                _period("2026-07-02T03:00Z", "2026-07-03T00:00Z"),
            ],
            tolerance_s=3600.0,
        )
        assert coverage.covers(self.t("2026-06-30T23:00Z"), self.t("2026-07-02T01:00Z"))
        assert not coverage.covers(self.t("2026-07-01T12:00Z"), self.t("2026-07-02T12:00Z"))

    def test_open_period_covers_everything_after(self) -> None:
        coverage = LoggedCoverage(
            [
                _period("2026-07-05T00:00Z", None),
                _period("2026-07-01T00:00Z", "2026-07-06T00:00Z", sensor=SENSOR),
            ],
            tolerance_s=0.0,
        )
        assert coverage.covers(self.t("2026-07-01T00:00Z"), self.t("2030-01-01T00:00Z"))
        merged_open_first = LoggedCoverage(
            [_period("2026-07-01T00:00Z", None), _period("2026-07-02T00:00Z", "2026-07-03T00:00Z")],
            tolerance_s=0.0,
        )
        assert merged_open_first.covers(self.t("2026-07-01T00:00Z"), self.t("2027-01-01T00:00Z"))

    def test_no_periods(self) -> None:
        assert not LoggedCoverage([], 3600.0).covers(
            self.t("2026-07-01T00:00Z"), self.t("2026-07-01T00:00Z")
        )
