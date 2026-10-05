"""Tests of the validation report, settings, rule registry and validator (synthetic data)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sivin.core.ids import SensorId
from sivin.ingest.validation import (
    ExportInspection,
    HumidityBoundsRule,
    InputValidator,
    Severity,
    TableInspection,
    TableRule,
    TimeColumn,
    ValidationIssue,
    ValidationReport,
    ValidationRule,
    ValidationRuleRegistry,
    ValidationSettings,
    ValueColumn,
    validation_rules,
)

SOURCE = Path("MeteoData_8615620 77678271.csv")

EXPECTED_RULES = (
    "file-exists",
    "file-not-empty",
    "file-readable",
    "expected-tables",
    "sensor-id",
    "required-columns",
    "data-rows",
    "short-rows",
    "numbers-parseable",
    "timestamps-parseable",
    "values-present",
    "date-order",
    "timestamps-plausible",
    "row-order",
    "out-of-sequence",
    "duplicate-timestamps",
    "backward-steps",
    "daylight-saving",
    "temperature-bounds",
    "humidity-bounds",
    "humidity-fraction",
)


def table(temp: list[float], rh: list[float]) -> TableInspection:
    """A parsed table with hourly UTC timestamps and the given values."""
    n_rows = len(temp)
    local = pd.Series(pd.date_range("2026-01-01", periods=n_rows, freq="h"))
    no = np.zeros(n_rows, dtype=np.bool_)
    return TableInspection(
        name="t",
        sensor_id=SensorId("77678271"),
        header_row=1,
        source_rows=np.arange(2, n_rows + 2, dtype=np.int64),
        times=TimeColumn(
            "Datum", local, local.dt.tz_localize("UTC"), no, no.copy(), no.copy(), no.copy()
        ),
        temp=ValueColumn("T", np.array(temp), no.copy()),
        rh=ValueColumn("RH", np.array(rh), no.copy()),
    )


def test_issue_and_report() -> None:
    error = ValidationIssue("a", Severity.ERROR, "bad", row=3, table="8271")
    warning = ValidationIssue("b", Severity.WARNING, "hm")
    assert str(error) == "ERROR a [8271] row 3: bad"
    assert str(warning) == "WARNING b: hm"
    report = ValidationReport((error, warning))
    assert not report.is_acceptable
    assert report.errors == (error,)
    assert report.warnings == (warning,)
    assert report.rules() == {"a", "b"}
    assert report.rules(Severity.WARNING) == {"b"}
    assert report.summary() == "ERROR a [8271] row 3: bad\nWARNING b: hm"
    assert ValidationReport().summary() == "no findings"
    assert ValidationReport((warning,)).is_acceptable


def test_settings_validation() -> None:
    assert ValidationSettings().temp_min_c == -60.0
    with pytest.raises(ValidationError, match="temp_min_c"):
        ValidationSettings(temp_min_c=80.0)
    with pytest.raises(ValidationError, match="rh_min_pct"):
        ValidationSettings(rh_min_pct=100.0)
    with pytest.raises(ValidationError, match="Extra inputs"):
        ValidationSettings(max_share=0.1)  # type: ignore[call-arg]


def test_registry_holds_every_rule_in_order() -> None:
    assert validation_rules.ids() == EXPECTED_RULES
    assert len(validation_rules) == len(EXPECTED_RULES)
    assert InputValidator().rule_ids == EXPECTED_RULES


def test_registry_errors() -> None:
    registry = ValidationRuleRegistry()
    registry.register(HumidityBoundsRule)
    assert registry.classes() == (HumidityBoundsRule,)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(HumidityBoundsRule)
    with pytest.raises(TypeError, match="Only ValidationRule"):
        registry.register(str)  # type: ignore[type-var]
    with pytest.raises(TypeError, match="abstract"):
        registry.register(TableRule)  # type: ignore[type-abstract]

    class Nameless(HumidityBoundsRule):
        rule_id = ""

    with pytest.raises(TypeError, match="rule_id"):
        registry.register(Nameless)


def test_validator_with_custom_rules() -> None:
    class Always(ValidationRule):
        rule_id = "always"

        def check(self, inspection: ExportInspection) -> Iterator[ValidationIssue]:
            yield self._issue(Severity.WARNING, f"{inspection.source.name} seen")

    settings = ValidationSettings(max_out_of_bounds_share=0.5)
    validator = InputValidator(settings, [Always(settings)])
    assert validator.settings is settings
    report = validator.validate(ExportInspection(SOURCE, size_bytes=None))
    assert report.issues == (
        ValidationIssue("always", Severity.WARNING, "MeteoData_8615620 77678271.csv seen"),
    )


def test_table_rules_skip_unreadable_files() -> None:
    inspection = ExportInspection(SOURCE, 10, read_problem="broken", tables=(table([99], [5]),))
    report = InputValidator().validate(inspection)
    assert report.rules() == {"file-readable"}


def test_clean_table_has_no_findings() -> None:
    inspection = ExportInspection(SOURCE, 10, tables=(table([1.0, 2.0], [50.0, 60.0]),))
    assert InputValidator().validate(inspection) == ValidationReport()


def test_bounds_share_decides_the_severity() -> None:
    values = [1.0] * 19 + [150.0]
    small = InputValidator().validate(
        ExportInspection(SOURCE, 10, tables=(table(values, [50] * 20),))
    )
    (issue,) = small.issues
    assert issue.severity is Severity.WARNING
    assert issue.row == 21
    assert issue.message == (
        "1 temperature value(s) outside [-60, 70] °C (5.0% of present values, limit 5.0%)."
    )
    rh = [50.0] * 16 + [-1.0, 101.0, 102.0, 103.0]
    large = InputValidator().validate(ExportInspection(SOURCE, 10, tables=(table([1.0] * 20, rh),)))
    (issue,) = large.issues
    assert (issue.rule, issue.severity) == ("humidity-bounds", Severity.ERROR)
    assert "20.0% of present values" in issue.message


@pytest.mark.parametrize(
    ("n_bad", "n_rows", "severity"),
    [
        (3, 10, Severity.WARNING),  # 30 % but only min_error_rows (3) rows
        (4, 10, Severity.ERROR),
        (2, 2, Severity.ERROR),  # all rows
        (1, 30, Severity.WARNING),
    ],
)
def test_short_tables_need_more_than_min_error_rows(
    n_bad: int, n_rows: int, severity: Severity
) -> None:
    temp = [99.0] * n_bad + [1.0] * (n_rows - n_bad)
    inspection = ExportInspection(SOURCE, 10, tables=(table(temp, [50.0] * n_rows),))
    (issue,) = InputValidator().validate(inspection).issues
    assert issue.severity is severity


def test_values_present() -> None:
    nan = float("nan")
    one = InputValidator().validate(
        ExportInspection(SOURCE, 10, tables=(table([1.0, 2.0], [nan, nan]),))
    )
    (issue,) = one.issues
    assert (issue.rule, issue.severity) == ("values-present", Severity.WARNING)
    assert issue.message == (
        "Column(s) 'RH' contain no value in 2 data row(s) "
        "(empty cells, or formulas without cached results)."
    )
    none = InputValidator().validate(ExportInspection(SOURCE, 10, tables=(table([nan], [nan]),)))
    assert none.rules(Severity.ERROR) == {"values-present"}


def test_missing_sensor_without_reason() -> None:
    nameless = TableInspection(name="x", sensor_id=None, header_search_rows=5)
    report = InputValidator().validate(ExportInspection(SOURCE, 10, tables=(nameless,)))
    assert [issue.message for issue in report.issues] == [
        "The sensor cannot be resolved: no sensor id",
        "No header row with a timestamp column in the first 5 rows.",
    ]


def test_first_row() -> None:
    inspection = table([1.0, 2.0, 3.0], [50.0] * 3)
    assert inspection.first_row([False, True, True]) == 3
    assert inspection.first_row([False] * 3) is None
    assert inspection.n_data_rows == 3
