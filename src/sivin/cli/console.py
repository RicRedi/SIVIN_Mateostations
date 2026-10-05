"""The only way the commands print: every line passes the process's secret redactor."""

from __future__ import annotations

import typer

from sivin.redaction import SecretRedactor


class Console:
    """Print command output with the credentials replaced by ``***``.

    Parameters
    ----------
    redactor : SecretRedactor, optional
        The secrets to hide; none until :meth:`use` is called.
    """

    __slots__ = ("_redactor",)

    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        self._redactor = redactor if redactor is not None else SecretRedactor()

    @property
    def redactor(self) -> SecretRedactor:
        """The redactor applied to every printed text."""
        return self._redactor

    def use(self, redactor: SecretRedactor) -> None:
        """Replace the redactor (after ``.env`` has been loaded).

        Parameters
        ----------
        redactor : SecretRedactor
            The secrets to hide from now on.
        """
        self._redactor = redactor

    def echo(self, text: str, err: bool = False, nl: bool = True) -> None:
        """Print ``text`` with the secrets redacted.

        Parameters
        ----------
        text : str
            The text.
        err : bool, optional
            Print to standard error.
        nl : bool, optional
            End with a line break.
        """
        typer.echo(self._redactor.redact(text), err=err, nl=nl)


console = Console()
"""The console of the ``sivin`` process; :class:`~sivin.cli.state.CliState` sets its redactor."""
