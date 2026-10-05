"""Tests of QcFlag (MIGRATION_PLAN §2.7)."""

from __future__ import annotations

import numpy as np

from sivin.core.flags import QcFlag, excluded, is_excluded


def test_bit_values_match_the_contract() -> None:
    expected = {
        "OK": 0,
        "MISSING": 1,
        "OUT_OF_RANGE": 2,
        "SPIKE": 4,
        "STEP": 8,
        "STUCK": 16,
        "PRE_DEPLOYMENT": 32,
        "NEIGHBOR_OUTLIER": 64,
        "TIMESTAMP_SUSPECT": 128,
        "MANUAL_EXCLUDE": 256,
    }
    assert {name: int(QcFlag[name]) for name in expected} == expected


def test_default_exclude_is_the_excluding_flags_of_the_plan() -> None:
    # 1 + 2 + 4 + 16 + 32 + 256 = 311
    assert int(QcFlag.DEFAULT_EXCLUDE) == 311
    for informative in (QcFlag.STEP, QcFlag.NEIGHBOR_OUTLIER, QcFlag.TIMESTAMP_SUSPECT):
        assert not QcFlag.DEFAULT_EXCLUDE & informative


def test_all_bits() -> None:
    assert QcFlag.all_bits() == 511


def test_is_excluded() -> None:
    mask = int(QcFlag.DEFAULT_EXCLUDE)
    assert not is_excluded(0, mask)
    assert not is_excluded(QcFlag.STEP | QcFlag.TIMESTAMP_SUSPECT, mask)
    assert is_excluded(QcFlag.STEP | QcFlag.SPIKE, mask)
    assert not is_excluded(QcFlag.SPIKE, 0)


def test_excluded_is_vectorised() -> None:
    flags = np.array([0, 8, 4, 136, 256], dtype=np.int32)
    result = excluded(flags, QcFlag.DEFAULT_EXCLUDE)
    assert result.dtype == np.bool_
    assert result.tolist() == [False, False, True, False, True]
