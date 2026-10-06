"""Tests of DownloadWatcher: only new, complete, size-stable files count."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from sivin.core.ids import SensorId
from sivin.ingest.portal.clock import SystemClock
from sivin.ingest.portal.errors import DownloadIncompleteError, DownloadTimeoutError
from sivin.ingest.portal.watcher import DirectorySnapshot, DownloadWatcher, FileKind

POLL_S = 1.0
TIMEOUT_S = 10.0


def _watcher(directory: Path, clock: Any) -> DownloadWatcher:
    return DownloadWatcher(directory, timeout_s=TIMEOUT_S, poll_interval_s=POLL_S, clock=clock)


def test_new_file_is_returned_after_two_equal_sizes(tmp_path: Path, fake_clock: Any) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    (tmp_path / "MeteoData_new.xlsx").write_bytes(b"12345")

    assert watcher.wait_for_new_file(before) == tmp_path / "MeteoData_new.xlsx"
    # Poll 1 sees the size, one pause, poll 2 sees the same size.
    assert fake_clock.sleeps == [POLL_S]


def test_pre_existing_file_is_never_returned(tmp_path: Path, fake_clock: Any) -> None:
    (tmp_path / "MeteoData_old.xlsx").write_bytes(b"old export")
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    (tmp_path / "MeteoData_old.xlsx").write_bytes(b"old export, touched again")

    with pytest.raises(DownloadTimeoutError, match="within 10 s"):
        watcher.wait_for_new_file(before)
    # Polls at t = 0, 1, ..., 10 s; the 11th poll is at the deadline.
    assert fake_clock.now_s == TIMEOUT_S


@pytest.mark.parametrize(
    "name", ["export.xlsx.crdownload", "export.tmp", ".com.google.Chrome.a1b2c3"]
)
def test_partial_and_hidden_files_are_ignored(tmp_path: Path, fake_clock: Any, name: str) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    (tmp_path / name).write_bytes(b"partial")

    with pytest.raises(DownloadTimeoutError):
        watcher.wait_for_new_file(before)


def test_waits_for_rename_and_for_a_stable_size(tmp_path: Path, fake_clock: Any) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    partial = tmp_path / "export.xlsx.crdownload"
    final = tmp_path / "export.xlsx"
    partial.write_bytes(b"ab")

    def browser(now_s: float) -> None:
        if now_s == 2.0:  # renamed after 2 s, still being written
            partial.rename(final)
        elif now_s == 3.0:  # grows once more after 3 s
            final.write_bytes(b"abcd")

    fake_clock.on_sleep.append(browser)

    assert watcher.wait_for_new_file(before) == final
    # Seen at t = 2 s (2 B), t = 3 s (4 B), t = 4 s (4 B) -> stable at 4 s.
    assert fake_clock.now_s == 4.0


def test_several_new_files_give_the_first_by_name(
    tmp_path: Path, fake_clock: Any, caplog: pytest.LogCaptureFixture
) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    (tmp_path / "b.xlsx").write_bytes(b"b")
    (tmp_path / "a.xlsx").write_bytes(b"a")

    with caplog.at_level(logging.WARNING):
        assert watcher.wait_for_new_file(before) == tmp_path / "a.xlsx"
    assert "Several new downloads" in caplog.text


def test_detects_a_file_written_by_another_thread(tmp_path: Path) -> None:
    watcher = DownloadWatcher(tmp_path, timeout_s=5.0, poll_interval_s=0.01, clock=SystemClock())
    before = watcher.snapshot()
    target = tmp_path / "MeteoData_thread.xlsx"
    writer = threading.Timer(0.05, target.write_bytes, args=(b"synthetic",))
    writer.start()
    try:
        assert watcher.wait_for_new_file(before) == target
    finally:
        writer.join()


def test_snapshot_creates_the_directory_and_skips_subdirectories(
    tmp_path: Path, fake_clock: Any
) -> None:
    directory = tmp_path / "missing"
    watcher = _watcher(directory, fake_clock)

    assert watcher.snapshot().names == frozenset()
    assert watcher.directory == directory
    (directory / "subdir").mkdir()
    with pytest.raises(DownloadTimeoutError):
        watcher.wait_for_new_file(watcher.snapshot())


def test_file_vanishing_during_listing_is_skipped(
    tmp_path: Path, fake_clock: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    (tmp_path / "gone.xlsx").write_bytes(b"x")
    original_is_file = Path.is_file

    def is_file_then_delete(self: Path) -> bool:
        result = original_is_file(self)
        if self.name == "gone.xlsx":
            self.unlink()  # the browser removes the file between listing and stat
        return result

    monkeypatch.setattr(Path, "is_file", is_file_then_delete)

    assert "gone.xlsx" not in watcher.snapshot().names


@pytest.mark.parametrize(("timeout_s", "poll_s"), [(0.0, 1.0), (1.0, 0.0)])
def test_non_positive_times_are_rejected(
    tmp_path: Path, fake_clock: Any, timeout_s: float, poll_s: float
) -> None:
    with pytest.raises(ValueError, match="positive"):
        DownloadWatcher(tmp_path, timeout_s=timeout_s, poll_interval_s=poll_s, clock=fake_clock)


def test_system_clock_is_monotonic() -> None:
    clock = SystemClock()
    start = clock.monotonic()
    clock.sleep(0.001)
    assert clock.monotonic() > start


def test_late_finish_of_a_download_pending_at_snapshot_is_ignored(
    tmp_path: Path, fake_clock: Any
) -> None:
    # Review probe: A times out while A.xlsx.crdownload is still written; B's snapshot holds
    # the partial file, and A.xlsx appears during B's wait. It must not become B's file.
    watcher = _watcher(tmp_path, fake_clock)
    (tmp_path / "A.xlsx.crdownload").write_bytes(b"x")
    before_b = watcher.snapshot()
    assert before_b.pending == frozenset({"A.xlsx"})

    def browser(now_s: float) -> None:
        if now_s == 1.0:
            (tmp_path / "A.xlsx.crdownload").rename(tmp_path / "A.xlsx")
        elif now_s == 2.0:
            (tmp_path / "B.xlsx").write_bytes(b"b")

    fake_clock.on_sleep.append(browser)

    assert watcher.wait_for_new_file(before_b) == tmp_path / "B.xlsx"


def test_files_left_by_a_timeout_are_ignored_by_later_waits(
    tmp_path: Path, fake_clock: Any, caplog: pytest.LogCaptureFixture
) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    before_a = watcher.snapshot()
    (tmp_path / "A.xlsx.crdownload").write_bytes(b"x")
    with caplog.at_level(logging.WARNING), pytest.raises(DownloadTimeoutError):
        watcher.wait_for_new_file(before_a)
    assert watcher.orphaned == frozenset({"A.xlsx"})
    assert "Files of the timed-out download will be ignored: ['A.xlsx']" in caplog.text

    (tmp_path / "A.xlsx.crdownload").rename(tmp_path / "A.xlsx")
    with pytest.raises(DownloadTimeoutError):
        watcher.wait_for_new_file(DirectorySnapshot(frozenset()))


def test_export_of_another_sensor_is_skipped(
    tmp_path: Path, fake_clock: Any, caplog: pytest.LogCaptureFixture
) -> None:
    # Chrome may use names like "Unconfirmed 123.crdownload", so the final name of a late
    # download is not always derivable; the serial in the export name still is.
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    (tmp_path / "MeteoData_8615620 77678271.xlsx").write_bytes(b"late export of A")

    def browser(now_s: float) -> None:
        if now_s == 2.0:
            (tmp_path / "MeteoData_8615621 77678272.xlsx").write_bytes(b"export of B")

    fake_clock.on_sleep.append(browser)

    with caplog.at_level(logging.WARNING):
        path = watcher.wait_for_new_file(before, expected=SensorId("77678272"))

    assert path.name == "MeteoData_8615621 77678272.xlsx"
    assert "it is the export of 77678271, not of 77678272" in caplog.text
    assert "MeteoData_8615620 77678271.xlsx" in watcher.orphaned


def test_matching_and_unnamed_exports_are_accepted(tmp_path: Path, fake_clock: Any) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    (tmp_path / "MeteoData_8615620 77678271.xlsx").write_bytes(b"x")
    assert watcher.wait_for_new_file(before, expected=SensorId("77678271")).name == (
        "MeteoData_8615620 77678271.xlsx"
    )
    before = watcher.snapshot()
    (tmp_path / "export.xlsx").write_bytes(b"x")
    assert watcher.wait_for_new_file(before, expected=SensorId("77678271")).name == "export.xlsx"


def test_empty_file_is_an_incomplete_download(tmp_path: Path, fake_clock: Any) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    (tmp_path / "empty.xlsx").write_bytes(b"")

    with pytest.raises(DownloadIncompleteError, match=r"smaller than 1 B.*empty\.xlsx"):
        watcher.wait_for_new_file(before)


def test_placeholder_that_fills_later_is_accepted(tmp_path: Path, fake_clock: Any) -> None:
    watcher = DownloadWatcher(
        tmp_path, timeout_s=TIMEOUT_S, poll_interval_s=POLL_S, clock=fake_clock, min_size_bytes=4
    )
    before = watcher.snapshot()
    target = tmp_path / "export.xlsx"
    target.write_bytes(b"ab")
    fake_clock.on_sleep.append(lambda now_s: target.write_bytes(b"abcd") if now_s == 3.0 else None)

    assert watcher.wait_for_new_file(before) == target
    # Too small but stable at t = 1, 2 s; 4 B at t = 3 s, stable at t = 4 s.
    assert fake_clock.now_s == 4.0


def test_file_appearing_at_the_deadline_gets_one_confirmation_poll(
    tmp_path: Path, fake_clock: Any
) -> None:
    watcher = _watcher(tmp_path, fake_clock)
    before = watcher.snapshot()
    target = tmp_path / "late.xlsx"
    fake_clock.on_sleep.append(
        lambda now_s: target.write_bytes(b"ok") if now_s == TIMEOUT_S else None
    )

    assert watcher.wait_for_new_file(before) == target
    assert fake_clock.now_s == TIMEOUT_S + POLL_S


def test_minimum_size_must_be_positive(tmp_path: Path, fake_clock: Any) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        DownloadWatcher(tmp_path, 1.0, 1.0, fake_clock, min_size_bytes=0)


@pytest.mark.parametrize(
    ("name", "size_bytes", "kind"),
    [
        ("export.xlsx", 5, FileKind.COMPLETE),
        ("export.xlsx", 0, FileKind.TOO_SMALL),
        ("export.xlsx.crdownload", 0, FileKind.UNFINISHED),
        ("export.tmp", 9, FileKind.UNFINISHED),
        (".com.google.Chrome.abc", 0, FileKind.IGNORED),
        (".hidden.xlsx", 9, FileKind.IGNORED),
    ],
)
def test_classify_applies_the_name_rules_before_the_size(
    tmp_path: Path, fake_clock: Any, name: str, size_bytes: int, kind: FileKind
) -> None:
    assert _watcher(tmp_path, fake_clock).classify(name, size_bytes) is kind
