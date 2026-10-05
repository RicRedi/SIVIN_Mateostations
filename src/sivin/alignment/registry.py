"""A small registry of extension classes keyed by a class-level identifier.

The alignment package has two extension points, :class:`~sivin.alignment.strategies.
AlignmentStrategy` and :class:`~sivin.alignment.grid.SpanRule`. Each keeps its implementations
in a :class:`ClassRegistry`; a new behaviour is a new class decorated with
``@registry.register`` (MIGRATION_PLAN §1.2, point 2).
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


class ClassRegistry[T]:
    """Registry of concrete subclasses of ``base``, keyed by their ``key_attribute``.

    Registries are the one kind of module-level mutable state the project allows: they are
    filled by class decorators when the defining module is imported and never changed later.

    Parameters
    ----------
    base : type
        Every registered class must be a concrete subclass of it; normally the class ``T``
        itself (an abstract base, hence typed loosely).
    key_attribute : str
        Name of the non-empty string class variable that identifies a class, e.g.
        ``"strategy_id"``.
    kind : str
        Human-readable name of the extension point, used in error messages.
    """

    __slots__ = ("_base", "_classes", "_key_attribute", "_kind")

    def __init__(self, base: type[Any], key_attribute: str, kind: str) -> None:
        self._base = base
        self._key_attribute = key_attribute
        self._kind = kind
        self._classes: dict[str, type[T]] = {}

    def register[C: type[Any]](self, cls: C) -> C:
        """Register ``cls``; use as a class decorator.

        Parameters
        ----------
        cls : type
            A concrete subclass of the registry's base class.

        Returns
        -------
        type
            ``cls`` unchanged.

        Raises
        ------
        TypeError
            If ``cls`` is not a concrete subclass of the base or has no valid identifier.
        ValueError
            If the identifier is already registered.
        """
        if not (isinstance(cls, type) and issubclass(cls, self._base)):
            raise TypeError(
                f"Only {self._base.__name__} subclasses can be registered, got {cls!r}."
            )
        if inspect.isabstract(cls):
            raise TypeError(f"{cls.__name__} is abstract and cannot be registered.")
        key = getattr(cls, self._key_attribute, None)
        if not isinstance(key, str) or not key:
            raise TypeError(
                f"{cls.__name__} must define a non-empty class variable {self._key_attribute!r}."
            )
        if key in self._classes:
            raise ValueError(
                f"{self._kind} {key!r} is already registered by {self._classes[key].__qualname__}."
            )
        self._classes[key] = cast(type[T], cls)
        logger.debug("Registered %s %r (%s).", self._kind, key, cls.__qualname__)
        return cls

    def get(self, key: str) -> type[T]:
        """Return the class registered under ``key``.

        Parameters
        ----------
        key : str
            Identifier of a registered class.

        Returns
        -------
        type
            The registered class.

        Raises
        ------
        KeyError
            If nothing is registered under ``key``.
        """
        try:
            return self._classes[key]
        except KeyError:
            raise KeyError(
                f"Unknown {self._kind} {key!r}; registered: {', '.join(self.ids()) or 'none'}."
            ) from None

    def ids(self) -> tuple[str, ...]:
        """Return the registered identifiers, sorted.

        Returns
        -------
        tuple of str
            Sorted identifiers.
        """
        return tuple(sorted(self._classes))

    def __contains__(self, key: object) -> bool:
        return key in self._classes

    def __len__(self) -> int:
        return len(self._classes)
