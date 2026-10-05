"""Export parsers (WP-1.2): portal CSV and XLSX exports and the legacy workbook.

Importing this package registers every parser with
:data:`~sivin.ingest.parsers.base.parser_registry`; use
``parser_registry.for_file(path, settings)`` to pick the parser of a file.
"""

from sivin.ingest.parsers import legacy, portal

__all__ = ["legacy", "portal"]
