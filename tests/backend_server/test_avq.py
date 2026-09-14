"""avq feature — the per-minute Audio/Video Quality series.

`/server/monitoring/avq` (features/avq/backend_server/) returns the `quality_metrics`
rows that drive the AVQ device page and the Grafana dashboard. Two properties of that
endpoint are load-bearing and easy to break silently, so they are pinned here:

  * **the series is ascending in time** — the timeline renders it directly, and the query
    deliberately fetches DESC + limit then reverses, so an ordering regression is invisible
    until a chart looks wrong.
  * **when the PostgREST 1000-row cap bites, the MOST RECENT rows survive** — the naive
    query would keep the oldest and quietly show a stale window.

  * `host_name` must filter, because `device_id` is NOT unique across hosts ('device1'
    exists on several) — without it rows from different physical devices get mixed.

Tier A: server API only, no device. Read-only, so nothing to clean up.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

from .conftest import assert_not_auth_failure

KPI_COLUMNS = {
    "timestamp", "device_id", "host_name",
    "video_availability", "video_mos", "freeze_seconds", "blackscreen_seconds",
    "macroblocks_seconds", "clean_video_seconds",
    "audio_availability", "audio_mos", "audio_level_db", "loudness_lkfs", "silence_seconds",
}


def _avq(get, api_headers, **params):
    return get("/server/monitoring/avq", headers=api_headers, params=params)


@pytest.fixture(scope="module")
def avq_source():
    """(host_name, device_id) expected to have AVQ rows; override with AVQ_HOST/AVQ_DEVICE.

    AVQ only collects where `vpt-avq.service` runs — as of 2026-09-07 that is host-clone-1
    and *not* the sample-app fleet (no vpt-avq unit installed there at all) — so the tests skip
    rather than fail when the environment they run against has no collector.
    """
    return (os.environ.get("AVQ_HOST", "host-clone-1"),
            os.environ.get("AVQ_DEVICE", "host"))


@pytest.fixture
def avq_rows(get, api_headers, avq_source):
    host_name, device_id = avq_source
    response = _avq(get, api_headers, device_id=device_id, host_name=host_name, hours=2)
    assert_not_auth_failure(response, "reading AVQ metrics")
    if response.status_code != 200:
        pytest.skip(f"AVQ endpoint unavailable ({response.status_code})")
    rows = response.json().get("metrics") or []
    if not rows:
        pytest.skip(f"no AVQ rows for {host_name}/{device_id} — is vpt-avq running there?")
    return rows


class TestAvqEndpoint:
    def test_device_id_is_required(self, get, api_headers):
        response = _avq(get, api_headers, hours=1)
        assert response.status_code == 400, response.text[:200]
        assert "device_id" in response.json().get("error", "")

    def test_count_matches_the_series_length(self, get, api_headers, avq_source):
        host_name, device_id = avq_source
        response = _avq(get, api_headers, device_id=device_id, host_name=host_name, hours=2)
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        assert body.get("success") is True
        assert body.get("count") == len(body.get("metrics") or [])

    def test_rows_carry_the_per_minute_kpi_columns(self, avq_rows):
        missing = KPI_COLUMNS - set(avq_rows[0])
        assert not missing, f"AVQ rows lost columns the page and dashboard read: {sorted(missing)}"

    def test_host_name_filters_the_series(self, avq_rows, avq_source):
        """Currently trivially satisfied — only host-clone-1 collects AVQ, so there is
        nothing to mix. Kept because the invariant is real and the moment a second host
        starts collecting (any sample-app host gaining vpt-avq) this becomes load-bearing."""
        host_name, _ = avq_source
        wrong = {r.get("host_name") for r in avq_rows} - {host_name}
        assert not wrong, (
            f"rows from other hosts leaked in: {sorted(wrong)}. device_id is not unique "
            f"across hosts, so an unfiltered query mixes different physical devices."
        )

    def test_window_is_respected(self, get, api_headers, avq_source):
        host_name, device_id = avq_source
        hours = 2
        response = _avq(get, api_headers, device_id=device_id, host_name=host_name, hours=hours)
        rows = response.json().get("metrics") or []
        if not rows:
            pytest.skip("no AVQ rows in the window")

        # Allow a minute of slack for the row that straddles the boundary.
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours, minutes=1)
        oldest = datetime.fromisoformat(rows[0]["timestamp"])
        assert oldest >= cutoff, f"row older than the requested {hours}h window: {rows[0]['timestamp']}"


class TestAvqSeriesOrdering:
    """Properties the timeline depends on."""

    def test_series_is_ascending_in_time(self, avq_rows):
        stamps = [r["timestamp"] for r in avq_rows]
        assert stamps == sorted(stamps), "AVQ series is not ascending — the timeline renders it directly"

    def test_capped_window_keeps_the_most_recent_rows(self, get, api_headers, avq_source):
        """The query fetches DESC + limit then reverses precisely so a capped window shows
        the newest data. Reverting that would return the OLDEST 1000 rows and the page would
        silently display a stale window with no error."""
        host_name, device_id = avq_source
        response = _avq(get, api_headers, device_id=device_id, host_name=host_name, hours=720)
        assert response.status_code == 200, response.text[:300]

        rows = response.json().get("metrics") or []
        if len(rows) < 1000:
            pytest.skip(f"window not capped ({len(rows)} rows) — nothing to prove here")

        newest = datetime.fromisoformat(rows[-1]["timestamp"])
        age = datetime.now(timezone.utc) - newest
        assert age < timedelta(hours=6), (
            f"capped window ends at {rows[-1]['timestamp']} ({age} old) — the cap appears to "
            f"be keeping the OLDEST rows, so the page would show a stale window"
        )


class TestAvqZaps:
    def test_team_id_and_device_name_are_required(self, get, api_headers):
        response = get("/server/monitoring/zaps", headers=api_headers, params={"hours": 1})
        assert response.status_code == 400, response.text[:200]
        error = response.json().get("error", "")
        assert "team_id" in error and "device_name" in error

    def test_returns_a_counted_list(self, get, api_headers, team_id, avq_source):
        host_name, _ = avq_source
        response = get(
            "/server/monitoring/zaps",
            headers=api_headers,
            params={"team_id": team_id, "device_name": f"{host_name}_Host",
                    "host_name": host_name, "hours": 24},
        )
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        assert body.get("success") is True
        assert body.get("count") == len(body.get("zaps") or [])
