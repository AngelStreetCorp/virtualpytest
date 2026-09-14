#!/usr/bin/env python3
"""Campaign script to run all scripts in test_scripts/gw."""

from __future__ import annotations

import sys

from _campaign_batch_common import execute_batch_campaign


if __name__ == "__main__":
    sys.exit(
        execute_batch_campaign(
            campaign_id="run-gw-campaign",
            campaign_name="run_gw_campaign",
            campaign_description="Run all Python scripts under test_scripts/gw",
            default_ui="example_mobile",
            cli_description="Execute all test_scripts/gw Python scripts sequentially",
            include_dirs=["test_scripts/gw"],
            exclude_scripts=["test_scripts/gw/udp_latency.py", "test_scripts/gw/gw_network_connect.py"],
        )
    )
