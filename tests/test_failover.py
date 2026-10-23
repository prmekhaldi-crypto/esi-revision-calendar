from pathlib import Path

from esi_revision_calendar import cli


def test_failed_feed_download_does_not_replace_previous_output(tmp_path, monkeypatch):
    output = tmp_path / "revision-calendar.ics"
    original = b"previous valid calendar\r\n"
    output.write_bytes(original)

    def fail(_urls):
        raise cli.FeedDownloadError("network unavailable")

    monkeypatch.setattr(cli, "fetch_calendars", fail)
    result = cli.main(["--output", str(output), "--start", "2026-10-23T17:30:00+01:00"])
    assert result == 1
    assert output.read_bytes() == original
