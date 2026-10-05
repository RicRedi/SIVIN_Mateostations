"""Pure formulas of the thermal indices, vectorised over daily values.

Each function computes the daily contribution of one index from daily temperatures. The index
classes select the period and the complete days and sum or average the contributions.
"""

from __future__ import annotations

import logging
from typing import Final

import pandas as pd

logger = logging.getLogger(__name__)

FAHRENHEIT_DEGREE_IN_CELSIUS: Final = 5.0 / 9.0
"""Size of one Fahrenheit degree in Celsius degrees (exact by definition of the scales)."""


def degree_days(mean_temp_c: pd.Series, base_temp_c: float) -> pd.Series:
    r"""Daily degree-days :math:`\max(0, T_{mean} - T_{base})`.

    Parameters
    ----------
    mean_temp_c : pandas.Series
        Daily mean temperature in °C.
    base_temp_c : float
        Base temperature in °C.

    Returns
    -------
    pandas.Series
        Degree-days in °C·d per day, never negative.
    """
    return (mean_temp_c - base_temp_c).clip(lower=0.0)


def huglin_daily(
    mean_temp_c: pd.Series, max_temp_c: pd.Series, base_temp_c: float, k: float
) -> pd.Series:
    r"""Daily Huglin contribution :math:`K \max(0, ((T_{mean} - b) + (T_{max} - b)) / 2)`.

    Parameters
    ----------
    mean_temp_c : pandas.Series
        Daily mean temperature in °C.
    max_temp_c : pandas.Series
        Daily maximum temperature in °C.
    base_temp_c : float
        Base temperature :math:`b` in °C (10 °C in Huglin, 1978).
    k : float
        Day-length (latitude) coefficient, dimensionless.

    Returns
    -------
    pandas.Series
        Contribution in °C·d per day, never negative.
    """
    excess_c = ((mean_temp_c - base_temp_c) + (max_temp_c - base_temp_c)) / 2.0
    return excess_c.clip(lower=0.0) * k


def dtr_adjustment(dtr_c: pd.Series, lower_c: float, upper_c: float, factor: float) -> pd.Series:
    r"""Diurnal-temperature-range adjustment of the BEDD daily contribution.

    .. math::

        A = f \, (\max(0, \mathrm{DTR} - u) - \max(0, l - \mathrm{DTR}))

    i.e. ``f (DTR - u)`` above the upper threshold, ``f (DTR - l)`` below the lower one and
    zero between them.

    Parameters
    ----------
    dtr_c : pandas.Series
        Diurnal temperature range :math:`T_{max} - T_{min}` in °C.
    lower_c, upper_c : float
        Range in °C within which no adjustment applies.
    factor : float
        Adjustment per °C of range outside the band, in °C·d/°C.

    Returns
    -------
    pandas.Series
        Adjustment in °C·d per day (positive above ``upper_c``, negative below ``lower_c``).
    """
    above_c = (dtr_c - upper_c).clip(lower=0.0)
    below_c = (lower_c - dtr_c).clip(lower=0.0)
    return factor * (above_c - below_c)


def bedd_daily(
    mean_temp_c: pd.Series,
    dtr_c: pd.Series,
    *,
    base_temp_c: float,
    cap_c_d: float,
    day_length_coefficient: float,
    dtr_lower_c: float,
    dtr_upper_c: float,
    dtr_factor: float,
) -> pd.Series:
    r"""Daily biologically effective degree-days.

    .. math::

        \mathrm{BEDD}_d = \min\!\left(c, \max\!\left(0,
            k \max(0, T_{mean} - b) + A(\mathrm{DTR})\right)\right)

    Parameters
    ----------
    mean_temp_c : pandas.Series
        Daily mean temperature in °C.
    dtr_c : pandas.Series
        Diurnal temperature range in °C.
    base_temp_c : float
        Base temperature :math:`b` in °C.
    cap_c_d : float
        Upper limit :math:`c` of the daily contribution in °C·d.
    day_length_coefficient : float
        Day-length coefficient :math:`k`, dimensionless (1 = no adjustment).
    dtr_lower_c, dtr_upper_c, dtr_factor : float
        Parameters of :func:`dtr_adjustment`.

    Returns
    -------
    pandas.Series
        Contribution in °C·d per day, within ``[0, cap_c_d]``.
    """
    adjustment = dtr_adjustment(dtr_c, dtr_lower_c, dtr_upper_c, dtr_factor)
    raw = day_length_coefficient * degree_days(mean_temp_c, base_temp_c) + adjustment
    return raw.clip(lower=0.0, upper=cap_c_d)


def fahrenheit_to_celsius_degree_days(degree_days_f_d: float) -> float:
    """Convert a degree-day sum from °F·d to °C·d.

    A temperature *difference* of 1 °F equals 5/9 °C, so a sum of differences converts with
    the same factor (no offset).

    Parameters
    ----------
    degree_days_f_d : float
        Degree-days in °F·d.

    Returns
    -------
    float
        Degree-days in °C·d.
    """
    return degree_days_f_d * FAHRENHEIT_DEGREE_IN_CELSIUS
