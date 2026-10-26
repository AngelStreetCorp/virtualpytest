"""Regression checks for stale deployment cleanup without importing host dependencies."""

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = (_ROOT / 'backend_host/src/services/deployment_scheduler.py').read_text()


def test_stale_scheduler_cleanup_closes_linked_script_result():
    # `script_name` is what a dead execution needs to find the script_results row it orphaned
    # (BUG-0837): the row is matched on host + bare script name when the stdout-scraped
    # `script_result_id` is NULL, which is always the case for a run that never finished.
    assert "script_result_id, started_at, scheduled_at, deployments!inner(host_name, script_name)" in _SOURCE
    assert "script_result_id, deployments!inner(host_name, device_id, name, script_name)" in _SOURCE
    assert "self.supabase.table('script_results').update" in _SOURCE
    assert "'error_msg': error_message" in _SOURCE


def test_a_coc_llm_run_is_not_called_stale_while_it_is_still_playing():
    """A CoC LLM run lasts 20-60 min: the 30 min threshold marked healthy runs as failed (BUG-0717)."""
    assert "max_age_s = 5400 if 'game_clashofclans_llm' in run_script else 3600" in _SOURCE
    assert "max_age_s = 1800 if 'game_clashofclans_llm' in run_script else 3600" not in _SOURCE
