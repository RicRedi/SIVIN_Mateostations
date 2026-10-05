"""Tests of PortalSettings and PortalCredentials."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pydantic
import pytest
from pydantic import BaseModel

from sivin.ingest.portal.credentials import PortalCredentials
from sivin.ingest.portal.errors import MissingCredentialsError
from sivin.ingest.portal.settings import PortalSelectors, PortalSettings, PortalTimeouts
from sivin.paths import ProjectPaths

SECRET = "synthetic-Secret-42"


def _all_fields(model: type[BaseModel]) -> list[tuple[str, str | None]]:
    fields: list[tuple[str, str | None]] = []
    for name, info in model.model_fields.items():
        fields.append((f"{model.__name__}.{name}", info.description))
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            fields.extend(_all_fields(annotation))
    return fields


def test_defaults_are_the_legacy_values() -> None:
    settings = PortalSettings()

    assert settings.portal_url == "https://lemon.e-service.cz/"
    assert settings.folder_name == "SIVIN VUT"
    assert settings.meteo_tab_name == "Meteorologická data"
    assert settings.selectors.username_id == "username"
    assert settings.selectors.submit_css == "input[type='submit']"
    assert settings.selectors.spinner_id == "UpdateProgress"
    assert settings.selectors.viewmodel_id == "__dot_viewmodel_root"
    assert "mdi-file-excel" in settings.selectors.excel_button_xpath
    assert settings.timeouts.element_wait_s == 15.0
    assert settings.timeouts.download_wait_s == 30.0
    assert settings.headless is True


def test_every_field_has_a_description() -> None:
    fields = _all_fields(PortalSettings)

    assert len(fields) > 20
    assert [name for name, description in fields if not description] == []


def test_settings_are_frozen_and_reject_unknown_keys() -> None:
    settings = PortalSettings()
    with pytest.raises(pydantic.ValidationError, match="frozen"):
        settings.headless = False  # type: ignore[misc]
    with pytest.raises(pydantic.ValidationError, match="extra"):
        PortalSettings.model_validate({"selectors": {"usernme_id": "x"}})


def test_xpath_template_needs_the_placeholder() -> None:
    with pytest.raises(pydantic.ValidationError, match=r"\{text\}"):
        PortalSelectors(link_xpath_template="//a[contains(., 'SIVIN VUT')]")


@pytest.mark.parametrize("field", ["element_wait_s", "download_wait_s", "poll_interval_s"])
def test_waits_must_be_positive(field: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        PortalTimeouts.model_validate({field: 0})


def test_resolved_against_makes_paths_absolute(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    settings = PortalSettings(chromedriver_path=Path("bin/chromedriver"))

    resolved = settings.resolved_against(paths)

    assert resolved.download_dir == tmp_path / "data" / "downloads"
    assert resolved.chromedriver_path == tmp_path / "bin" / "chromedriver"
    assert resolved.chrome_binary is None
    assert settings.download_dir == Path("data/downloads")


def test_credentials_from_environment() -> None:
    credentials = PortalCredentials.from_env({"SIVIN_USER": "user", "SIVIN_PASSWORD": SECRET})

    assert credentials.username == "user"
    assert credentials.password == SECRET


def test_credentials_default_to_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIVIN_USER", "user")
    monkeypatch.setenv("SIVIN_PASSWORD", SECRET)

    assert PortalCredentials.from_env().password == SECRET


@pytest.mark.parametrize(
    ("environ", "missing"),
    [
        ({}, "SIVIN_USER, SIVIN_PASSWORD"),
        ({"SIVIN_USER": "user"}, "SIVIN_PASSWORD"),
        ({"SIVIN_USER": "", "SIVIN_PASSWORD": SECRET}, "SIVIN_USER"),
    ],
)
def test_missing_credentials_name_the_variable_only(environ: dict[str, str], missing: str) -> None:
    with pytest.raises(MissingCredentialsError) as caught:
        PortalCredentials.from_env(environ)

    assert f"variable(s) {missing} not set" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_empty_credentials_are_rejected() -> None:
    with pytest.raises(MissingCredentialsError):
        PortalCredentials("user", "")


def test_repr_and_str_never_reveal_the_password() -> None:
    credentials = PortalCredentials("user", SECRET)

    for text in (repr(credentials), str(credentials), f"{credentials}", repr([credentials])):
        assert SECRET not in text
        assert "***" in text


def test_light_modules_do_not_import_selenium() -> None:
    code = (
        "import sys, sivin.ingest.portal, sivin.ingest.portal.settings; "
        "print('selenium' in sys.modules)"
    )
    output = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True
    ).stdout

    assert output.strip() == "False"


def test_custom_xpath_template_with_placeholder_is_accepted() -> None:
    selectors = PortalSelectors(link_xpath_template="//span[contains(., {text})]/ancestor::a")

    assert selectors.link_xpath_template.startswith("//span")
