"""Login credentials for the data provider's portal, read only from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Self

from sivin.ingest.portal.errors import MissingCredentialsError

USER_ENV_VAR: Final = "SIVIN_USER"
"""Environment variable holding the portal user name."""

PASSWORD_ENV_VAR: Final = "SIVIN_PASSWORD"
"""Environment variable holding the portal password."""

_MASK: Final = "***"


@dataclass(frozen=True, slots=True, repr=False)
class PortalCredentials:
    """User name and password for the portal.

    The password never appears in :func:`repr`, :func:`str` or log messages. Credentials are
    never read from configuration files (MIGRATION_PLAN §1.3); use :meth:`from_env`.

    Parameters
    ----------
    username : str
        Portal user name (non-empty).
    password : str
        Portal password (non-empty).

    Raises
    ------
    MissingCredentialsError
        If either value is empty.
    """

    username: str
    password: str

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise MissingCredentialsError("Portal user name and password must not be empty.")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Read the credentials from ``SIVIN_USER`` and ``SIVIN_PASSWORD``.

        Parameters
        ----------
        environ : Mapping[str, str], optional
            Environment to read; :data:`os.environ` when omitted (tests pass a dict).

        Returns
        -------
        PortalCredentials
            The credentials.

        Raises
        ------
        MissingCredentialsError
            If a variable is unset or empty. The message names the variable, never its value.
        """
        env = os.environ if environ is None else environ
        missing = [name for name in (USER_ENV_VAR, PASSWORD_ENV_VAR) if not env.get(name)]
        if missing:
            raise MissingCredentialsError(
                f"Environment variable(s) {', '.join(missing)} not set; put them into .env "
                "locally or into the repository secrets in GitHub Actions."
            )
        return cls(username=env[USER_ENV_VAR], password=env[PASSWORD_ENV_VAR])

    def __repr__(self) -> str:
        return f"PortalCredentials(username={self.username!r}, password={_MASK!r})"

    def __str__(self) -> str:
        return repr(self)
