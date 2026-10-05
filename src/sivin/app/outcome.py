"""Outcome of a command: the exit codes of ``sivin`` and the error that stops a command early."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import IntEnum
from typing import Self


class Outcome(IntEnum):
    """How a command ended; the value is the process exit code (``docs/cli.md``)."""

    OK = 0
    """Everything succeeded."""
    PARTIAL_FAILURE = 1
    """The command ran, but some items failed (a file rejected, a device not downloaded, a
    sensor not processed) or a check found problems (``sensors check``)."""
    USAGE_ERROR = 2
    """Invalid command-line usage (unknown option, bad value); set by the CLI framework."""
    SETUP_ERROR = 3
    """The command could not start: invalid configuration, registry or off-site log, not
    inside the project."""
    DATA_SOURCE_UNAVAILABLE = 4
    """The data provider's portal could not be used: missing credentials, failed login, portal
    or browser unreachable. ``sivin run`` still processes the stored data and ends with this
    code, so a scheduled job can tell a broken portal from a routine partial failure."""
    INTERNAL_ERROR = 5
    """An unexpected exception (a bug): the traceback is printed to standard error with the
    credentials redacted (:func:`sivin.cli.main.entry_point`)."""

    @classmethod
    def of(cls, failures: Sequence[str]) -> Self:
        """Return :attr:`OK` without failures, :attr:`PARTIAL_FAILURE` with some.

        Parameters
        ----------
        failures : sequence of str
            One message per failed item.

        Returns
        -------
        Outcome
            The outcome.
        """
        return cls.PARTIAL_FAILURE if failures else cls.OK

    @classmethod
    def worst(cls, outcomes: Iterable[Outcome]) -> Outcome:
        """Return the most severe of several outcomes (:attr:`OK` for none).

        Parameters
        ----------
        outcomes : iterable of Outcome
            Outcomes of the steps of a command.

        Returns
        -------
        Outcome
            The one with the highest exit code.
        """
        return max(outcomes, default=cls.OK)


class SetupError(RuntimeError):
    """A command cannot start (configuration, registry, off-site log, project).

    The message is meant for the user and names what to fix; it never contains a secret.
    """


class SourceUnavailableError(SetupError):
    """The portal cannot be used: missing credentials, failed login, unreachable portal.

    Exit code :attr:`Outcome.DATA_SOURCE_UNAVAILABLE` (4); the message never contains a secret.
    """


class UnknownIndexError(ValueError):
    """Raised when a requested index id is not registered (a usage error of ``sivin indices``)."""
