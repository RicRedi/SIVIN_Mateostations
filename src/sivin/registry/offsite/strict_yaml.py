"""Strict YAML reading of the hand-edited off-site log.

PyYAML silently keeps the last of two equal keys and reads ``to:`` without a value as
``null``. :class:`StrictLogLoader` turns the first into an error and the second into
:class:`BlankValue`, so a hand-edited file is never misread silently.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import yaml

from sivin.registry.offsite.messages import ENTRIES_KEY, OffSiteLogError


class BlankValue:
    """A key written without a value in the YAML file (``to:``), as opposed to ``to: null``.

    Produced by :class:`OffSiteLogStore`'s loader; :class:`OffSitePeriod` rejects it with a hint
    from :data:`BLANK_HINTS`, so a half-filled entry never silently becomes an open period.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "BlankValue()"


class LocatedMapping(dict[Any, Any]):
    """A YAML mapping that remembers its line and the line of each key (1-based)."""

    line: int = 0
    key_lines: dict[str, int]


_YAML_MAP_TAG: Final = "tag:yaml.org,2002:map"
_YAML_NULL_TAG: Final = "tag:yaml.org,2002:null"
_YAML_NUMBER_TAGS: Final = frozenset({"tag:yaml.org,2002:int", "tag:yaml.org,2002:float"})


class StrictLogLoader(yaml.SafeLoader):
    """Safe YAML loader for the log that cannot misread a hand-edited file silently.

    * A key that appears twice in one mapping (e.g. a second ``entries:`` after uncommenting an
      example, or two ``from:`` in one entry) raises :class:`OffSiteLogError` naming the key
      and both lines; PyYAML would keep the last one without a word.
    * A key without a value (``to:``) becomes :class:`BlankValue`, not ``None``.
    * An unquoted ``sensor: 77799986`` keeps its text (no octal or float surprises).
    * Mappings are :class:`LocatedMapping` objects carrying line numbers for messages.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Build a mapping, rejecting duplicate keys and marking blank values."""
        first_lines: dict[Any, int] = {}
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            line = key_node.start_mark.line + 1
            if key in first_lines:
                raise OffSiteLogError(
                    f"line {line}: the key {key!r} appears a second time (first on line "
                    f"{first_lines[key]}); keep only one - YAML would silently use the last"
                    + (
                        " (put all entries as '- sensor: ...' items under one 'entries:')"
                        if key == ENTRIES_KEY
                        else ""
                    )
                )
            first_lines[key] = line
        mapping = super().construct_mapping(node, deep=deep)
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if isinstance(value_node, yaml.ScalarNode) and value_node.style is None:
                if value_node.tag == _YAML_NULL_TAG and value_node.value == "":
                    mapping[key] = BlankValue()
                elif key == "sensor" and value_node.tag in _YAML_NUMBER_TAGS:
                    mapping[key] = value_node.value
        return mapping

    def construct_located_mapping(self, node: yaml.MappingNode) -> Iterator[LocatedMapping]:
        """Constructor of YAML mappings: a :class:`LocatedMapping` with line numbers."""
        data = LocatedMapping()
        data.line = node.start_mark.line + 1
        data.key_lines = {
            str(key_node.value): key_node.start_mark.line + 1 for key_node, _ in node.value
        }
        yield data
        data.update(self.construct_mapping(node))

    yaml_constructors = {  # noqa: RUF012 - the per-class constructor registry of PyYAML
        **yaml.SafeLoader.yaml_constructors,
        _YAML_MAP_TAG: construct_located_mapping,
    }
