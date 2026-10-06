"""Encoding, output directory, pruning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sivin.redaction import SecretRedactor
from sivin.site.files import SiteFile, SiteOutput, digest, encode_json


def test_encode_json_is_compact_utf8_with_final_newline() -> None:
    assert encode_json({"b": 1, "a": [1.5, None], "u": "°C"}) == (
        '{"b":1,"a":[1.5,null],"u":"°C"}\n'.encode()
    )


def test_encode_json_rejects_nan() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        encode_json({"x": float("nan")})


def test_encode_json_redacts_strings() -> None:
    redactor = SecretRedactor.of({"SIVIN_PASSWORD": "synthetic-Secret-42"})
    assert b"synthetic-Secret-42" not in encode_json({"detail": "x synthetic-Secret-42"}, redactor)


@pytest.mark.parametrize("path", ["/abs.json", "../up.json", "series/../../x.json"])
def test_site_file_paths_stay_inside(path: str) -> None:
    with pytest.raises(ValueError, match="relative"):
        SiteFile(path, b"")


def test_digest_is_sha256() -> None:
    assert (
        SiteFile("a.json", b"").digest
        == digest(b"")
        == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    )


def test_write_only_when_content_changes(tmp_path: Path) -> None:
    output = SiteOutput(tmp_path / "data")
    file = SiteFile("events/77678271.json", b"{}\n")
    assert output.write(file) is True
    assert output.write(file) is False
    assert output.read("events/77678271.json") == b"{}\n"
    assert output.has("events/77678271.json", file.digest)
    assert not output.has("events/77678271.json", digest(b"other"))
    assert not output.has("missing.json", file.digest)
    assert output.write(SiteFile("events/77678271.json", b"[]\n")) is True
    assert output.root == tmp_path / "data"


def test_prune_only_managed_directories(tmp_path: Path) -> None:
    output = SiteOutput(tmp_path)
    for path in (
        "series/1/raw/2026-01.json",
        "series/1/daily.json",
        "series/2/raw/2026-01.json",
        "events/2.json",
        "indices/2025.json",
    ):
        output.write(SiteFile(path, b"x"))
    (tmp_path / "README.md").write_text("kept", encoding="utf-8")
    removed = output.prune({"series/1/raw/2026-01.json", "series/1/daily.json"})
    assert removed == ["events/2.json", "indices/2025.json", "series/2/raw/2026-01.json"]
    assert not (tmp_path / "series" / "2").exists()
    assert not (tmp_path / "events").exists()
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "series" / "1" / "daily.json").exists()


def test_prune_of_a_missing_directory(tmp_path: Path) -> None:
    assert SiteOutput(tmp_path / "nothing").prune(set()) == []
