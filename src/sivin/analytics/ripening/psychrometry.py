"""Pure psychrometric formulas: dew point (Magnus form) and vapour pressure deficit (FAO-56).

All functions are element-wise on NumPy arrays (scalars work too) and have no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

from sivin.analytics.ripening.durations import FloatArray

PERCENT: Final = 100.0
"""Relative humidity of a saturated air mass in %."""


@dataclass(frozen=True, slots=True)
class MagnusCoefficients:
    """Coefficients of the Magnus form ``e_s(T) = c * exp(a * T / (b + T))`` over water.

    Only ``a`` and ``b`` enter the dew point; the prefactor ``c`` cancels.

    Parameters
    ----------
    a : float
        Dimensionless coefficient.
    b_c : float
        Coefficient in °C.

    Raises
    ------
    ValueError
        If a coefficient is not positive.
    """

    a: float
    b_c: float

    def __post_init__(self) -> None:
        if self.a <= 0 or self.b_c <= 0:
            raise ValueError(f"Magnus coefficients must be positive, got a={self.a}, b={self.b_c}.")


ALDUCHOV_ESKRIDGE_1996: Final = MagnusCoefficients(a=17.625, b_c=243.04)
"""Magnus coefficients recommended by Alduchov and Eskridge (1996) (AERK form, over water)."""

LEGACY_MAGNUS: Final = MagnusCoefficients(a=17.27, b_c=237.7)
"""Coefficients of the legacy ``vineyard_analyst.py``, kept for comparison with old results."""

FAO56_E0_KPA: Final = 0.6108
"""Saturation vapour pressure at 0 °C in kPa (Allen et al., 1998, FAO-56 eq. 11)."""

FAO56_A: Final = 17.27
"""Dimensionless coefficient of FAO-56 eq. 11 (Allen et al., 1998)."""

FAO56_B_C: Final = 237.3
"""Coefficient in °C of FAO-56 eq. 11 (Allen et al., 1998)."""


def dew_point_c(
    temp_c: npt.ArrayLike,
    rh_pct: npt.ArrayLike,
    coefficients: MagnusCoefficients = ALDUCHOV_ESKRIDGE_1996,
) -> FloatArray:
    """Dew-point temperature from air temperature and relative humidity (Magnus form).

    .. math::

        \\gamma = \\ln\\left(\\frac{RH}{100}\\right) + \\frac{a T}{b + T}, \\qquad
        T_d = \\frac{b\\,\\gamma}{a - \\gamma}

    Parameters
    ----------
    temp_c : array_like of float
        Air temperature in °C.
    rh_pct : array_like of float
        Relative humidity in %.
    coefficients : MagnusCoefficients, optional
        ``a`` and ``b``; Alduchov and Eskridge (1996) by default.

    Returns
    -------
    numpy.ndarray of float
        Dew point in °C. ``NaN`` where an input is ``NaN`` and where ``RH <= 0`` (the logarithm
        is undefined; such values are sensor errors, see :func:`non_positive_humidity`).
    """
    temp = np.asarray(temp_c, dtype=np.float64)
    rh = np.asarray(rh_pct, dtype=np.float64)
    usable = rh > 0
    safe_rh = np.where(usable, rh, np.nan)
    a, b = coefficients.a, coefficients.b_c
    gamma = np.log(safe_rh / PERCENT) + a * temp / (b + temp)
    return np.asarray(b * gamma / (a - gamma), dtype=np.float64)


def non_positive_humidity(rh_pct: npt.ArrayLike) -> npt.NDArray[np.bool_]:
    """Flag relative humidities for which the dew point is undefined.

    Parameters
    ----------
    rh_pct : array_like of float
        Relative humidity in %.

    Returns
    -------
    numpy.ndarray of bool
        ``True`` where ``RH <= 0`` (``NaN`` gives ``False``).
    """
    return np.asarray(np.asarray(rh_pct, dtype=np.float64) <= 0, dtype=np.bool_)


def saturation_vapour_pressure_kpa(temp_c: npt.ArrayLike) -> FloatArray:
    """Saturation vapour pressure over water (Allen et al., 1998, FAO-56 eq. 11).

    .. math:: e_s(T) = 0.6108 \\exp\\left(\\frac{17.27\\,T}{T + 237.3}\\right)

    Parameters
    ----------
    temp_c : array_like of float
        Air temperature in °C.

    Returns
    -------
    numpy.ndarray of float
        Saturation vapour pressure in kPa.
    """
    temp = np.asarray(temp_c, dtype=np.float64)
    return np.asarray(FAO56_E0_KPA * np.exp(FAO56_A * temp / (temp + FAO56_B_C)), dtype=np.float64)


def vapour_pressure_deficit_kpa(temp_c: npt.ArrayLike, rh_pct: npt.ArrayLike) -> FloatArray:
    """Vapour pressure deficit from temperature and relative humidity (FAO-56).

    .. math:: e_a = e_s(T) \\frac{RH}{100}, \\qquad VPD = e_s(T) - e_a

    Parameters
    ----------
    temp_c : array_like of float
        Air temperature in °C.
    rh_pct : array_like of float
        Relative humidity in %.

    Returns
    -------
    numpy.ndarray of float
        VPD in kPa. ``NaN`` where an input is ``NaN`` or ``RH < 0`` (impossible value).
        ``RH > 100 %`` gives a negative VPD and is passed through unchanged.
    """
    rh = np.asarray(rh_pct, dtype=np.float64)
    safe_rh = np.where(rh >= 0, rh, np.nan)
    e_s = saturation_vapour_pressure_kpa(temp_c)
    return np.asarray(e_s * (1.0 - safe_rh / PERCENT), dtype=np.float64)
