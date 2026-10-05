"""Fixtures of the application-service tests (temporary projects, see ``project.py``)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.app.project import Project, make_project

from sivin.app.factory import ServiceFactory
from sivin.app.workspace import Workspace
from sivin.ingest.portal.credentials import PortalCredentials, Secret

RUN_TIME = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
"""Fixed clock of the services in the tests."""


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A project with the real registry and off-site log and the test configuration."""
    return make_project(tmp_path / "project")


def make_factory(project: Project) -> ServiceFactory:
    """Build the services of a project with a fixed clock and synthetic credentials."""
    return ServiceFactory(
        Workspace.open(start=project.root),
        credentials=lambda: PortalCredentials("synthetic-user", Secret("synthetic-Secret-42")),
        clock=lambda: RUN_TIME,
    )


@pytest.fixture
def factory(project: Project) -> ServiceFactory:
    """The services of :func:`project`."""
    return make_factory(project)
