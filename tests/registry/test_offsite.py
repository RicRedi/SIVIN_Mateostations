"""Tests of the off-site log (MIGRATION_PLAN §2.8). All periods and sensors here are SYNTHETIC.

Expected UTC instants are computed by hand from the Europe/Prague rules: CET = UTC+1 in winter,
CEST = UTC+2 from the last Sunday of March 02:00 to the last Sunday of October 03:00
(2026-03-29 and 2026-10-25).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from tests.registry.conftest import SensorFactory

from sivin.core.ids import SensorId
from sivin.core.schema import MeasurementSeries
from sivin.registry.geojson import GeoJsonRegistryStore
from sivin.registry.offsite import (
    JSON_SCHEMA_DIALECT,
    TIME_TEXT_PATTERN,
    TIMEZONE_CONTEXT_KEY,
    BlankValue,
    LocalTimeReader,
    OffSiteLog,
    OffSiteLogError,
    OffSiteLogSettings,
    OffSiteLogStore,
    OffSitePeriod,
    build_json_schema,
    format_local,
    format_local_iso,
    render_json_schema,
)
from sivin.registry.registry import SensorRegistry

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = ROOT / "sensors" / "offsite_log.schema.json"
LOG_FILE = ROOT / "sensors" / "offsite_log.yaml"
OFFICE = SensorId("77799986")
FIELD = SensorId("77678271")


@pytest.fixture
def registry(make_sensor: SensorFactory) -> SensorRegistry:
    return SensorRegistry([make_sensor(str(OFFICE)), make_sensor(str(FIELD))])


@pytest.fixture
def store() -> OffSiteLogStore:
    return OffSiteLogStore()


def _entry(
    sensor: str = str(OFFICE),
    start: str = "2025-12-17 12:00",
    end: str | None = "2026-03-15 09:00",
    reason: str = "office",
    note: str | None = None,
) -> str:
    to = "null" if end is None else f'"{end}"'
    lines = [
        f'  - sensor: "{sensor}"',
        f'    from: "{start}"',
        f"    to: {to}",
        f"    reason: {reason}",
    ]
    if note is not None:
        lines.append(f'    note: "{note}"')
    return "\n".join(lines)


def _log_text(*entries: str) -> str:
    return "entries:\n" + "\n".join(entries) + "\n"


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)  # type: ignore[misc]


def _period(**values: object) -> OffSitePeriod:
    return OffSitePeriod.model_validate(
        {"sensor": str(OFFICE), "to": None, "reason": "office", **values}
    )


class TestSchemaAndCommittedFile:
    def test_committed_schema_is_in_sync(self) -> None:
        # Regenerate with:
        # .venv/bin/python -c "from sivin.registry.offsite import render_json_schema as r; \
        #   open('sensors/offsite_log.schema.json', 'w', encoding='utf-8').write(r())"
        assert SCHEMA_FILE.read_text(encoding="utf-8") == render_json_schema()

    def test_schema_uses_file_keys(self) -> None:
        schema = build_json_schema()
        assert schema["$schema"] == JSON_SCHEMA_DIALECT
        assert schema["required"] == ["entries"]
        period = schema["$defs"]["OffSitePeriod"]
        assert list(period["properties"]) == ["sensor", "from", "to", "reason", "note"]
        assert period["required"] == ["sensor", "from", "to", "reason"]
        assert period["additionalProperties"] is False
        assert period["properties"]["reason"]["enum"] == [
            "office",
            "service",
            "transport",
            "storage",
            "other",
        ]
        assert "?P<" not in period["properties"]["from"]["pattern"]
        assert json.loads(render_json_schema()) == schema

    def test_committed_log_holds_the_q10_entry(self, store: OffSiteLogStore) -> None:
        # Owner decision Q10 (2026-10-05): 77799986 was off site for the whole real export.
        registry = GeoJsonRegistryStore().load(ROOT / "sensors" / "sensors.geojson")
        log = store.load(LOG_FILE, registry)
        assert log.sensors() == (OFFICE,)
        (period,) = log.periods_for(OFFICE)
        assert period.from_utc == _utc(2025, 7, 30, 8, 0)  # 10:00 CEST
        assert period.to_utc == _utc(2026, 3, 1, 21, 30)  # 22:30 CET
        assert period.reason == "service"
        assert period.note is not None
        assert period.note.startswith("Derived from the real export")

    def test_q10_entry_covers_the_real_export(self, store: OffSiteLogStore) -> None:
        # First and last sample of the real export: 2025-07-30 10:22 and 2026-03-01 22:27 local.
        registry = GeoJsonRegistryStore().load(ROOT / "sensors" / "sensors.geojson")
        log = store.load(LOG_FILE, registry)
        assert log.is_off_site(OFFICE, pd.Timestamp("2025-07-30 10:22", tz="Europe/Prague"))
        assert log.is_off_site(OFFICE, pd.Timestamp("2026-03-01 22:27", tz="Europe/Prague"))
        assert not log.is_off_site(OFFICE, pd.Timestamp("2026-03-01 22:30", tz="Europe/Prague"))

    def test_uncommenting_the_example_is_harmless(self, store: OffSiteLogStore) -> None:
        registry = GeoJsonRegistryStore().load(ROOT / "sensors" / "sensors.geojson")
        text = LOG_FILE.read_text(encoding="utf-8")
        uncommented = re.sub(r"(?m)^  # (?=- |  )", "  ", text)
        assert uncommented != text
        log = store.loads(uncommented, registry)
        assert len(log) == 2
        (example,) = log.periods_for(FIELD)
        # A closed period in the year 2000: no data exist then, nothing is excluded.
        assert example.to_utc is not None
        assert example.to_utc < _utc(2001, 1, 1)

    def test_uncommenting_every_comment_line_fails_loudly(self, store: OffSiteLogStore) -> None:
        registry = GeoJsonRegistryStore().load(ROOT / "sensors" / "sensors.geojson")
        text = LOG_FILE.read_text(encoding="utf-8")
        with pytest.raises(OffSiteLogError):
            store.loads(re.sub(r"(?m)^(\s*)# ?", r"\1", text), registry)


class TestTimes:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2025-12-17 12:00", _utc(2025, 12, 17, 11, 0)),  # CET, UTC+1
            ("2026-07-01 12:00", _utc(2026, 7, 1, 10, 0)),  # CEST, UTC+2
            ("2026-07-01T12:00", _utc(2026, 7, 1, 10, 0)),
            ("2026-07-01 12:00:30", _utc(2026, 7, 1, 10, 0, 30)),
            ("2026-07-01T12:00+02:00", _utc(2026, 7, 1, 10, 0)),
            ("2026-07-01T12:00Z", _utc(2026, 7, 1, 12, 0)),
            ("2026-07-01 12:00-03:30", _utc(2026, 7, 1, 15, 30)),
            ("2026-03-29 01:59", _utc(2026, 3, 29, 0, 59)),  # last minute of CET
            ("2026-03-29 03:00", _utc(2026, 3, 29, 1, 0)),  # first minute of CEST
            ("2026-10-25 01:59", _utc(2026, 10, 24, 23, 59)),  # still CEST
            ("2026-10-25 03:00", _utc(2026, 10, 25, 2, 0)),  # CET again
        ],
    )
    def test_text_is_read_as_utc(self, text: str, expected: datetime) -> None:
        assert LocalTimeReader("Europe/Prague").read(text) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 1, 10, 8, 0), _utc(2026, 1, 10, 7, 0)),
            (
                datetime(2026, 1, 10, 8, 0, tzinfo=timezone(timedelta(hours=3))),
                _utc(2026, 1, 10, 5, 0),
            ),
        ],
    )
    def test_datetimes_from_unquoted_yaml(self, value: datetime, expected: datetime) -> None:
        assert LocalTimeReader("Europe/Prague").read(value) == expected

    def test_ambiguous_local_time_asks_for_an_offset(self) -> None:
        with pytest.raises(ValueError, match="ambiguous") as error:
            LocalTimeReader("Europe/Prague").read("2026-10-25 02:30")
        message = str(error.value)
        assert "explicit offset" in message
        assert "'2026-10-25T02:30+02:00' for the first one (summer time)" in message
        assert "'2026-10-25T02:30+01:00' for the second one (winter time)" in message

    def test_nonexistent_local_time_suggests_one_offset(self) -> None:
        with pytest.raises(ValueError, match=r"does not exist.*time after the change") as error:
            LocalTimeReader("Europe/Prague").read("2026-03-29 02:30")
        assert "'2026-03-29T02:30+01:00'" in str(error.value)
        assert "+02:00" not in str(error.value)

    def test_explicit_offsets_resolve_the_repeated_hour(self) -> None:
        reader = LocalTimeReader("Europe/Prague")
        assert reader.read("2026-10-25T02:30+02:00") == _utc(2026, 10, 25, 0, 30)
        assert reader.read("2026-10-25T02:30+01:00") == _utc(2026, 10, 25, 1, 30)

    @pytest.mark.parametrize(
        ("value", "match"),
        [
            (date(2026, 1, 10), "no time of day"),
            ("2026-01-10", "must be local"),
            ("10.1.2026 12:00", "must be local"),
            ("2026-02-30 12:00", "not a valid calendar date"),
            (12, "expected a time as text"),
        ],
    )
    def test_invalid_values(self, value: object, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            LocalTimeReader("Europe/Prague").read(value)

    def test_unknown_zone(self) -> None:
        with pytest.raises(ValueError, match="unknown IANA time zone"):
            LocalTimeReader("Mars/Olympus")

    def test_zone_comes_from_the_validation_context(self) -> None:
        period = OffSitePeriod.model_validate(
            {"sensor": str(OFFICE), "from": "2026-07-01 12:00", "to": None, "reason": "office"},
            context={TIMEZONE_CONTEXT_KEY: "Europe/London"},
        )
        assert period.from_utc == _utc(2026, 7, 1, 11, 0)
        assert LocalTimeReader("Europe/London").timezone == "Europe/London"

    def test_pattern_accepts_what_the_reader_accepts(self) -> None:
        pattern = re.compile(TIME_TEXT_PATTERN)
        assert pattern.fullmatch("2025-12-17 12:00")
        assert pattern.fullmatch("2025-12-17T11:00:00.5Z")
        assert not pattern.fullmatch("2025-12-17")


class TestPeriod:
    def test_fields_and_serialisation(self) -> None:
        period = _period(**{"from": "2026-07-01 12:00", "to": "2026-07-03 08:00"}, note="x")
        assert period.sensor == OFFICE
        assert period.to_utc == _utc(2026, 7, 3, 6, 0)
        assert not period.is_open
        assert period.detail == "office: x"
        assert period.model_dump(mode="json") == {
            "sensor": "77799986",
            "from": "2026-07-01T10:00:00Z",
            "to": "2026-07-03T06:00:00Z",
            "reason": "office",
            "note": "x",
        }

    def test_any_spelling_of_the_sensor_name(self) -> None:
        assert _period(sensor="8615620 77799986", **{"from": "2026-07-01 12:00"}).sensor == OFFICE
        assert _period(sensor=OFFICE, **{"from": "2026-07-01 12:00"}).sensor == OFFICE

    def test_open_period_and_detail_without_note(self) -> None:
        period = _period(**{"from": "2026-07-01 12:00"}, reason="service")
        assert period.is_open
        assert period.end_ts is None
        assert period.detail == "service"

    @pytest.mark.parametrize("end", ["2026-07-01 12:00", "2026-07-01 11:00"])
    def test_from_must_be_before_to(self, end: str) -> None:
        with pytest.raises(ValidationError, match=r"'from' .* must be before 'to'"):
            _period(**{"from": "2026-07-01 12:00", "to": end})

    def test_to_is_required(self) -> None:
        with pytest.raises(ValidationError, match="to\n  Field required"):
            OffSitePeriod.model_validate(
                {"sensor": str(OFFICE), "from": "2026-07-01 12:00", "reason": "office"}
            )

    @pytest.mark.parametrize(
        ("values", "match"),
        [
            ({"reason": "holiday"}, "reason"),
            ({"sensor": 7779998}, "8-digit serial"),
            ({"sensor": 1.5}, "write the serial in quotes"),
            ({"sensor": "9986"}, "legacy"),
            ({"colour": "red"}, "Extra inputs"),
            ({"note": ""}, "is empty - write a note or delete the line"),
            ({"to": "   "}, "is empty - write a date/time, or 'open'"),
            ({"from": None}, "is empty - write when the sensor left the vineyard"),
        ],
    )
    def test_invalid_entries(self, values: dict[str, object], match: str) -> None:
        with pytest.raises(ValidationError, match=match):
            _period(**{"from": "2026-07-01 12:00", **values})

    def test_contains_is_half_open(self) -> None:
        period = _period(**{"from": "2026-07-01T10:00Z", "to": "2026-07-01T12:00Z"})
        assert not period.contains(pd.Timestamp("2026-07-01T09:59:59Z"))
        assert period.contains(pd.Timestamp("2026-07-01T10:00Z"))
        assert period.contains(_utc(2026, 7, 1, 11, 59))
        assert not period.contains(pd.Timestamp("2026-07-01T12:00Z"))
        with pytest.raises(ValueError, match="timezone-aware"):
            period.contains(datetime(2026, 7, 1, 11))

    def test_overlaps(self) -> None:
        period = _period(**{"from": "2026-07-01T10:00Z", "to": "2026-07-01T12:00Z"})
        t = pd.Timestamp
        assert period.overlaps(t("2026-07-01T09:00Z"), t("2026-07-01T10:00Z"))
        assert not period.overlaps(t("2026-07-01T08:00Z"), t("2026-07-01T09:59Z"))
        assert not period.overlaps(t("2026-07-01T12:00Z"), t("2026-07-01T13:00Z"))
        assert period.overlaps(t("2026-07-01T11:59Z"), t("2026-07-02T00:00Z"))
        still_off = _period(**{"from": "2026-07-01T10:00Z"})
        assert still_off.overlaps(t("2027-01-01T00:00Z"), t("2027-01-02T00:00Z"))


class TestLogRules:
    def test_valid_log(self, registry: SensorRegistry) -> None:
        first = _period(**{"from": "2026-01-01T00:00Z", "to": "2026-01-05T00:00Z"})
        touching = _period(**{"from": "2026-01-05T00:00Z", "to": "2026-01-06T00:00Z"})
        last_open = _period(**{"from": "2026-02-01T00:00Z"})
        other = _period(sensor=str(FIELD), **{"from": "2026-01-02T00:00Z"})
        log = OffSiteLog([last_open, other, touching, first], registry)
        assert len(log) == 4
        assert list(log) == [last_open, other, touching, first]
        assert log.periods_for(OFFICE) == (first, touching, last_open)
        assert log.periods_for(FIELD) == (other,)
        assert log.periods_for(SensorId("11112222")) == ()
        assert log.sensors() == (FIELD, OFFICE)
        assert repr(log) == "OffSiteLog(periods=4, sensors=2)"

    def test_unknown_sensor(self, registry: SensorRegistry) -> None:
        stranger = _period(sensor="12345678", **{"from": "2026-01-01T00:00Z"})
        with pytest.raises(OffSiteLogError) as error:
            OffSiteLog([stranger], registry)
        assert (
            "entry #1, 'sensor': sensor '12345678' is not in sensors/sensors.geojson (known "
            "sensors: 77799986, 77678271); check the serial, or add the sensor to the registry "
            "first"
        ) in str(error.value)

    def test_overlap(self, registry: SensorRegistry) -> None:
        first = _period(**{"from": "2026-01-01T00:00Z", "to": "2026-01-05T00:00Z"})
        second = _period(**{"from": "2026-01-04T23:00Z", "to": "2026-01-06T00:00Z"})
        with pytest.raises(OffSiteLogError) as error:
            OffSiteLog([second, first], registry)
        assert (
            "entry #1, 'from': the period of sensor 77799986 starting 2026-01-05 00:00 CET "
            "(2026-01-04 23:00 UTC) overlaps entry #2 (2026-01-01 01:00 CET (00:00 UTC) - "
            "2026-01-05 01:00 CET (00:00 UTC)); periods of one sensor must not overlap"
        ) in str(error.value)

    def test_periods_of_different_sensors_may_overlap(self, registry: SensorRegistry) -> None:
        first = _period(**{"from": "2026-01-01T00:00Z", "to": "2026-01-05T00:00Z"})
        other = _period(sensor=str(FIELD), **{"from": "2026-01-02T00:00Z", "to": None})
        assert len(OffSiteLog([first, other], registry)) == 2

    def test_open_period_must_be_last(self, registry: SensorRegistry) -> None:
        still_off = _period(**{"from": "2026-01-01T00:00Z"})
        later = _period(**{"from": "2026-02-01T00:00Z", "to": "2026-02-02T00:00Z"})
        pattern = r"entry #1 \(line 2\), 'to': .* open period"
        with pytest.raises(OffSiteLogError, match=pattern) as error:
            OffSiteLog([still_off, later], registry, labels=["entry #1 (line 2)"])
        assert "entry #1 (line 2), 'to'" in str(error.value)
        assert "write the end time into entry #1 (line 2)" in str(error.value)

    def test_two_open_periods(self, registry: SensorRegistry) -> None:
        periods = [
            _period(**{"from": "2026-01-01T00:00Z"}),
            _period(**{"from": "2026-02-01T00:00Z"}),
        ]
        with pytest.raises(OffSiteLogError, match="not its last one"):
            OffSiteLog(periods, registry)

    def test_empty(self) -> None:
        log = OffSiteLog.empty()
        assert len(log) == 0
        assert not log.is_off_site(OFFICE, pd.Timestamp("2026-01-01T00:00Z"))


class TestQueries:
    @pytest.fixture
    def log(self, registry: SensorRegistry) -> OffSiteLog:
        return OffSiteLog(
            [
                _period(**{"from": "2026-07-01T10:00Z", "to": "2026-07-01T11:00Z"}),
                _period(**{"from": "2026-07-01T12:00Z"}),
            ],
            registry,
        )

    def test_is_off_site(self, log: OffSiteLog) -> None:
        t = pd.Timestamp
        assert log.is_off_site(OFFICE, t("2026-07-01T10:00Z"))
        assert not log.is_off_site(OFFICE, t("2026-07-01T11:00Z"))
        assert log.is_off_site(OFFICE, t("2030-01-01T00:00Z"))
        assert not log.is_off_site(FIELD, t("2026-07-01T10:30Z"))

    def test_mask(self, log: OffSiteLog) -> None:
        times = pd.date_range("2026-07-01T09:30Z", periods=7, freq="30min")
        series = MeasurementSeries.from_records(OFFICE, times, np.zeros(7), np.zeros(7))
        # 09:30 10:00 10:30 11:00 11:30 12:00 12:30
        assert log.mask(series).tolist() == [False, True, True, False, False, True, True]
        other = MeasurementSeries.from_records(FIELD, times, np.zeros(7), np.zeros(7))
        assert not log.mask(other).any()
        assert log.mask(MeasurementSeries.empty(OFFICE)).shape == (0,)


class TestStore:
    def test_load_and_name_variants(
        self, store: OffSiteLogStore, registry: SensorRegistry, tmp_path: Path
    ) -> None:
        path = tmp_path / "offsite_log.yaml"
        text = _log_text(
            _entry(sensor="8615620 77799986", note="winter storage in the office"),
            _entry(sensor="77678271 (VUT)", start="2026-03-01 08:00", end=None, reason="service"),
            _entry(sensor="9986", start="2026-03-15 09:00", end=None, reason="storage"),
        )
        path.write_text(text, encoding="utf-8")
        log = store.load(path, registry)
        office = log.periods_for(OFFICE)
        assert [p.from_utc for p in office] == [_utc(2025, 12, 17, 11), _utc(2026, 3, 15, 8)]
        assert office[0].to_utc == _utc(2026, 3, 15, 8)
        assert office[0].note == "winter storage in the office"
        assert log.periods_for(FIELD)[0].from_utc == _utc(2026, 3, 1, 7)

    def test_unquoted_yaml_timestamps(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        text = (
            "entries:\n  - sensor: '77799986'\n    from: 2026-07-01 12:00:00\n"
            "    to: 2026-07-02T12:00:00Z\n    reason: other\n"
        )
        (period,) = store.loads(text, registry)
        assert period.from_utc == _utc(2026, 7, 1, 10)
        assert period.to_utc == _utc(2026, 7, 2, 12)

    def test_timezone_is_configurable(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        (period,) = store.loads(_log_text(_entry(end=None)), registry, "UTC")
        assert period.from_utc == _utc(2025, 12, 17, 12)

    def test_errors_name_entry_and_field(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        text = _log_text(
            _entry(),
            _entry(sensor="12345678"),
            _entry(start="2026-10-25 02:30", end="2026-10-26 08:00"),
            _entry(start="2026-05-01 08:00", end="2026-05-01 08:00"),
            _entry(reason="holiday", start="2027-01-01 00:00"),
        )
        with pytest.raises(OffSiteLogError) as error:
            store.loads(text, registry)
        lines = str(error.value).splitlines()
        assert lines[0] == "Invalid off-site log:"
        # Entries start on lines 2, 6, 10, 14, 18; 'from' is the line after 'sensor'.
        assert lines[1].startswith("  entry #2, 'sensor' (line 6): sensor '12345678' is not in")
        assert lines[2].startswith("  entry #3, 'from' (line 11): local time '2026-10-25 02:30'")
        assert lines[3] == (
            "  entry #4 (line 14): 'from' (2026-05-01 08:00 CEST (06:00 UTC)) must be before "
            "'to' (2026-05-01 08:00 CEST (06:00 UTC)); swap or correct the times"
        )
        assert lines[4].startswith("  entry #5, 'reason' (line 21): Input should be 'office'")
        assert lines[4].endswith("(lower case, exactly one of these)")
        assert len(lines) == 5

    def test_rule_errors_after_parsing(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        text = _log_text(_entry(), _entry(start="2026-03-01 00:00", end="2026-04-01 00:00"))
        with pytest.raises(
            OffSiteLogError, match=r"entry #2 \(line 6\), 'from': .* overlaps entry #1 \(line 2\)"
        ):
            store.loads(text, registry)

    def test_ambiguous_legacy_name(
        self, store: OffSiteLogStore, make_sensor: SensorFactory
    ) -> None:
        registry = SensorRegistry([make_sensor("11119986"), make_sensor("22229986")])
        with pytest.raises(OffSiteLogError, match=r"entry #1, 'sensor' \(line 2\): Legacy short"):
            store.loads(_log_text(_entry(sensor="9986")), registry)

    def test_unquoted_serial_keeps_its_text(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        text = "entries:\n  - sensor: 77799986\n    from: '2026-01-01 00:00'\n    to: null\n"
        (period,) = store.loads(text + "    reason: office\n", registry)
        assert period.sensor == OFFICE
        # YAML would read 01234567 as an octal number; the loader keeps the written digits.
        with pytest.raises(OffSiteLogError, match="sensor '01234567' is not in"):
            store.loads(text.replace("77799986", "01234567") + "    reason: office\n", registry)

    def test_entry_that_is_not_a_mapping(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        with pytest.raises(OffSiteLogError, match=r"entry #1: must be a list item of keys"):
            store.loads("entries:\n  - just text\n", registry)

    def test_missing_and_mistyped_keys_say_how_to_fix(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        text = (
            "entries:\n  - sensor: '77799986'\n    form: '2026-01-01 00:00'\n    reason: office\n"
        )
        with pytest.raises(OffSiteLogError) as error:
            store.loads(text, registry)
        message = str(error.value)
        assert (
            "entry #1 (line 2): the key 'from' is missing - add a line like "
            'from: "2026-03-01 08:00"'
        ) in message
        assert "entry #1 (line 2): the key 'to' is missing" in message
        assert "to: open  if the sensor is still off site" in message
        assert (
            "entry #1, 'form' (line 3): unknown key 'form' - allowed keys are sensor, from, to, "
            "reason, note (check the spelling)"
        ) in message

    def test_note_that_is_not_text(self, store: OffSiteLogStore, registry: SensorRegistry) -> None:
        text = _log_text(_entry(end=None)) + "    note: 12\n"
        with pytest.raises(OffSiteLogError, match="put the text in quotes"):
            store.loads(text, registry)

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("", "must contain one key 'entries:'"),
            ("entries:\n", "write 'entries: \\[\\]' when there are no periods"),
            ("- a\n", "must contain one key 'entries:'"),
            ("entries: [\n", "not valid YAML \\(indent with spaces"),
            ("entries: []\nextra: 1\n", r"unknown top-level key\(s\) 'extra' \(line 2\)"),
            ("entires: []\n", r"unknown top-level key\(s\) 'entires' \(line 1\)"),
        ],
    )
    def test_file_structure(
        self, store: OffSiteLogStore, registry: SensorRegistry, text: str, match: str
    ) -> None:
        with pytest.raises(OffSiteLogError, match=match):
            store.loads(text, registry)

    def test_unknown_timezone(self, store: OffSiteLogStore, registry: SensorRegistry) -> None:
        with pytest.raises(OffSiteLogError, match="unknown IANA time zone"):
            store.loads("entries: []\n", registry, "Nowhere/Town")

    def test_load_errors_name_the_file(
        self, store: OffSiteLogStore, registry: SensorRegistry, tmp_path: Path
    ) -> None:
        missing = tmp_path / "missing.yaml"
        with pytest.raises(OffSiteLogError, match="Cannot read off-site log"):
            store.load(missing, registry)
        broken = tmp_path / "broken.yaml"
        broken.write_text(_log_text(_entry(reason="holiday")), encoding="utf-8")
        with pytest.raises(OffSiteLogError, match=rf"^{broken}: Invalid off-site log"):
            store.load(broken, registry)


class TestSettings:
    def test_defaults(self) -> None:
        settings = OffSiteLogSettings()
        assert settings.file == Path("sensors/offsite_log.yaml")
        assert settings.timezone == "Europe/Prague"
        assert OffSiteLogSettings(timezone="UTC").timezone == "UTC"

    def test_unknown_timezone_and_key(self) -> None:
        with pytest.raises(ValidationError, match="unknown IANA time zone"):
            OffSiteLogSettings(timezone="Mars/Olympus")
        with pytest.raises(ValidationError, match="Extra inputs"):
            OffSiteLogSettings.model_validate({"zone": "UTC"})


class TestStrictYaml:
    """The traps of a hand-edited YAML file must fail loudly, never be read silently."""

    def test_second_entries_key_is_rejected(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        # The round-1 trap: an uncommented example added a second 'entries:' and the log
        # loaded silently empty (YAML keeps the last key).
        text = _log_text(_entry()) + "entries: []\n"
        with pytest.raises(OffSiteLogError) as error:
            store.loads(text, registry)
        assert (
            "line 6: the key 'entries' appears a second time (first on line 1); keep only one"
        ) in str(error.value)
        assert "under one 'entries:'" in str(error.value)

    def test_duplicate_key_inside_an_entry_is_rejected(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        text = _log_text(_entry()) + '    from: "2026-01-01 00:00"\n'
        with pytest.raises(OffSiteLogError, match=r"line 6: the key 'from' appears a second time"):
            store.loads(text, registry)

    def test_blank_to_is_an_error(self, store: OffSiteLogStore, registry: SensorRegistry) -> None:
        text = (
            'entries:\n  - sensor: "77799986"\n    from: "2025-12-17 12:00"\n    to:\n'
            "    reason: office\n"
        )
        with pytest.raises(OffSiteLogError) as error:
            store.loads(text, registry)
        assert (
            "entry #1, 'to' (line 4): is empty - write a date/time, or 'open' if the sensor is "
            "still off site"
        ) in str(error.value)

    def test_blank_value_at_the_end_of_the_file(
        self, store: OffSiteLogStore, registry: SensorRegistry
    ) -> None:
        text = 'entries:\n  - sensor: "77799986"\n    from: "2025-12-17 12:00"\n    to: open\n'
        with pytest.raises(OffSiteLogError, match=r"'reason' \(line 5\): is empty"):
            store.loads(text + "    reason:", registry)

    @pytest.mark.parametrize("value", ["open", "OPEN", "null", "~"])
    def test_open_and_null_mean_still_off_site(
        self, store: OffSiteLogStore, registry: SensorRegistry, value: str
    ) -> None:
        text = (
            f'entries:\n  - sensor: "77799986"\n    from: "2025-12-17 12:00"\n    to: {value}\n'
            "    reason: office\n"
        )
        (period,) = store.loads(text, registry)
        assert period.is_open

    def test_open_is_only_a_value_of_to(self) -> None:
        with pytest.raises(ValidationError, match="must be local"):
            _period(**{"from": "open"})

    def test_blank_sensor(self, store: OffSiteLogStore, registry: SensorRegistry) -> None:
        text = 'entries:\n  - sensor:\n    from: "2025-12-17 12:00"\n    to: open\n    reason: x\n'
        with pytest.raises(OffSiteLogError) as error:
            store.loads(text, registry)
        assert "entry #1, 'sensor' (line 2): is empty - write the 8-digit serial in quotes" in str(
            error.value
        )

    def test_blank_value_repr(self) -> None:
        assert repr(BlankValue()) == "BlankValue()"


class TestFormatting:
    def test_local_time_with_utc(self) -> None:
        assert format_local(_utc(2025, 12, 17, 11), "Europe/Prague") == (
            "2025-12-17 12:00 CET (11:00 UTC)"
        )
        assert format_local(_utc(2026, 7, 1, 23, 30), "Europe/Prague") == (
            "2026-07-02 01:30 CEST (2026-07-01 23:30 UTC)"
        )

    def test_ready_to_paste_text(self) -> None:
        assert format_local_iso(_utc(2026, 10, 25, 0, 30), "Europe/Prague") == (
            "2026-10-25T02:30+02:00"
        )
        assert format_local_iso(_utc(2026, 10, 25, 1, 30), "Europe/Prague") == (
            "2026-10-25T02:30+01:00"
        )
        assert LocalTimeReader("Europe/Prague").read("2026-10-25T02:30+01:00") == _utc(
            2026, 10, 25, 1, 30
        )
