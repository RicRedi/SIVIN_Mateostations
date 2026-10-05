"""Common base of the disease models: building their :class:`IndexResult`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import ClassVar, Final

import numpy as np
import pandas as pd

from sivin.analytics.base import ClimateIndex, IndexContext, IndexParams, IndexResult
from sivin.core.season import Season
from sivin.core.timeutil import LocalTimeConverter

DATE_INDEX_NAME: Final = "date"
"""Name of the index of the daily curves (local calendar date, as in ``DailyWeather``)."""


class DiseaseIndex[P: IndexParams](ClimateIndex[P]):
    """A :class:`ClimateIndex` of this package; adds a uniform result builder.

    Attributes
    ----------
    estimated : bool
        Class variable; ``True`` for models that rely on a proxy (e.g. wetness from humidity).
        Copied into every :class:`IndexResult`.
    """

    estimated: ClassVar[bool] = False

    @staticmethod
    def _model_days(ctx: IndexContext, season: Season) -> list[date]:
        """Return the local days the model runs over in ``ctx.year``.

        Parameters
        ----------
        ctx : IndexContext
            Input of :meth:`compute`.
        season : Season
            The model period.

        Returns
        -------
        list of datetime.date
            Every day from the first to the last local date with a sample inside the period
            (also days without samples in between); empty if the period has no sample.
        """
        first_day, last_day = season.dates(ctx.year)
        dates = LocalTimeConverter(ctx.timezone).local_dates(ctx.series.timestamps)
        in_period = dates[(dates >= first_day) & (dates <= last_day)]
        if in_period.empty:
            return []
        start: date = in_period.iloc[0]
        end: date = in_period.iloc[-1]
        return [start + timedelta(days=n) for n in range((end - start).days + 1)]

    def _daily_series(self, days: Sequence[date], values: Sequence[float]) -> pd.Series:
        """Build the daily curve of :attr:`IndexResult.daily` (float, indexed by local date)."""
        return pd.Series(
            list(values),
            index=pd.Index(list(days), dtype=object, name=DATE_INDEX_NAME),
            name=self.index_id,
            dtype=np.float64,
        )

    def _result(
        self,
        ctx: IndexContext,
        coverage: float,
        value: float | None,
        complete: bool = False,
        classification: str | None = None,
        daily: pd.Series | None = None,
        details: dict[str, float | int | str] | None = None,
    ) -> IndexResult:
        """Build the result of this index for ``ctx`` (``complete`` is ``False`` by default)."""
        return IndexResult(
            index_id=self.index_id,
            sensor_id=ctx.sensor_id,
            year=ctx.year,
            value=value,
            unit=self.unit,
            coverage=coverage,
            complete=complete,
            classification=classification,
            daily=daily,
            details=details or {},
            estimated=self.estimated,
        )
