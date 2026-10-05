"""Shared contracts of all subsystems: sensor identity, measurement schema, QC flags, time.

Import from the submodules (``sivin.core.ids``, ``.flags``, ``.schema``, ``.timeutil``,
``.daily``, ``.season``, ``.defaults``). This package deliberately re-exports nothing, so that
importing a light module such as :mod:`sivin.core.flags` does not load pandas.
"""
