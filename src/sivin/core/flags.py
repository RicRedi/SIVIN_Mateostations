"""Quality-control flags attached to every measurement (MIGRATION_PLAN §2.7).

Each measurement row carries an ``int32`` bit field in the ``qc`` column. A value of ``0`` means
"no finding"; every set bit is one finding of a quality check. Some findings exclude the sample
from climate indices, others are informative only; which ones exclude is decided by an
*exclusion mask* taken from the configuration (``analytics.exclude_mask``).
"""

from __future__ import annotations

import enum

import numpy as np
import numpy.typing as npt


class QcFlag(enum.IntFlag):
    """Bit flags describing quality-control findings of a single sample.

    The bit values are part of the data contract (MIGRATION_PLAN §2.7) and must never change,
    because they are persisted in the measurement store and in the static site data.

    Attributes
    ----------
    OK
        No finding.
    MISSING
        The value is missing. Excluded from indices by default.
    OUT_OF_RANGE
        Outside the physical or climatological range. Excluded by default.
    SPIKE
        Isolated excursion that returns to the previous level. Excluded by default.
    STEP
        Sudden persistent level shift. Informative.
    STUCK
        Stuck value (persistence check). Excluded by default.
    PRE_DEPLOYMENT
        Recorded before the sensor was deployed in the vineyard (office, transport).
        Excluded by default.
    NEIGHBOR_OUTLIER
        Disagrees with neighbouring sensors. Informative.
    TIMESTAMP_SUSPECT
        Ambiguous local time (daylight-saving transition) or irregular sampling step.
        Informative.
    MANUAL_EXCLUDE
        Excluded manually by the owner. Excluded by default.
    DEFAULT_EXCLUDE
        Composite: the flags marked "excludes from indices" in MIGRATION_PLAN §2.7. It is the
        default of ``analytics.exclude_mask`` in the configuration.
    """

    OK = 0
    MISSING = 1
    OUT_OF_RANGE = 2
    SPIKE = 4
    STEP = 8
    STUCK = 16
    PRE_DEPLOYMENT = 32
    NEIGHBOR_OUTLIER = 64
    TIMESTAMP_SUSPECT = 128
    MANUAL_EXCLUDE = 256

    DEFAULT_EXCLUDE = MISSING | OUT_OF_RANGE | SPIKE | STUCK | PRE_DEPLOYMENT | MANUAL_EXCLUDE

    @classmethod
    def all_bits(cls) -> int:
        """Return the union of all defined flag bits.

        Returns
        -------
        int
            Bit mask with every defined flag set; any other bit in a ``qc`` value is invalid.
        """
        mask = 0
        for flag in cls:
            mask |= int(flag)
        return mask


def is_excluded(flags: int, mask: int) -> bool:
    """Tell whether a single sample is excluded by an exclusion mask.

    Parameters
    ----------
    flags : int
        The sample's ``qc`` bit field.
    mask : int
        Exclusion mask, e.g. ``QcFlag.DEFAULT_EXCLUDE``.

    Returns
    -------
    bool
        ``True`` if at least one flag of ``flags`` is also set in ``mask``.
    """
    return (int(flags) & int(mask)) != 0


def excluded(flags: npt.ArrayLike, mask: int) -> npt.NDArray[np.bool_]:
    """Vectorised :func:`is_excluded` for an array of ``qc`` values.

    Parameters
    ----------
    flags : array_like of int
        ``qc`` bit fields, one per sample.
    mask : int
        Exclusion mask, e.g. ``QcFlag.DEFAULT_EXCLUDE``.

    Returns
    -------
    numpy.ndarray of bool
        ``True`` where the sample is excluded.
    """
    values = np.asarray(flags, dtype=np.int64)
    return np.asarray(np.bitwise_and(values, np.int64(int(mask))) != 0, dtype=np.bool_)
