"""Renderings of a :class:`~sivin.app.summary.RunSummary`: Markdown (job summary) and text.

Every format is a :class:`SummaryFormat` registered in :data:`summary_format_registry` under its
``name``; ``sivin report --format NAME`` picks one. A format only defines the primitives
(heading, paragraph, table, list); the content and its order are shared
(:meth:`SummaryFormat.render`), so both formats always say the same.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import ClassVar, Final
from zoneinfo import ZoneInfo

from sivin.app.summary import RunSummary
from sivin.storage.registry import NamedRegistry
from sivin.storage.runlog import RunRecord

TITLE: Final = "SIVIN pipeline run"

NO_RECORD: Final = (
    "No run record of this run was found: the run stopped before it wrote one (see the exit "
    "code above and the job log). Nothing was added to the store."
)

_SECONDS_PER_MINUTE: Final = 60

_UTC_FORMAT: Final = "%Y-%m-%d %H:%M:%S UTC"
_LOCAL_FORMAT: Final = "%Y-%m-%d %H:%M %Z"


class SummaryFormat(ABC):
    """A rendering of the run summary; subclasses define the text primitives.

    Register a new format with ``@summary_format_registry.register`` and a class variable
    ``name``.
    """

    name: ClassVar[str] = ""

    def render(self, summary: RunSummary) -> str:
        """Return the whole summary as text.

        Parameters
        ----------
        summary : RunSummary
            What to show.

        Returns
        -------
        str
            The document, ending with a line break.
        """
        blocks = [self.heading(TITLE, 2), *self._outcome(summary)]
        record = summary.record
        blocks.extend(self._record(summary, record) if record is not None else [NO_RECORD])
        blocks.extend(self._warnings(summary))
        return "\n\n".join(block for block in blocks if block) + "\n"

    @abstractmethod
    def heading(self, text: str, level: int) -> str:
        """Return a heading.

        Parameters
        ----------
        text : str
            Plain text.
        level : int
            2 for the title, 3 for a section.

        Returns
        -------
        str
            The heading block.
        """

    @abstractmethod
    def text(self, value: str) -> str:
        """Return plain text (e.g. a message from the run record) safe for the format.

        Parameters
        ----------
        value : str
            Plain text.

        Returns
        -------
        str
            Escaped text.
        """

    @abstractmethod
    def table(self, header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
        """Return a table of plain-text cells.

        Parameters
        ----------
        header : sequence of str
            Column titles.
        rows : sequence of sequences of str
            Cells, row by row.

        Returns
        -------
        str
            The table block.
        """

    @abstractmethod
    def items(self, values: Sequence[str]) -> str:
        """Return a bullet list of plain-text items.

        Parameters
        ----------
        values : sequence of str
            Items.

        Returns
        -------
        str
            The list block.
        """

    def _outcome(self, summary: RunSummary) -> list[str]:
        outcome = summary.outcome
        if outcome is None:
            return []
        return [
            self.text(f"Outcome: {outcome.status.value} (exit code {outcome.code}). ")
            + self.text(outcome.meaning)
        ]

    def _record(self, summary: RunSummary, record: RunRecord) -> list[str]:
        blocks = [
            self.text(_timing(record, summary.display_timezone)),
            self.table(
                ("Item", "Count"),
                (
                    ("export files processed", str(len(record.files))),
                    ("files rejected", str(len(summary.rejected_files))),
                    ("rows added to the store", str(summary.new_rows)),
                    ("other failures", str(len(summary.other_failures))),
                    ("warning kinds (sensor, kind)", str(len(summary.warnings))),
                ),
            ),
            self.heading("Rows added per sensor", 3),
            self._appends(summary),
        ]
        limit = summary.settings.max_items
        if record.validation_issues:
            blocks += [
                self.heading("Input validation findings", 3),
                self.table(
                    ("Finding", "Count"),
                    [(name, str(count)) for name, count in record.validation_issues.items()],
                ),
            ]
        for title, values in (
            ("Rejected files", summary.rejected_files),
            ("Failures", summary.other_failures),
            ("Derived results not updated", _derived(summary)),
            ("Export files", record.files),
        ):
            if values:
                blocks += [self.heading(title, 3), self.items(_capped(values, limit))]
        return blocks

    def _appends(self, summary: RunSummary) -> str:
        if not summary.appends:
            return self.text("No rows were added.")
        return self.table(
            ("Sensor", "New rows", "Filled values", "Conflicting values", "Replaced values"),
            [
                (
                    str(sensor),
                    str(counts.new_rows),
                    str(counts.filled_values),
                    str(counts.conflicting_values),
                    str(counts.replaced_values),
                )
                for sensor, counts in summary.appends.items()
            ],
        )

    def _warnings(self, summary: RunSummary) -> list[str]:
        if not summary.warnings:
            return [self.heading("Warnings", 3), self.text("No QC warnings in the stored data.")]
        limit = summary.settings.max_items
        rows = [
            (
                group.sensor_id,
                group.kind,
                str(group.count),
                _interval(group.latest_t, group.latest_t_end),
                group.latest_detail,
            )
            for group in summary.warnings[:limit]
        ]
        blocks = [
            self.heading("Warnings", 3),
            self.text(
                "QC warnings over each sensor's whole stored record, most recent first "
                "(e.g. low_battery, unlogged_off_site: check the off-site log)."
            ),
            self.table(("Sensor", "Kind", "Count", "Latest (UTC)", "Latest detail"), rows),
        ]
        hidden = len(summary.warnings) - limit
        if hidden > 0:
            blocks.append(self.text(f"... and {hidden} more."))
        return blocks


def _derived(summary: RunSummary) -> tuple[str, ...]:
    return tuple(f"events {item.sensor_id}: {item.error}" for item in summary.derived_failures)


def _capped(values: Sequence[str], limit: int) -> list[str]:
    """Return at most ``limit`` values and a line counting the rest."""
    shown = list(values[:limit])
    if len(values) > limit:
        shown.append(f"... and {len(values) - limit} more")
    return shown


def _interval(start: str | None, end: str | None) -> str:
    if start is None:
        return "-"
    return start if end is None or end == start else f"{start} .. {end}"


def _timing(record: RunRecord, zone: str) -> str:
    """Return ``Run started ... (local ...), took ...``."""
    local = record.started_at.astimezone(ZoneInfo(zone))
    seconds = int((record.finished_at - record.started_at).total_seconds())
    minutes, rest = divmod(seconds, _SECONDS_PER_MINUTE)
    return (
        f"Run started {_utc(record.started_at)} ({local.strftime(_LOCAL_FORMAT)}), "
        f"took {minutes} min {rest} s."
    )


def _utc(moment: datetime) -> str:
    return moment.strftime(_UTC_FORMAT)


summary_format_registry: Final = NamedRegistry[SummaryFormat](SummaryFormat)
"""The registered summary formats, by ``name``."""

_MARKDOWN_SPECIAL: Final = re.compile(r"([\\`*_\[\]<>|~&#])")
"""ASCII punctuation that could start Markdown or HTML markup; escaped with a backslash."""


def markdown_text(value: str) -> str:
    """Escape plain text for GitHub-flavoured Markdown (one line).

    Parameters
    ----------
    value : str
        Plain text, e.g. a failure message.

    Returns
    -------
    str
        The text with markup characters backslash-escaped and line breaks as spaces, so a
        message can neither break a table nor inject HTML or links.
    """
    return _MARKDOWN_SPECIAL.sub(r"\\\1", " ".join(value.splitlines()))


@summary_format_registry.register
class MarkdownSummary(SummaryFormat):
    """GitHub-flavoured Markdown, for ``$GITHUB_STEP_SUMMARY``."""

    name: ClassVar[str] = "markdown"

    def heading(self, text: str, level: int) -> str:
        return f"{'#' * level} {markdown_text(text)}"

    def text(self, value: str) -> str:
        return markdown_text(value)

    def table(self, header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
        lines = [
            _row(header),
            _row(["---"] * len(header), escape=False),
            *(_row(row) for row in rows),
        ]
        return "\n".join(lines)

    def items(self, values: Sequence[str]) -> str:
        return "\n".join(f"- {markdown_text(value)}" for value in values)


def _row(cells: Sequence[str], escape: bool = True) -> str:
    texts = [markdown_text(cell) if escape else cell for cell in cells]
    return "| " + " | ".join(texts) + " |"


@summary_format_registry.register
class TextSummary(SummaryFormat):
    """Plain text for a terminal: aligned columns, no markup."""

    name: ClassVar[str] = "text"

    def heading(self, text: str, level: int) -> str:
        return text.upper() if level <= 2 else f"{text}:"

    def text(self, value: str) -> str:
        return " ".join(value.splitlines())

    def table(self, header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
        lines = [list(header), *(list(row) for row in rows)]
        cells = [[self.text(cell) for cell in line] for line in lines]
        widths = [max(len(line[column]) for line in cells) for column in range(len(header))]
        return "\n".join(
            "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
            for line in cells
        )

    def items(self, values: Sequence[str]) -> str:
        return "\n".join(f"- {self.text(value)}" for value in values)
