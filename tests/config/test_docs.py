"""docs/configuration.md carries the generated key reference."""

from __future__ import annotations

from pathlib import Path

from sivin.config.schema import ConfigReference

DOC = Path(__file__).resolve().parents[2] / "docs" / "configuration.md"
BEGIN = "<!-- BEGIN GENERATED REFERENCE -->\n\n"
END = "\n<!-- END GENERATED REFERENCE -->\n"


def test_configuration_reference_is_current() -> None:
    """Regenerate with ConfigReference().markdown(heading_level=4) if this fails."""
    text = DOC.read_text(encoding="utf-8")
    generated = text[text.index(BEGIN) + len(BEGIN) : text.index(END)]
    assert generated == ConfigReference().markdown(heading_level=4)
