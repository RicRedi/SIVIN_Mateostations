"""Labels of variables and indices; QC event mapping (synthetic events)."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

import sivin.config  # noqa: F401  (imports the index packages, which register themselves)
from sivin.analytics.base import index_registry
from sivin.quality.events import EventKind, EventSource, QualityEvent, Severity
from sivin.site.events import POINT_KINDS, SiteEventMapping
from sivin.site.labels import INDEX_LABELS, VARIABLES, IndexCatalog, IndexSpec, Label
from sivin.site.settings import DEFAULT_PUBLISHED_EVENTS, DEFAULT_STALE_AFTER_S, SiteSettings

T0 = pd.Timestamp("2026-01-01T00:00:00Z")
T0_S = 1_767_225_600


def test_every_registered_index_has_a_label() -> None:
    assert set(index_registry.ids()) == set(INDEX_LABELS)


def test_catalog_entry() -> None:
    entry = IndexCatalog().entry(IndexSpec("huglin", "°C·d"))
    assert entry == {
        "id": "huglin",
        "unit": "°C·d",
        "doc": "docs/indices/huglin.md",
        "label": {"cs": "Huglinův index", "de": "Huglin-Index", "en": "Huglin index"},
    }


def test_catalog_falls_back_to_the_id(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        label = IndexCatalog({}).label("new_index")
    assert label == Label.same("new_index")
    assert "new_index has no label" in caplog.text


def test_variables_of_the_manifest() -> None:
    assert [variable.as_dict() for variable in VARIABLES[:2]] == [
        {
            "id": "temp_c",
            "unit": "°C",
            "label": {"cs": "Teplota", "de": "Temperatur", "en": "Temperature"},
        },
        {
            "id": "rh_pct",
            "unit": "%",
            "label": {"cs": "Vlhkost", "de": "Feuchtigkeit", "en": "Humidity"},
        },
    ]
    assert [variable.id for variable in VARIABLES] == ["temp_c", "rh_pct", "precip_mm", "battery_v"]


def test_settings_defaults_and_duplicates() -> None:
    settings = SiteSettings()
    assert settings.stale_after_s == DEFAULT_STALE_AFTER_S == 36 * 3600
    assert settings.events == DEFAULT_PUBLISHED_EVENTS
    assert EventKind.UNLOGGED_OFF_SITE not in settings.events  # opt-in only (review round 1)
    assert SiteSettings(events=("step",)).events == (EventKind.STEP,)
    with pytest.raises(ValueError, match="listed twice"):
        SiteSettings(events=(EventKind.STEP, EventKind.STEP))
    with pytest.raises(ValueError, match="Extra inputs"):
        SiteSettings.model_validate({"stale_after": 1})


def test_point_event_has_no_end() -> None:
    event = QualityEvent(EventKind.STEP, T0, "temp_c level step +5.0 °C", origin="step")
    assert SiteEventMapping([EventKind.STEP]).entries([event]) == [
        {
            "type": "step",
            "t": T0_S,
            "source": "detected",
            "confidence": None,
            "detail": "temp_c level step +5.0 °C",
        }
    ]


def test_interval_events_have_an_end() -> None:
    open_period = QualityEvent(EventKind.OFF_SITE, T0, "service: synthetic", source=EventSource.LOG)
    battery = QualityEvent(
        EventKind.LOW_BATTERY,
        T0,
        "",
        severity=Severity.WARNING,
        end_utc=T0 + pd.Timedelta(seconds=1830),
    )
    unlogged = QualityEvent(
        EventKind.UNLOGGED_OFF_SITE,
        T0,
        "possible unlogged off-site period",
        confidence=0.876,
        end_utc=T0 + pd.Timedelta(days=1),
    )
    assert SiteEventMapping(DEFAULT_PUBLISHED_EVENTS).entries([unlogged]) == []
    mapping = SiteEventMapping([*DEFAULT_PUBLISHED_EVENTS, EventKind.UNLOGGED_OFF_SITE])
    off_site, low, warning = mapping.entries([open_period, battery, unlogged])
    assert off_site == {
        "type": "off_site",
        "t": T0_S,
        "t_end": None,
        "source": "log",
        "confidence": None,
        "detail": "service",  # the reason only, never the note of the off-site log
    }
    assert (low["t_end"], low["detail"]) == (T0_S + 1830, None)
    assert (warning["t_end"], warning["confidence"]) == (T0_S + 86_400, 0.88)


@pytest.mark.parametrize(
    ("detail", "published"),
    [
        ("service: INTERNAL synthetic note", "service"),
        ("other", "other"),
        ("", None),
        ("not a reason: INTERNAL synthetic note", None),
    ],
)
def test_off_site_detail_publishes_only_the_reason(detail: str, published: str | None) -> None:
    event = QualityEvent(EventKind.OFF_SITE, T0, detail, source=EventSource.LOG, end_utc=None)
    assert SiteEventMapping([EventKind.OFF_SITE]).entry(event)["detail"] == published


def test_other_kinds_keep_their_detail_and_filters_are_injectable() -> None:
    step = QualityEvent(EventKind.STEP, T0, "temp_c level step +5.0 °C")
    assert SiteEventMapping([EventKind.STEP]).entry(step)["detail"] == "temp_c level step +5.0 °C"
    custom = SiteEventMapping([EventKind.STEP], {EventKind.STEP: lambda _: "hidden"})
    assert custom.entry(step)["detail"] == "hidden"


def test_unpublished_kinds_are_dropped() -> None:
    gap = QualityEvent(EventKind.GAP, T0, "gap", end_utc=T0 + pd.Timedelta(hours=5))
    assert SiteEventMapping(DEFAULT_PUBLISHED_EVENTS).entries([gap]) == []
    assert SiteEventMapping([EventKind.GAP]).entries([gap])[0]["t_end"] == T0_S + 5 * 3600


def test_transition_kinds_are_points() -> None:
    assert {EventKind.DEPLOYMENT, EventKind.RETRIEVAL, EventKind.STEP} <= POINT_KINDS
    assert EventKind.OFF_SITE not in POINT_KINDS
