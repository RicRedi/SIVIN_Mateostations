"""Tests of StorageConfig and build_store."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sivin.core.schema import MeasurementSeries
from sivin.storage.config import StorageConfig, build_store
from sivin.storage.errors import MeasurementConflictError

from .conftest import UtcSeriesFactory


def test_defaults() -> None:
    config = StorageConfig()
    assert config.conflict_policy == "prefer_newest"
    assert config.partitioning == "year"


def test_explicit_valid_values() -> None:
    values = {"conflict_policy": "prefer_existing", "partitioning": "year"}
    config = StorageConfig.model_validate(values)
    assert config.model_dump() == values


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"conflict_policy": "newest"}, "unknown conflict policy 'newest'"),
        ({"partitioning": "month"}, "unknown partitioning 'month'"),
        ({"conflict": "raise"}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_values_are_rejected(values: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        StorageConfig.model_validate(values)


def test_every_field_has_a_description() -> None:
    assert all(field.description for field in StorageConfig.model_fields.values())


def test_build_store_uses_configured_policy(
    tmp_path: Path, make_utc_series: UtcSeriesFactory
) -> None:
    store = build_store(tmp_path, StorageConfig(conflict_policy="raise"))
    assert store.root == tmp_path
    series: MeasurementSeries = make_utc_series(["2026-01-01T00:00:00Z"], [1.0], [2.0])
    store.append(series)
    with pytest.raises(MeasurementConflictError):
        store.append(make_utc_series(["2026-01-01T00:00:00Z"], [1.5], [2.0]))
