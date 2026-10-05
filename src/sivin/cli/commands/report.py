"""Plain-text summaries of the application reports (standard output, one line per item)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from sivin.cli.common import echo_failures

if TYPE_CHECKING:
    from sivin.app.indices import IndicesReport
    from sivin.app.ingest import IngestReport
    from sivin.app.quality import QualityReport


def echo_ingest(report: IngestReport) -> None:
    """Print one line per file and the failures.

    Parameters
    ----------
    report : IngestReport
        Result of the ingest step.
    """
    for item in report.files:
        rows = ", ".join(f"{sensor} {count} rows" for sensor, count in item.rows.items())
        if item.failure is None:
            appended = ", ".join(
                f"{sensor} +{counts.new_rows} new, {counts.filled_values} filled, "
                f"{counts.conflicting_values} conflicting"
                for sensor, counts in item.appends.items()
            )
            status = "VALID" if report.dry_run else "IMPORTED"
            typer.echo(
                f"{status} {item.path.name}: {rows}" + (f" ({appended})" if appended else "")
            )
            for issue in item.report.warnings:
                typer.echo(f"  {issue}")
        else:
            where = f" -> {item.quarantined}" if item.quarantined is not None else ""
            typer.echo(f"REJECTED {item.path.name}{where}")
    echo_failures(report.failures)
    if report.dry_run:
        typer.echo("Dry run: nothing was written.")


def echo_quality(report: QualityReport) -> None:
    """Print one line per sensor and the failures.

    Parameters
    ----------
    report : QualityReport
        Result of the QC step.
    """
    for sensor, item in report.sensors.items():
        if item.result is None:
            if item.failure is None:
                typer.echo(f"{sensor}: no stored data")
            continue
        result = item.result
        flags = ", ".join(
            f"{flag.name} {count}" for flag, count in result.flag_counts.items() if count
        )
        warnings = sum(1 for event in result.events if event.severity == "warning")
        line = (
            f"{sensor}: {len(result.series)} samples, flags: {flags or 'none'}, "
            f"{len(result.events)} event(s) ({warnings} warning(s)), "
            f"{result.values_set_aside} value(s) set aside"
        )
        typer.echo(line + (f" -> {item.events_file}" if item.events_file is not None else ""))
    echo_failures(report.failures)


def echo_indices(report: IndicesReport) -> None:
    """Print one line per sensor and index and the failures.

    Parameters
    ----------
    report : IndicesReport
        Result of the indices step.
    """
    typer.echo(f"Season {report.window.season} (data {report.window.first}..{report.window.last})")
    for sensor, results in report.results.items():
        for index_id, result in results.items():
            value = "-" if result.value is None else f"{result.value:.6g} {result.unit}"
            completeness = "complete" if result.complete else "incomplete"
            typer.echo(
                f"{sensor} {index_id}: {value} (coverage {result.coverage:.2f}, {completeness})"
            )
    if report.file is not None:
        typer.echo(f"Written: {report.file}")
    echo_failures(report.failures)
