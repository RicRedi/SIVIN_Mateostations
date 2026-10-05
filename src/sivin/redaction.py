"""Redaction of the portal credentials at every boundary that leaves the process.

One :class:`SecretRedactor`, built from the loaded credentials, is applied to the log records
(:mod:`sivin.logging_setup`), to everything the CLI prints, to the run record
(``data/runs/*.jsonl``, committed to the public ``data`` branch) and to the derived JSON files.
The values of ``SIVIN_USER`` and ``SIVIN_PASSWORD`` are replaced by ``***`` wherever they
occur, also inside exception messages (WP-1.7 review rounds 1 and 2).

Values shorter than :data:`MIN_SECRET_LENGTH` are **not** redacted: replacing every
occurrence of e.g. ``vut`` would mangle file names and messages and reveal the value by its
pattern. Such a credential is reported once (by name, never by value) through
:attr:`SecretRedactor.unredactable`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, Self

SECRET_ENV_VARS: Final = ("SIVIN_PASSWORD", "SIVIN_USER")
"""Environment variables whose values never leave the process."""

REDACTED: Final = "***"
"""Replacement text of a secret value."""

MIN_SECRET_LENGTH: Final = 4
"""Shortest value (characters) that is redacted; shorter ones are reported instead."""


@dataclass(frozen=True, slots=True)
class SecretRedactor:
    """Replace secret values by ``***`` in texts and JSON-like data.

    Attributes
    ----------
    secrets : tuple of str
        Values to redact (at least :data:`MIN_SECRET_LENGTH` characters), longest first.
    unredactable : tuple of str
        Names (never values) of credentials too short to be redacted safely.
    """

    secrets: tuple[str, ...] = ()
    unredactable: tuple[str, ...] = field(default=())

    @classmethod
    def of(cls, named: Mapping[str, str]) -> Self:
        """Build a redactor from named secret values.

        Parameters
        ----------
        named : Mapping of str to str
            Name (e.g. ``SIVIN_PASSWORD``) → value; empty values are ignored.

        Returns
        -------
        SecretRedactor
            Redacts the values with at least :data:`MIN_SECRET_LENGTH` characters.
        """
        values = {name: value for name, value in named.items() if value}
        long_enough = {v for v in values.values() if len(v) >= MIN_SECRET_LENGTH}
        short = tuple(sorted(n for n, v in values.items() if len(v) < MIN_SECRET_LENGTH))
        return cls(tuple(sorted(long_enough, key=len, reverse=True)), short)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Build a redactor from ``SIVIN_USER`` and ``SIVIN_PASSWORD``.

        Parameters
        ----------
        environ : Mapping, optional
            The environment; :data:`os.environ` when omitted.

        Returns
        -------
        SecretRedactor
            The redactor of the current credentials.
        """
        env = os.environ if environ is None else environ
        return cls.of({name: env.get(name, "") for name in SECRET_ENV_VARS})

    def including(self, named: Mapping[str, str]) -> SecretRedactor:
        """Return a redactor that also redacts further secrets.

        Parameters
        ----------
        named : Mapping of str to str
            Name → value of the additional secrets (e.g. the credentials a fetch uses).

        Returns
        -------
        SecretRedactor
            The combined redactor.
        """
        extra = SecretRedactor.of(named)
        secrets = sorted(set(self.secrets) | set(extra.secrets), key=len, reverse=True)
        names = tuple(sorted(set(self.unredactable) | set(extra.unredactable)))
        return SecretRedactor(tuple(secrets), names)

    def redact(self, text: str) -> str:
        """Return ``text`` with every secret replaced by ``***``.

        Parameters
        ----------
        text : str
            Any text.

        Returns
        -------
        str
            The redacted text.
        """
        for secret in self.secrets:
            text = text.replace(secret, REDACTED)
        return text

    def redact_data(self, value: object) -> object:
        """Return JSON-like data with every string redacted (keys included).

        Parameters
        ----------
        value : object
            Mappings, sequences, strings and plain values, nested freely.

        Returns
        -------
        object
            The same structure; tuples become lists.
        """
        if not self.secrets:
            return value
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, Mapping):
            return {self.redact(str(k)): self.redact_data(v) for k, v in value.items()}
        if isinstance(value, Iterable) and not isinstance(value, bytes | bytearray):
            return [self.redact_data(item) for item in value]
        return value
