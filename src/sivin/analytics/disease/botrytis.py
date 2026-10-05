"""Botrytis bunch rot infection model of Broome et al. (1995) (``botrytis_broome``).

The model gives the infection probability ``Y`` of a wetness period from its duration ``W``
(h) and mean temperature ``T`` (°C):

.. math:: \\ln\\frac{Y}{1-Y} = a + b\\,W + c\\,W T + d\\,W T^2

**Wetness is not measured** by the sensors. It is *estimated* as periods with relative
humidity at or above a threshold (:class:`WetnessPeriodDetector`), so every result carries
``estimated=True``. See ``docs/indices/botrytis_broome.md`` for the proxy and its bias.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sivin.analytics.base import IndexContext, IndexParams, IndexResult, index_registry
from sivin.analytics.disease.period import SeasonWindow
from sivin.analytics.disease.result import DiseaseIndex
from sivin.analytics.disease.sampling import (
    SECONDS_PER_HOUR,
    RunFinder,
    SampleRun,
    SampleTiming,
    SamplingParams,
)
from sivin.core.schema import Column, MeasurementSeries
from sivin.core.timeutil import LocalTimeConverter

logger = logging.getLogger(__name__)


class BroomeCoefficients(BaseModel):
    """Coefficients of the logit equation of Broome et al. (1995).

    The defaults are the published values as commonly quoted from Broome et al. (1995); they
    could not be checked against the paper in this project and are marked
    **[to be verified]**.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intercept: float = Field(-2.647866, description="a (dimensionless) [to be verified].")
    wetness_h: float = Field(
        -0.374927, description="b, per hour of wetness (1/h) [to be verified]."
    )
    wetness_temp: float = Field(
        0.061601, description="c, per hour and °C (1/(h·°C)) [to be verified]."
    )
    wetness_temp_sq: float = Field(
        -0.001511, description="d, per hour and °C squared (1/(h·°C²)) [to be verified]."
    )

    def logit(self, wetness_h: float, temp_c: float) -> float:
        """Return ``ln(Y / (1 - Y))`` for a wetness period.

        Parameters
        ----------
        wetness_h : float
            Wetness duration ``W`` in hours.
        temp_c : float
            Mean temperature ``T`` during wetness in °C.

        Returns
        -------
        float
            ``a + b W + c W T + d W T²`` (dimensionless).
        """
        return (
            self.intercept
            + self.wetness_h * wetness_h
            + self.wetness_temp * wetness_h * temp_c
            + self.wetness_temp_sq * wetness_h * temp_c**2
        )

    def infection_probability(self, wetness_h: float, temp_c: float) -> float:
        """Return the infection probability ``Y`` (0-1) of a wetness period.

        Parameters
        ----------
        wetness_h : float
            Wetness duration ``W`` in hours.
        temp_c : float
            Mean temperature ``T`` during wetness in °C.

        Returns
        -------
        float
            ``1 / (1 + exp(-logit))``, dimensionless, 0-1.
        """
        return logistic(self.logit(wetness_h, temp_c))


def logistic(logit: float) -> float:
    """Return the inverse of the logit, ``1 / (1 + exp(-logit))``, computed stably.

    Parameters
    ----------
    logit : float
        Log-odds (dimensionless).

    Returns
    -------
    float
        Probability, 0-1.
    """
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    odds = math.exp(logit)
    return odds / (1.0 + odds)


class RiskBand(BaseModel):
    """A risk class from a lower bound of the infection probability upwards."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1, description="Class label, e.g. 'low'.")
    min_probability: float = Field(
        ge=0.0, le=1.0, description="Lowest infection probability (0-1) of the class."
    )


class BotrytisBroomeParams(IndexParams):
    """Parameters of the Broome Botrytis model with the humidity proxy for wetness."""

    wet_rh_threshold_pct: float = Field(
        90.0,
        gt=0.0,
        le=100.0,
        description=(
            "Relative humidity (%) at or above which a sample counts as wet. Proxy for leaf "
            "wetness; project default [to be tuned], not from Broome et al. (1995)."
        ),
    )
    max_dry_interruption_h: float = Field(
        1.0,
        ge=0.0,
        description=(
            "Longest dry interruption (h) inside one wetness period; longer dry spells end it. "
            "Project default [to be tuned]."
        ),
    )
    min_event_duration_h: float = Field(
        0.0,
        ge=0.0,
        description=(
            "Shortest wetness period (h) that is reported as an event. Project default "
            "(report all) [to be tuned]."
        ),
    )
    max_wetness_h: float | None = Field(
        None,
        gt=0.0,
        description=(
            "Optional cap (h) on the wetness duration W used in the model; long estimated "
            "periods (W > 24 h) otherwise give Y close to 1. None (default): no cap. Project "
            "choice."
        ),
    )
    coefficients: BroomeCoefficients = Field(
        default_factory=BroomeCoefficients,
        description="Logit coefficients of Broome et al. (1995) [to be verified].",
    )
    risk_bands: tuple[RiskBand, ...] = Field(
        (),
        description=(
            "Risk classes by season-maximum infection probability (0-1), ascending, the first "
            "starting at 0. Empty (default): no classification, because no class limits are "
            "taken from literature."
        ),
    )
    season: SeasonWindow = Field(
        default_factory=SeasonWindow,
        description="Model period (local dates); default April 1 - October 31 (project default).",
    )
    sampling: SamplingParams = Field(
        default_factory=SamplingParams, description="Duration represented by each sample."
    )

    @model_validator(mode="after")
    def _ascending_bands(self) -> Self:
        bounds = [band.min_probability for band in self.risk_bands]
        if bounds and bounds[0] != 0.0:
            raise ValueError("the first risk band must start at probability 0")
        if any(lower >= upper for lower, upper in pairwise(bounds)):
            raise ValueError("risk bands must be strictly ascending by min_probability")
        return self


@dataclass(frozen=True, slots=True)
class WetnessPeriod:
    """A period of estimated wetness.

    Attributes
    ----------
    start_utc : pandas.Timestamp
        Time of the first wet sample (UTC).
    end_utc : pandas.Timestamp
        End of the time represented by the last wet sample (UTC).
    end_date : datetime.date
        Local date of the last wet sample; the period is counted on this day.
    duration_h : float
        Wetness duration ``W`` in hours, including bridged dry interruptions.
    interruption_h : float
        Bridged dry interruptions in hours (part of ``duration_h``).
    mean_temp_c : float or None
        Duration-weighted mean temperature in °C; ``None`` if no valid temperature.
    """

    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    end_date: date
    duration_h: float
    interruption_h: float
    mean_temp_c: float | None


@dataclass(frozen=True, slots=True)
class InfectionEvent:
    """A wetness period with its infection probability.

    Attributes
    ----------
    period : WetnessPeriod
        The estimated wetness period.
    mean_temp_c : float
        Mean temperature during the period in °C (``period.mean_temp_c``, known).
    infection_probability : float
        ``Y`` of Broome et al. (1995), 0-1 (estimated, see module docstring).
    """

    period: WetnessPeriod
    mean_temp_c: float
    infection_probability: float


class WetnessPeriodDetector:
    """Estimate wetness periods as runs of samples with high relative humidity.

    A sample is wet if its humidity is valid (present, not excluded by QC) and at least
    ``wet_rh_threshold_pct``. Dry spells up to ``max_dry_interruption_h`` are bridged; invalid
    samples and data gaps end a period.

    Parameters
    ----------
    params : BotrytisBroomeParams
        Threshold, interruption limit and sampling parameters.
    """

    __slots__ = ("_params", "_runs")

    def __init__(self, params: BotrytisBroomeParams) -> None:
        self._params = params
        self._runs = RunFinder(params.max_dry_interruption_h * SECONDS_PER_HOUR)

    def detect(
        self, series: MeasurementSeries, exclude_mask: int, timezone: str
    ) -> list[WetnessPeriod]:
        """Return the wetness periods of a series that last at least ``min_event_duration_h``.

        Parameters
        ----------
        series : MeasurementSeries
            Raw measurements.
        exclude_mask : int
            QC flags that exclude a sample.
        timezone : str
            IANA zone of the local dates.

        Returns
        -------
        list of WetnessPeriod
            In time order.
        """
        frame = series.frame
        timing = self._params.sampling.durations().measure(frame[Column.TIMESTAMP])
        usable = series.valid_mask(exclude_mask).to_numpy()
        rh_pct = frame[Column.RH].to_numpy(dtype=np.float64)
        rh_valid = usable & ~np.isnan(rh_pct)
        wet = rh_valid & (rh_pct >= self._params.wet_rh_threshold_pct)
        runs = self._runs.find(timing, wet, rh_valid)
        local_dates = LocalTimeConverter(timezone).local_dates(frame[Column.TIMESTAMP])
        periods = [self._period(run, frame, timing, usable, local_dates) for run in runs]
        return [p for p in periods if p.duration_h >= self._params.min_event_duration_h]

    @staticmethod
    def _period(
        run: SampleRun,
        frame: pd.DataFrame,
        timing: SampleTiming,
        usable: npt.NDArray[np.bool_],
        local_dates: pd.Series,
    ) -> WetnessPeriod:
        span = slice(run.first, run.last + 1)
        temp_c = frame[Column.TEMP].to_numpy(dtype=np.float64)[span]
        weights_s = timing.durations_s[span]
        has_temp = usable[span] & ~np.isnan(temp_c)
        mean_temp_c = (
            float(np.average(temp_c[has_temp], weights=weights_s[has_temp]))
            if has_temp.any()
            else None
        )
        start_utc = frame[Column.TIMESTAMP].iloc[run.first]
        last_utc = frame[Column.TIMESTAMP].iloc[run.last]
        return WetnessPeriod(
            start_utc=start_utc,
            end_utc=last_utc + pd.Timedelta(seconds=float(timing.durations_s[run.last])),
            end_date=local_dates.iloc[run.last],
            duration_h=run.duration_h,
            interruption_h=run.interruption_s / SECONDS_PER_HOUR,
            mean_temp_c=mean_temp_c,
        )


@index_registry.register
class BotrytisBroome(DiseaseIndex[BotrytisBroomeParams]):
    """Botrytis bunch rot infection risk after Broome et al. (1995), with estimated wetness.

    Result: ``value`` is the season maximum of the infection probability ``Y`` (0-1; 0 if no
    wetness period was estimated), ``daily`` the daily maximum of ``Y`` by the local date on
    which a period ends, from the first to the last day with samples in the period (0 on
    covered days without a period, ``NaN`` on other days), ``details`` summary keys and the
    event with the highest ``Y`` (the full list comes from :meth:`infection_events`), and
    ``estimated`` is always ``True``. Coverage counts the days of
    the period on which **both** temperature and humidity reach ``ctx.min_daily_coverage``.
    """

    index_id = "botrytis_broome"
    unit = "1"
    params_model = BotrytisBroomeParams
    estimated = True

    def infection_events(self, ctx: IndexContext) -> list[InfectionEvent]:
        """Return the infection events of the period of ``ctx.year``.

        Wetness periods without a valid temperature are skipped (and logged).

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and one year.

        Returns
        -------
        list of InfectionEvent
            Events whose wetness period ends within the period, in time order.
        """
        season = self.params.season.to_season()
        detector = WetnessPeriodDetector(self.params)
        events = []
        for period in detector.detect(ctx.series, ctx.exclude_mask, ctx.timezone):
            if period.end_date.year != ctx.year or not season.contains(period.end_date):
                continue
            if period.mean_temp_c is None:
                logger.info("Wetness period from %s has no valid temperature.", period.start_utc)
                continue
            probability = self.params.coefficients.infection_probability(
                self._model_wetness_h(period.duration_h), period.mean_temp_c
            )
            events.append(InfectionEvent(period, period.mean_temp_c, probability))
        return events

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Estimate wetness periods and their infection probability over the period.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and one year.

        Returns
        -------
        IndexResult
            See the class docstring; ``value`` is ``None`` without samples in the period.
        """
        season = self.params.season.to_season()
        first_day, last_day = season.dates(ctx.year)
        covered_days = _covered_days(ctx, first_day, last_day)
        coverage = len(covered_days) / season.n_days(ctx.year)
        days = self._model_days(ctx, season)
        if not days:
            logger.info("No samples of %s in the period %s %s.", ctx.sensor_id, season, ctx.year)
            return self._result(ctx, coverage, value=None)
        events = self.infection_events(ctx)
        daily = self._daily_curve(events, days, covered_days)
        value = max((event.infection_probability for event in events), default=0.0)
        return self._result(
            ctx,
            coverage,
            value=value,
            complete=coverage >= ctx.min_season_coverage,
            classification=self._classify(value),
            daily=daily,
            details=self._details(events),
        )

    def _classify(self, probability: float) -> str | None:
        label = None
        for band in self.params.risk_bands:
            if probability >= band.min_probability:
                label = band.label
        return label

    def _daily_curve(
        self,
        events: Sequence[InfectionEvent],
        days: Sequence[date],
        covered_days: set[date],
    ) -> pd.Series:
        values = {day: 0.0 if day in covered_days else math.nan for day in days}
        for event in events:
            day = event.period.end_date
            current = values[day]
            values[day] = (
                event.infection_probability
                if math.isnan(current)
                else max(current, event.infection_probability)
            )
        return self._daily_series(days, [values[day] for day in days])

    def _model_wetness_h(self, duration_h: float) -> float:
        """Return the wetness duration W in hours used in the model (capped if configured)."""
        cap = self.params.max_wetness_h
        return duration_h if cap is None else min(duration_h, cap)

    def _details(self, events: Sequence[InfectionEvent]) -> dict[str, float | int | str]:
        """Summary keys and the event with the highest Y (full list: :meth:`infection_events`)."""
        details: dict[str, float | int | str] = {
            "n_events": len(events),
            "wetness_proxy": f"rh_pct >= {self.params.wet_rh_threshold_pct:g}",
            "total_wetness_h": sum(event.period.duration_h for event in events),
        }
        if events:
            top = max(events, key=lambda event: event.infection_probability)
            details["max_infection_probability"] = top.infection_probability
            details["max_event_start_utc"] = top.period.start_utc.isoformat()
            details["max_event_duration_h"] = top.period.duration_h
            details["max_event_mean_temp_c"] = top.mean_temp_c
        return details


def _covered_days(ctx: IndexContext, first_day: date, last_day: date) -> set[date]:
    """Days of the period on which temperature and humidity reach the daily coverage."""
    frame = ctx.daily.between(first_day, last_day).frame
    covered = (frame["temp_coverage"] >= ctx.min_daily_coverage) & (
        frame["rh_coverage"] >= ctx.min_daily_coverage
    )
    return set(frame.index[covered])
