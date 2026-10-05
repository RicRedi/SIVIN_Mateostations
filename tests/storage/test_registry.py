"""Tests of NamedRegistry."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pytest

from sivin.storage.registry import NamedRegistry


class _Base(ABC):
    @abstractmethod
    def value(self) -> int: ...


class _One(_Base):
    def value(self) -> int:
        return 1


def test_register_get_create_and_names() -> None:
    registry = NamedRegistry[_Base](_Base)
    registry.register("one")(_One)
    assert registry.get("one") is _One
    assert registry.create("one").value() == 1
    assert registry.names() == ("one",)
    assert "one" in registry
    assert "two" not in registry


def test_unknown_name_lists_known_names() -> None:
    registry = NamedRegistry[_Base](_Base)
    with pytest.raises(KeyError, match="registered: none"):
        registry.get("one")
    registry.register("one")(_One)
    with pytest.raises(KeyError, match="registered: one"):
        registry.get("two")


def test_rejects_duplicates_abstract_classes_foreign_classes_and_empty_names() -> None:
    registry = NamedRegistry[_Base](_Base)
    registry.register("one")(_One)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("one")(_One)
    with pytest.raises(TypeError, match="abstract"):
        registry.register("base")(_Base)
    with pytest.raises(TypeError, match="Only _Base subclasses"):
        registry.register("int")(int)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="empty"):
        registry.register("")
