"""Tests of NamedRegistry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import pytest

from sivin.storage.registry import NamedRegistry


class _Base(ABC):
    name: ClassVar[str]

    @abstractmethod
    def value(self) -> int: ...


class _One(_Base):
    name: ClassVar[str] = "one"

    def value(self) -> int:
        return 1


class _Nameless(_Base):
    def value(self) -> int:
        return 0


def test_register_get_create_and_names() -> None:
    registry = NamedRegistry[_Base](_Base)
    assert registry.register(_One) is _One
    assert registry.get("one") is _One
    assert registry.create("one").value() == 1
    assert registry.names() == ("one",)
    assert "one" in registry
    assert "two" not in registry


def test_unknown_name_lists_known_names() -> None:
    registry = NamedRegistry[_Base](_Base)
    with pytest.raises(KeyError, match="registered: none"):
        registry.get("one")
    registry.register(_One)
    with pytest.raises(KeyError, match="registered: one"):
        registry.get("two")


def test_rejects_duplicates_abstract_foreign_and_nameless_classes() -> None:
    registry = NamedRegistry[_Base](_Base)
    registry.register(_One)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_One)
    with pytest.raises(TypeError, match="abstract"):
        registry.register(_Base)  # type: ignore[type-abstract]
    with pytest.raises(TypeError, match="Only _Base subclasses"):
        registry.register(int)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="class variable 'name'"):
        registry.register(_Nameless)
