"""Application services: the subsystems composed into the steps of the pipeline (WP-1.7).

The command-line interface (:mod:`sivin.cli`) only parses options, calls these services and
prints their reports; everything else lives here and is tested without the CLI.

* :class:`~sivin.app.workspace.Workspace` — project root and resolved configuration;
* :class:`~sivin.app.factory.ServiceFactory` — builds the services from the configuration;
* :mod:`~sivin.app.catalog` (``sensors check``), :mod:`~sivin.app.fetch` (``fetch``, needs the
  ``ingest`` extra), :mod:`~sivin.app.ingest` (``ingest``), :mod:`~sivin.app.quality`
  (``qc``), :mod:`~sivin.app.indices` (``indices``), :mod:`~sivin.app.run` (``run``);
* :class:`~sivin.app.outcome.Outcome` — exit codes; :class:`~sivin.app.outcome.SetupError`.
"""
