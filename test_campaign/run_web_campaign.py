#!/usr/bin/env python3
"""Campaign script to run all scripts in test_scripts/web."""

from __future__ import annotations

import sys

from _campaign_batch_common import execute_batch_campaign


if __name__ == "__main__":
    sys.exit(
        execute_batch_campaign(
            campaign_id="run-web-campaign",
            campaign_name="run_web_campaign",
            campaign_description="Run all Python scripts under test_scripts/web",
            default_ui="example_mobile",
            cli_description="Execute all test_scripts/web Python scripts sequentially",
            include_dirs=["test_scripts/web"],
            exclude_scripts=[
                "test_scripts/web/browser_task.py",
                "test_scripts/web/netflix_video_check.py",
                "test_scripts/web/exampletv_go_home.py",
            ],
        )
    )
