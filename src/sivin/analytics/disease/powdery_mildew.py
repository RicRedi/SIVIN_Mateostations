"""Powdery mildew risk (``powdery_mildew_gt``): daily assessment of raw samples and the index."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Final

import numpy as np
import numpy.typing as npt

from sivin.analytics.base import IndexContext, IndexResult, index_registry
from sivin.analytics.disease.gubler_thomas import (
    DayAssessment,
    GublerThomasModel,
    GublerThomasParams,
    GublerThomasState,
)
from sivin.analytics.disease.result import DiseaseIndex
from sivin.analytics.disease.sampling import RunFinder, SampleTiming
from sivin.core.schema import Column
from sivin.core.timeutil import LocalTimeConverter

logger = logging.getLogger(__name__)

SECONDS_PER_MINUTE: Final = 60.0
"""Seconds in one minute."""


class PowderyMildewDayAssessor:
    """Turn the raw samples of a sensor into one :class:`DayAssessment` per local day.

    * The longest run in the favourable band is measured from the time each valid sample
      represents (:mod:`sivin.analytics.disease.sampling`), only within the local day.
    * A day is *favourable* if that run lasts at least ``min_favourable_run_h``. Otherwise it
      is *not favourable* if its temperature coverage reaches ``ctx.min_daily_coverage``, and
      *undetermined* if it does not: missing data could have held the run.
    * *Heat* means valid samples at or above ``heat_temp_c`` representing at least
      ``min_heat_duration_min`` in total. With ~30-minute sampling one such sample suffices.

    Parameters
    ----------
    params : GublerThomasParams
        Thresholds and sampling parameters.
    """

    __slots__ = ("_params", "_runs")

    def __init__(self, params: GublerThomasParams) -> None:
        self._params = params
        self._runs = RunFinder()

    def assess(self, ctx: IndexContext, days: Sequence[date]) -> list[DayAssessment]:
        """Assess the given local days.

        Parameters
        ----------
        ctx : IndexContext
            Raw series, daily coverage, QC exclusion mask and coverage threshold.
        days : sequence of datetime.date
            Local dates to assess.

        Returns
        -------
        list of DayAssessment
            One assessment per requested day, in the same order.
        """
        frame = ctx.series.frame
        timing = self._params.sampling.durations().measure(frame[Column.TIMESTAMP])
        temp_c = frame[Column.TEMP].to_numpy(dtype=np.float64)
        valid = (ctx.series.valid_mask(ctx.exclude_mask) & frame[Column.TEMP].notna()).to_numpy()
        local_dates = LocalTimeConverter(ctx.timezone).local_dates(frame[Column.TIMESTAMP])
        groups = local_dates.groupby(local_dates).indices
        coverage = ctx.daily.frame["temp_coverage"]
        assessments = []
        for day in days:
            positions = np.asarray(groups.get(day, np.empty(0, dtype=np.intp)), dtype=np.intp)
            day_coverage = float(coverage.get(day, 0.0))
            assessments.append(
                self._assess_day(
                    day,
                    timing.subset(positions),
                    temp_c[positions],
                    valid[positions],
                    day_coverage >= ctx.min_daily_coverage,
                )
            )
        return assessments

    def _assess_day(
        self,
        day: date,
        timing: SampleTiming,
        temp_c: npt.NDArray[np.float64],
        valid: npt.NDArray[np.bool_],
        covered: bool,
    ) -> DayAssessment:
        params = self._params
        in_band = (temp_c >= params.band_min_temp_c) & (temp_c <= params.band_max_temp_c)
        runs = self._runs.find(timing, in_band, valid)
        longest_run_h = max((run.duration_h for run in runs), default=0.0)
        favourable: bool | None
        if longest_run_h >= params.min_favourable_run_h:
            favourable = True
        elif covered:
            favourable = False
        else:
            favourable = None
        hot = valid & (temp_c >= params.heat_temp_c)
        heat_s = float(timing.durations_s[hot].sum())
        heat = bool(hot.any()) and heat_s >= params.min_heat_duration_min * SECONDS_PER_MINUTE
        return DayAssessment(day=day, favourable=favourable, heat=heat, longest_run_h=longest_run_h)


@index_registry.register
class PowderyMildewGublerThomas(DiseaseIndex[GublerThomasParams]):
    """Gubler-Thomas powdery mildew risk index (UC Davis), 0-100 points.

    Result: ``value`` is the season maximum of the index and ``classification`` its risk
    class; ``daily`` is the index at the end of each day from the first to the last day with
    samples in the period (the model waits for onset before the first sample); ``details``
    holds the onset date, the current index and its class (``current_class``) and day counts.
    ``coverage``/``complete`` follow ``ClimateIndex._season_days`` (temperature coverage).
    """

    index_id = "powdery_mildew_gt"
    unit = "points"
    params_model = GublerThomasParams

    def compute(self, ctx: IndexContext) -> IndexResult:
        """Run the model over the period of ``ctx.year``.

        Parameters
        ----------
        ctx : IndexContext
            Data of one sensor and one year.

        Returns
        -------
        IndexResult
            See the class docstring; ``value`` is ``None`` if there are no samples in the
            period.
        """
        season = self.params.season.to_season()
        selection = self._season_days(ctx, season)
        days = self._model_days(ctx, season)
        if not days:
            logger.info("No samples of %s in the period %s %s.", ctx.sensor_id, season, ctx.year)
            return self._result(ctx, selection.coverage, value=None)
        assessments = PowderyMildewDayAssessor(self.params).assess(ctx, days)
        model = GublerThomasModel(self.params)
        states = model.run(assessments)
        daily = self._daily_series(days, [float(state.index_points) for state in states])
        current = states[-1]
        return self._result(
            ctx,
            selection.coverage,
            value=float(daily.max()),
            complete=selection.complete,
            classification=str(model.classify(max(s.index_points for s in states))),
            daily=daily,
            details={
                **_details(states, assessments),
                "current_class": str(model.classify(current.index_points)),
            },
        )


def _details(
    states: Sequence[GublerThomasState], assessments: Sequence[DayAssessment]
) -> dict[str, float | int | str]:
    """Summarise a model run for :attr:`IndexResult.details`."""
    current = states[-1]
    details: dict[str, float | int | str] = {
        "current_index_points": current.index_points,
        "phase": str(current.phase),
        "n_days": len(assessments),
        "n_favourable_days": sum(day.favourable is True for day in assessments),
        "n_unfavourable_days": sum(day.favourable is False for day in assessments),
        "n_undetermined_days": sum(day.favourable is None for day in assessments),
        "n_heat_days": sum(day.heat for day in assessments),
        "longest_run_h_max": max(day.longest_run_h for day in assessments),
    }
    if current.onset_date is not None:
        details["onset_date"] = current.onset_date.isoformat()
    return details
