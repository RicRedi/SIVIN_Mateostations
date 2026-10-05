"""Thermal-time accumulation shared by growing degree-days and the phenology models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from sivin.analytics.thermal.formulas import degree_days

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ThermalTimeCurve:
    """Cumulative thermal time from the first day of a period.

    Attributes
    ----------
    cumulative_c_d : pandas.Series
        Cumulative degree-days in °C·d after each local date (index), increasing. Days that
        are missing from the input (incomplete days) are missing here too.
    """

    cumulative_c_d: pd.Series

    @property
    def total_c_d(self) -> float:
        """Degree-days accumulated over all days in °C·d (0 for an empty curve)."""
        return float(self.cumulative_c_d.iloc[-1]) if len(self.cumulative_c_d) else 0.0

    def date_reached(self, f_star_c_d: float) -> date | None:
        """Return the first local date on which the sum reaches a critical value.

        Parameters
        ----------
        f_star_c_d : float
            Critical thermal sum :math:`F^*` in °C·d.

        Returns
        -------
        datetime.date or None
            First date with ``cumulative >= f_star_c_d``; ``None`` if it is not reached.
        """
        reached = self.cumulative_c_d.index[self.cumulative_c_d >= f_star_c_d]
        return reached[0] if len(reached) else None


@dataclass(frozen=True, slots=True)
class ThermalTimeModel:
    r"""Accumulation :math:`\sum_d \max(0, T_d - T_{base})` over the days given to it.

    The caller selects the days (period start, complete days); the model only sums.

    Attributes
    ----------
    base_temp_c : float
        Base temperature :math:`T_{base}` in °C.
    """

    base_temp_c: float

    def accumulate(self, mean_temp_c: pd.Series) -> ThermalTimeCurve:
        """Accumulate daily degree-days.

        Parameters
        ----------
        mean_temp_c : pandas.Series
            Daily mean temperature in °C indexed by increasing local date; ``NaN`` days are
            skipped.

        Returns
        -------
        ThermalTimeCurve
            Cumulative degree-days in °C·d.
        """
        valid = mean_temp_c.dropna()
        cumulative = degree_days(valid, self.base_temp_c).cumsum()
        return ThermalTimeCurve(cumulative.rename("cumulative_c_d"))
