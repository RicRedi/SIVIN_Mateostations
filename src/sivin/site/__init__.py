"""The static site data of the web portal (MIGRATION_PLAN §2.6, WP-3.2).

:class:`~sivin.site.builder.SiteBuilder` turns the quality-controlled measurements, events and
index results into ``site/data``: one writer class per file kind
(:mod:`~sivin.site.sensor_files`, :mod:`~sivin.site.site_files`), pure column builders
(:mod:`~sivin.site.columns`) and an incremental build state (:mod:`~sivin.site.state`). The
application layer (:mod:`sivin.app.site`) wires it to the store, quality control and indices.
Details: ``docs/site.md``.
"""

from sivin.site.builder import SiteBuilder, SiteInputs, SiteReport
from sivin.site.settings import SiteSettings

__all__ = ["SiteBuilder", "SiteInputs", "SiteReport", "SiteSettings"]
