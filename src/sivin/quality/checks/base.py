"""Extension point for quality checks: :class:`QualityCheck`, its outcome and registry.

A new check is a new subclass of :class:`QualityCheck` that registers itself::

    class MyCheckSettings(CheckSettings):
        limit_c: float = Field(5.0, description="... in °C. Origin of the default: ...")


    @check_registry.register
    class MyCheck(QualityCheck[MyCheckSettings]):
        check_id = "my_check"
        settings_model = MyCheckSettings

        def check(self, series: MeasurementSeries) -> CheckOutcome: ...

The registry is filled when :mod:`sivin.quality.checks` is imported.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Final, cast

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict

from sivin.core.flags import QcFlag
from sivin.core.schema import QC_DTYPE, MeasurementSeries
from sivin.quality.events import QualityEvent

logger = logging.getLogger(__name__)

FlagArray = npt.NDArray[np.int32]
"""One :class:`~sivin.core.flags.QcFlag` bit field per sample."""


class CheckSettings(BaseModel):
    """Base class of check settings: frozen, unknown keys rejected.

    Every field of a subclass has ``Field(description=...)`` with its unit and the origin of
    its default value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """Result of one check on one series.

    Attributes
    ----------
    flags : numpy.ndarray of int32
        One :class:`~sivin.core.flags.QcFlag` bit field per sample, in row order (read-only).
    events : tuple of QualityEvent
        Events the check reported, in time order.

    Raises
    ------
    ValueError
        If ``flags`` is not one-dimensional or contains bits that are not QC flags.
    """

    flags: FlagArray
    events: tuple[QualityEvent, ...] = ()

    def __post_init__(self) -> None:
        flags = np.array(self.flags, dtype=QC_DTYPE)
        if flags.ndim != 1:
            raise ValueError(f"flags must be one-dimensional, got shape {flags.shape}.")
        if np.any(np.bitwise_and(flags.astype(np.int64), ~np.int64(QcFlag.all_bits()))):
            raise ValueError("flags contain negative values or bits that are not QcFlag values.")
        flags.setflags(write=False)
        object.__setattr__(self, "flags", flags)
        object.__setattr__(
            self, "events", tuple(sorted(self.events, key=lambda event: event.t_utc))
        )

    @classmethod
    def from_mask(
        cls,
        mask: npt.NDArray[np.bool_],
        flag: QcFlag,
        events: Iterable[QualityEvent] = (),
    ) -> CheckOutcome:
        """Build an outcome that sets one flag where ``mask`` is true.

        Parameters
        ----------
        mask : numpy.ndarray of bool
            ``True`` for the samples that get ``flag``.
        flag : QcFlag
            The flag to set.
        events : iterable of QualityEvent, optional
            Events to report.

        Returns
        -------
        CheckOutcome
            The outcome.
        """
        flags = np.where(mask, np.int32(flag), np.int32(QcFlag.OK)).astype(QC_DTYPE)
        return cls(flags=flags, events=tuple(events))

    def count(self, flag: QcFlag) -> int:
        """Count the samples that carry ``flag``.

        Parameters
        ----------
        flag : QcFlag
            A single flag.

        Returns
        -------
        int
            Number of samples with the flag set.
        """
        return int(np.count_nonzero(np.bitwise_and(self.flags, np.int32(flag))))


class QualityCheck[S: CheckSettings](ABC):
    """Abstract quality check of one series.

    Subclasses set :attr:`check_id` and :attr:`settings_model`, implement :meth:`check` and
    register themselves with :data:`check_registry`.

    Attributes
    ----------
    check_id : str
        Unique name of the check, the key in the registry and in the configuration.
    settings_model : type[CheckSettings]
        Pydantic model of the settings; must be the type argument ``S``.

    Parameters
    ----------
    settings : S, optional
        Settings; defaults of :attr:`settings_model` when omitted.

    Raises
    ------
    TypeError
        If ``settings`` is not an instance of :attr:`settings_model`.
    """

    check_id: ClassVar[str]
    settings_model: ClassVar[type[CheckSettings]]

    def __init__(self, settings: S | None = None) -> None:
        model = type(self).settings_model
        if settings is None:
            settings = cast(S, model())
        if not isinstance(settings, model):
            raise TypeError(
                f"{type(self).__name__} expects {model.__name__}, got {type(settings).__name__}."
            )
        self._settings: S = settings

    @property
    def settings(self) -> S:
        """The (immutable) settings of this check."""
        return self._settings

    @abstractmethod
    def check(self, series: MeasurementSeries) -> CheckOutcome:
        """Check a series.

        Parameters
        ----------
        series : MeasurementSeries
            The measurements of one sensor.

        Returns
        -------
        CheckOutcome
            One flag bit field per row of ``series`` and the events found.
        """

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._settings!r})"


type CheckClass = type[QualityCheck[Any]]
"""A concrete :class:`QualityCheck` subclass."""


class CheckRegistry:
    """Registry of quality check classes, keyed by :attr:`QualityCheck.check_id`.

    Registries are the one kind of module-level mutable state the project allows
    (MIGRATION_PLAN §1.2, point 2): they are filled by class decorators when the module that
    defines a check is imported, and never changed afterwards.
    """

    __slots__ = ("_classes",)

    def __init__(self) -> None:
        self._classes: dict[str, CheckClass] = {}

    def register[C: CheckClass](self, cls: C) -> C:
        """Register a check class; use as a class decorator.

        Parameters
        ----------
        cls : type[QualityCheck]
            The class to register.

        Returns
        -------
        type[QualityCheck]
            The class unchanged.

        Raises
        ------
        TypeError
            If the class is not a concrete :class:`QualityCheck` with ``check_id`` and
            ``settings_model``.
        ValueError
            If the ``check_id`` is already registered.
        """
        if not (isinstance(cls, type) and issubclass(cls, QualityCheck)):
            raise TypeError(f"Only QualityCheck subclasses can be registered, got {cls!r}.")
        if getattr(cls, "__abstractmethods__", None):
            raise TypeError(f"{cls.__name__} is abstract and cannot be registered.")
        check_id = getattr(cls, "check_id", None)
        if not isinstance(check_id, str) or not check_id:
            raise TypeError(f"{cls.__name__} must define a non-empty class variable 'check_id'.")
        model = getattr(cls, "settings_model", None)
        if not (isinstance(model, type) and issubclass(model, CheckSettings)):
            raise TypeError(
                f"{cls.__name__} must set 'settings_model' to a CheckSettings subclass, "
                f"got {model!r}."
            )
        if check_id in self._classes:
            raise ValueError(
                f"Check id {check_id!r} is already registered by "
                f"{self._classes[check_id].__qualname__}."
            )
        self._classes[check_id] = cls
        logger.debug("Registered quality check %r (%s).", check_id, cls.__qualname__)
        return cls

    def create(self, check_id: str, settings: Mapping[str, Any] | None = None) -> QualityCheck[Any]:
        """Instantiate a registered check with validated settings.

        Parameters
        ----------
        check_id : str
            Name of a registered check.
        settings : Mapping, optional
            Raw setting values (e.g. from the configuration); defaults when omitted.

        Returns
        -------
        QualityCheck
            A new check instance.

        Raises
        ------
        KeyError
            If no check with this name is registered.
        pydantic.ValidationError
            If the settings do not fit the check's settings model.
        """
        cls = self.get(check_id)
        return cls(cls.settings_model.model_validate(dict(settings or {})))

    def get(self, check_id: str) -> CheckClass:
        """Return the class registered under ``check_id``.

        Parameters
        ----------
        check_id : str
            Name of a registered check.

        Returns
        -------
        type[QualityCheck]
            The registered class.

        Raises
        ------
        KeyError
            If no check with this name is registered.
        """
        try:
            return self._classes[check_id]
        except KeyError:
            raise KeyError(
                f"Unknown quality check {check_id!r}; registered: "
                f"{', '.join(self.ids()) or 'none'}."
            ) from None

    def ids(self) -> tuple[str, ...]:
        """Return the registered check names, sorted.

        Returns
        -------
        tuple of str
            Sorted names.
        """
        return tuple(sorted(self._classes))

    def __contains__(self, check_id: object) -> bool:
        return check_id in self._classes

    def __len__(self) -> int:
        return len(self._classes)


check_registry: Final = CheckRegistry()
"""The project-wide registry of quality checks (filled on import of :mod:`sivin.quality.checks`)."""
