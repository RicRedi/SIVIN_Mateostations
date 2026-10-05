"""Name-keyed registries of the storage extension points (conflict policies, partitionings)."""

from __future__ import annotations

import inspect
import logging

logger = logging.getLogger(__name__)


class NamedRegistry[T]:
    """Registry of the concrete subclasses of one extension point, keyed by a short name.

    Registries are the one kind of module-level mutable state the project allows
    (MIGRATION_PLAN §1.2, point 2): they are filled by class decorators when the defining module
    is imported and never changed afterwards. Registered classes carry their key as the class
    variable ``name`` and must be constructible without arguments, so that a configuration can
    name them.

    Parameters
    ----------
    base : type
        The extension point (an abstract base class); only its subclasses can be registered.
        Being abstract, it cannot be the type argument's value for mypy, so the registry is
        created as ``NamedRegistry[Base](Base)``.
    """

    __slots__ = ("_base", "_classes")

    def __init__(self, base: type[object]) -> None:
        self._base = base
        self._classes: dict[str, type[T]] = {}

    def register(self, cls: type[T]) -> type[T]:
        """Register a class under its ``name`` class variable; use as a class decorator.

        The name is set once, as the class variable ``name``, and read from there.

        Parameters
        ----------
        cls : type
            A concrete subclass of the extension point with a non-empty ``name``.

        Returns
        -------
        type
            The class unchanged.

        Raises
        ------
        ValueError
            If the name is already registered.
        TypeError
            If the class is not a concrete subclass of the extension point or has no
            non-empty string ``name``.
        """
        if not (isinstance(cls, type) and issubclass(cls, self._base)):
            raise TypeError(f"Only {self._base.__name__} subclasses can be registered.")
        if inspect.isabstract(cls):
            raise TypeError(f"{cls.__name__} is abstract and cannot be registered.")
        name = getattr(cls, "name", None)
        if not isinstance(name, str) or not name:
            raise TypeError(f"{cls.__name__} must define a non-empty class variable 'name'.")
        if name in self._classes:
            raise ValueError(
                f"{self._base.__name__} name {name!r} is already registered by "
                f"{self._classes[name].__qualname__}."
            )
        self._classes[name] = cls
        logger.debug("Registered %s %r (%s).", self._base.__name__, name, cls.__qualname__)
        return cls

    def get(self, name: str) -> type[T]:
        """Return the class registered under ``name``.

        Parameters
        ----------
        name : str
            A registered name.

        Returns
        -------
        type
            The registered class.

        Raises
        ------
        KeyError
            If nothing is registered under ``name``; the message lists the known names.
        """
        try:
            return self._classes[name]
        except KeyError:
            raise KeyError(
                f"Unknown {self._base.__name__} {name!r}; registered: "
                f"{', '.join(self.names()) or 'none'}."
            ) from None

    def create(self, name: str) -> T:
        """Instantiate the class registered under ``name`` without arguments.

        Parameters
        ----------
        name : str
            A registered name.

        Returns
        -------
        object
            A new instance of the registered class.
        """
        return self.get(name)()

    def names(self) -> tuple[str, ...]:
        """Return the registered names, sorted.

        Returns
        -------
        tuple of str
            Sorted names.
        """
        return tuple(sorted(self._classes))

    def __contains__(self, name: object) -> bool:
        return name in self._classes
