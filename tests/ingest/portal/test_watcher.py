"""Tests of DownloadWatcher: only new, complete, size-stable files count."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from sivin.ingest.portal.clock import SystemClock
from sivin.ingest.portal.errors import DownloadTimeoutError
from sivin.ingest.portal.watcher import DownloadWatcher

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
