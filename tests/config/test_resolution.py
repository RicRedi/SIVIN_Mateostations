"""Resolution of the configuration: shared ``time`` values and registry-backed settings."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field, ValidationError

from sivin.analytics.base import index_registry
from sivin.config import ConfigError, SivinConfig, TimeConfig, describe, load_config
from sivin.config.registered import ParamPreset
from sivin.config.resolver import ConfigResolver
from sivin.config.shared import SharedValue, SharedValues, plain, settings_model_of
from sivin.core.flags import QcFlag
from sivin.ingest.parsers.columns import ParserSettings
from sivin.quality.checks.base import check_registry
from sivin.quality.pipeline import QualityPipelineSettings


def problems_of(data: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as caught:
        SivinConfig.model_validate(data)
    return describe(caught.value).splitlines()


class TestSharedTimeValues:
    def test_interval_reaches_every_subsystem(self) -> None:
        config = SivinConfig.model_validate({"time": {"expected_interval_s": 600}})
        assert config.time.expected_interval_s == 600.0
        assert config.ingest.parsers.expected_interval_s == 600.0
        assert config.quality.check_settings["sampling"]["expected_interval_s"] == 600.0
        assert config.alignment.params["expected_interval_s"] == 600.0
        for index_id in ("botrytis_broome", "dew_point", "frost", "heat_hours", "vpd"):
            sampling = config.analytics.indices[index_id]["sampling"]
            assert sampling["nominal_interval_s"] == 600.0, index_id
        assert config.analytics.indices["powdery_mildew_gt"]["sampling"]["nominal_interval_s"] == (
            600.0
        )

    def test_default_interval_is_1830_s_everywhere(self) -> None:
        config = SivinConfig()
        assert config.ingest.parsers.expected_interval_s == 1830.0
        assert config.quality.check_settings["sampling"]["expected_interval_s"] == 1830.0
        assert config.alignment.params["expected_interval_s"] == 1830.0
        assert config.analytics.indices["frost"]["sampling"]["nominal_interval_s"] == 1830.0

    def test_time_zones_reach_parsers_and_detector(self) -> None:
        config = SivinConfig.model_validate(
            {"time": {"source_timezone": "UTC", "display_timezone": "Europe/Vienna"}}
        )
        assert config.ingest.parsers.source_timezone == "UTC"
        assert config.quality.deployment.display_timezone == "Europe/Vienna"
        assert config.offsite_log.timezone == "Europe/Prague"  # the log's own zone

    def test_an_equal_explicit_value_is_accepted(self) -> None:
        config = SivinConfig.model_validate(
            {
                "ingest": {"parsers": {"expected_interval_s": 1830}},
                "quality": {"check_settings": {"sampling": {"expected_interval_s": 1830.0}}},
            }
        )
        assert config == SivinConfig()

    @pytest.mark.parametrize(
        ("data", "path"),
        [
            ({"ingest": {"parsers": {"expected_interval_s": 1800}}}, "ingest.parsers"),
            (
                {"quality": {"check_settings": {"sampling": {"expected_interval_s": 1}}}},
                "quality.check_settings.sampling",
            ),
            ({"alignment": {"params": {"expected_interval_s": 1}}}, "alignment.params"),
            (
                {"analytics": {"indices": {"vpd": {"sampling": {"nominal_interval_s": 1}}}}},
                "analytics.indices.vpd.sampling",
            ),
        ],
    )
    def test_a_contradicting_value_names_its_key_path(
        self, data: dict[str, Any], path: str
    ) -> None:
        (problem,) = problems_of(data)
        assert problem.startswith(f"  {path}.")
        assert "is set by time.expected_interval_s (1830.0)" in problem

    def test_contradicting_time_zone(self) -> None:
        (problem,) = problems_of({"quality": {"deployment": {"display_timezone": "UTC"}}})
        assert problem.startswith("  quality.deployment.display_timezone: is set by ")

    def test_invalid_time_section_is_reported_by_the_section(self) -> None:
        assert problems_of({"time": {"expected_interval_s": 0}}) == [
            "  time.expected_interval_s: Input should be greater than 0"
        ]


class TestQualityCheckSettings:
    def test_every_enabled_check_gets_complete_settings(self) -> None:
        config = SivinConfig.model_validate(
            {"quality": {"check_settings": {"battery": {"low_battery_v": 3.4}}}}
        )
        settings = config.quality.check_settings
        enabled = (*config.quality.screening_checks, *config.quality.deployed_checks)
        assert set(settings) == set(enabled)
        assert settings["battery"] == {"low_battery_v": 3.4, "recovery_margin_v": 0.1}
        assert settings["range"] == check_registry.get("range").settings_model().model_dump(
            mode="json"
        )

    def test_unknown_key_names_the_full_path(self) -> None:
        assert problems_of({"quality": {"check_settings": {"range": {"temp_mx": 1}}}}) == [
            "  quality.check_settings.range.temp_mx: Extra inputs are not permitted"
        ]

    def test_settings_must_be_a_mapping(self) -> None:
        assert problems_of({"quality": {"check_settings": {"range": 5}}}) == [
            "  quality.check_settings.range: must be a mapping of settings"
        ]

    def test_settings_of_a_disabled_check_are_rejected(self) -> None:
        (problem,) = problems_of(
            {"quality": {"deployed_checks": [], "check_settings": {"spike": {}}}}
        )
        assert problem.startswith(
            "  quality.check_settings.spike: settings given for a check that is not enabled"
        )

    def test_unknown_check_is_reported_at_its_key_path(self) -> None:
        (problem,) = problems_of({"quality": {"check_settings": {"nonexist": {}}}})
        assert problem.startswith("  quality.check_settings.nonexist: unknown check; registered:")

    def test_invalid_check_lists_are_left_to_the_section(self) -> None:
        (problem,) = problems_of({"quality": {"screening_checks": ["nope"]}})
        assert problem.startswith("  quality.screening_checks: ")
        assert "unknown checks ['nope']" in problem
        (problem,) = problems_of({"quality": {"screening_checks": "missing"}})
        assert problem.startswith("  quality.screening_checks")

    def test_quality_section_must_be_a_mapping(self) -> None:
        (problem,) = problems_of({"quality": 3})
        assert problem.startswith("  quality: ")


class TestAlignmentParams:
    def test_params_of_the_chosen_strategy(self) -> None:
        config = SivinConfig.model_validate(
            {"alignment": {"strategy": "linear_interpolation", "params": {"max_gap_s": 3000}}}
        )
        assert dict(config.alignment.params) == {"max_gap_s": 3000.0}

    def test_unknown_parameter(self) -> None:
        assert problems_of({"alignment": {"params": {"max_gap_s": 3000}}}) == [
            "  alignment.params.max_gap_s: Extra inputs are not permitted"
        ]

    def test_params_must_be_a_mapping(self) -> None:
        assert problems_of({"alignment": {"params": [1]}}) == [
            "  alignment.params: must be a mapping of parameters"
        ]

    def test_unknown_strategy_is_left_to_the_section(self) -> None:
        (problem,) = problems_of({"alignment": {"strategy": "spline"}})
        assert problem.startswith("  alignment.strategy: ")


class TestIndexParams:
    def test_every_registered_index_is_resolved(self) -> None:
        indices = SivinConfig().analytics.indices
        assert tuple(sorted(indices)) == index_registry.ids()
        assert indices["huglin"]["k_override"] is None

    def test_parameters_override_defaults(self) -> None:
        config = SivinConfig.model_validate(
            {"analytics": {"indices": {"huglin": {"k_override": 1.05}}}}
        )
        assert config.analytics.indices["huglin"]["k_override"] == 1.05

    def test_unknown_index_and_unknown_key(self) -> None:
        problems = problems_of({"analytics": {"indices": {"hugin": {}, "gst": {"bse": 1}}}})
        assert problems[0].startswith("  analytics.indices.hugin: unknown index; registered: ")
        assert problems[1] == "  analytics.indices.gst.bse: Extra inputs are not permitted"

    def test_parameters_must_be_a_mapping(self) -> None:
        assert problems_of({"analytics": {"indices": {"gst": 1}}}) == [
            "  analytics.indices.gst: must be a mapping of parameters"
        ]

    def test_gsr_preset_fills_the_targets(self) -> None:
        config = SivinConfig.model_validate(
            {"analytics": {"indices": {"gsr": {"preset": "sauvignon_blanc"}}}}
        )
        gsr = config.analytics.indices["gsr"]
        # Parker et al. (2020) via Ausseil et al. (2021): 2820 °C·d to 200 g/L (WP-L.1).
        assert gsr["targets"] == [{"label": "sugar_200_g_l", "f_star_c_d": 2820.0}]
        assert "preset" not in gsr
        assert SivinConfig.model_validate(config.model_dump(mode="json")) == config

    def test_gsr_preset_errors(self) -> None:
        assert problems_of({"analytics": {"indices": {"gsr": {"preset": "riesling"}}}}) == [
            "  analytics.indices.gsr.preset: unknown preset; known: sauvignon_blanc"
        ]
        both = {"preset": "sauvignon_blanc", "targets": []}
        assert problems_of({"analytics": {"indices": {"gsr": both}}}) == [
            "  analytics.indices.gsr.preset: give either preset or targets"
        ]

    def test_preset_without_choices(self) -> None:
        preset = ParamPreset(index_id="x", key="preset", target="t", choices={})
        problems: list[Any] = []
        assert preset.expand({"preset": "a"}, ("x",), problems) == {}
        assert "known: none" in problems[0]["type"].message()

    def test_analytics_masks(self) -> None:
        assert SivinConfig().analytics.auxiliary_exclude_mask == int(
            QcFlag.PRE_DEPLOYMENT | QcFlag.MANUAL_EXCLUDE
        )
        (problem,) = problems_of({"analytics": {"auxiliary_exclude_mask": 4096}})
        assert problem.startswith("  analytics.auxiliary_exclude_mask: ")


@pytest.mark.parametrize(
    ("data", "path"),
    [
        ({"quality": {"screening_checks": ["missing", 3]}}, "quality.screening_checks"),
        ({"alignment": 3}, "alignment"),
        ({"analytics": 3}, "analytics"),
        ({"analytics": {"indices": [1]}}, "analytics.indices"),
    ],
)
def test_malformed_sections_are_left_to_the_section_model(data: dict[str, Any], path: str) -> None:
    problems = problems_of(data)
    assert problems
    assert all(problem.startswith(f"  {path}") for problem in problems)


def test_preset_values_become_plain_data() -> None:
    preset = ParamPreset(index_id="x", key="preset", target="t", choices={"a": ("b", 1)})
    assert preset.expand({"preset": "a"}, ("x",), []) == {"t": ["b", 1]}


class TestIdempotence:
    def test_resolving_a_resolved_configuration_changes_nothing(self) -> None:
        config = SivinConfig.model_validate(
            {"time": {"expected_interval_s": 900}, "storage": {"conflict_policy": "raise"}}
        )
        assert SivinConfig.model_validate(config.model_dump(mode="json")) == config
        assert SivinConfig.model_validate(config.model_dump()) == config

    def test_sections_given_as_models(self) -> None:
        config = SivinConfig(
            time=TimeConfig(expected_interval_s=900),
            quality=QualityPipelineSettings(deployed_checks=()),
        )
        assert config.quality.check_settings["sampling"]["expected_interval_s"] == 900.0
        assert "spike" not in config.quality.check_settings

    def test_parser_settings_given_as_a_model_keep_their_explicit_keys(self) -> None:
        parsers = ParserSettings(header_search_rows=7)
        config = SivinConfig.model_validate({"ingest": {"parsers": parsers}})
        assert config.ingest.parsers.header_search_rows == 7
        assert config.ingest.parsers.expected_interval_s == 1830.0

    def test_check_and_index_settings_round_trip_through_json(self) -> None:
        for index_id in index_registry.ids():
            model = index_registry.get(index_id).params_model
            assert model.model_validate(model().model_dump(mode="json")) == model(), index_id
        for check_id in check_registry.ids():
            model = check_registry.get(check_id).settings_model
            assert model.model_validate(model().model_dump(mode="json")) == model(), check_id

    def test_non_mapping_data_is_rejected_by_the_model(self) -> None:
        with pytest.raises(ValidationError):
            SivinConfig.model_validate([1, 2])
        assert ConfigResolver().resolve(SivinConfig, [1, 2]) == [1, 2]


class _Leaf(BaseModel):
    expected_interval_s: float = 1.0


class _Branch(BaseModel):
    leaf: _Leaf = Field(default_factory=lambda: _Leaf(expected_interval_s=5.0))
    maybe: _Leaf | None = None
    annotated: Annotated[_Leaf, "meta"] = Field(default_factory=_Leaf)
    many: list[_Leaf] = Field(default_factory=list)
    plain_value: int = 0


class TestSharedValuesMechanics:
    SHARED = SharedValues((SharedValue(frozenset({"expected_interval_s"}), 9.0, "time.x"),))

    def test_settings_model_of(self) -> None:
        fields = _Branch.model_fields
        assert settings_model_of(fields["leaf"].annotation) is _Leaf
        assert settings_model_of(fields["maybe"].annotation) is _Leaf
        assert settings_model_of(Annotated[_Leaf, "meta"]) is _Leaf
        assert settings_model_of(fields["many"].annotation) is None
        assert settings_model_of(int) is None
        assert settings_model_of(_Leaf | _Branch) is None

    def test_defaults_and_explicit_sections_are_filled(self) -> None:
        problems: list[Any] = []
        out = self.SHARED.apply(_Branch, {"maybe": {}, "plain_value": 3}, ("x",), problems)
        assert out == {
            "leaf": {"expected_interval_s": 9.0},
            "maybe": {"expected_interval_s": 9.0},
            "annotated": {"expected_interval_s": 9.0},
            "plain_value": 3,
        }
        assert problems == []

    def test_a_non_mapping_section_is_left_for_validation(self) -> None:
        out = self.SHARED.apply(_Branch, {"leaf": 5}, (), [])
        assert out["leaf"] == 5

    def test_reaches(self) -> None:
        assert self.SHARED.reaches(_Branch)
        assert not SharedValues(()).reaches(_Branch)

    def test_a_field_name_can_be_shared_only_once(self) -> None:
        twice = SharedValue(frozenset({"a"}), 1, "time.a")
        with pytest.raises(ValueError, match="shared twice"):
            SharedValues((twice, twice))

    def test_plain(self) -> None:
        assert plain({"a": _Leaf(expected_interval_s=2.0), "b": [1]}) == {
            "a": {"expected_interval_s": 2.0},
            "b": [1],
        }


def test_committed_yaml_lists_valid_keys_only(tmp_path: Path) -> None:
    text = "analytics:\n  indices:\n    huglin: {k_overide: 1.0}\n"
    path = tmp_path / "sivin.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=r"(?m)^  analytics\.indices\.huglin\.k_overide: "):
        load_config(path)


class TestIntervalDerivedDefaults:
    def test_derived_defaults_follow_the_interval(self) -> None:
        config = SivinConfig.model_validate({"time": {"expected_interval_s": 600}})
        checks = config.quality.check_settings
        assert checks["spike"]["min_interval_s"] == 600.0
        assert checks["spike"]["max_interval_s"] == 1800.0  # 3 x
        assert checks["step"]["max_interval_s"] == 1800.0  # 3 x
        assert checks["precip_counter"]["max_interval_s"] == 900.0  # 1.5 x
        assert config.analytics.indices["vpd"]["sampling"]["max_sample_duration_s"] == 1500.0
        assert config.analytics.indices["botrytis_broome"]["sampling"]["max_sample_duration_s"] == (
            1500.0
        )
        linear = SivinConfig.model_validate(
            {
                "time": {"expected_interval_s": 600},
                "alignment": {"strategy": "linear_interpolation"},
            }
        )
        assert linear.alignment.params["max_gap_s"] == 900.0  # 1.5 x

    def test_defaults_at_1830_s_are_unchanged(self) -> None:
        config = SivinConfig()
        assert config.quality.check_settings["spike"]["max_interval_s"] == 5490.0
        assert config.analytics.indices["frost"]["sampling"]["max_sample_duration_s"] == 4575.0

    def test_an_explicit_value_stays(self) -> None:
        config = SivinConfig.model_validate(
            {
                "time": {"expected_interval_s": 600},
                "quality": {"check_settings": {"spike": {"max_interval_s": 4000}}},
            }
        )
        assert config.quality.check_settings["spike"]["max_interval_s"] == 4000.0

    def test_errors_explain_the_relation_to_the_interval(self) -> None:
        problems = problems_of(
            {
                "time": {"expected_interval_s": 5000},
                "analytics": {"indices": {"vpd": {"sampling": {"max_sample_duration_s": 4575}}}},
            }
        )
        (problem,) = problems
        assert problem.startswith("  analytics.indices.vpd.sampling: ")
        assert "time.expected_interval_s = 5000 s" in problem
        assert "max_sample_duration_s = 2.5 x time.expected_interval_s by default" in problem
        assert "nominal_interval_s is set from time.expected_interval_s" in problem

    def test_reference_marks_derived_defaults(self) -> None:
        from sivin.config.schema import ConfigReference

        rows = {row.path: row for row in ConfigReference().rows()}
        spike = rows["quality.check_settings.spike.max_interval_s"]
        assert spike.default == "= `3 x time.expected_interval_s`"
