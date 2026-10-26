#!/bin/bash
# Mac: run pull_lol_dataset.py every 10 minutes (launchd agent com.virtualpytest.lol-pull). Remove: launchctl unload + rm the plist.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
P="$HOME/Library/LaunchAgents/com.virtualpytest.lol-pull.plist"
cat > "$P" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.virtualpytest.lol-pull</string>
<key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$ROOT/scripts/lol_practice/pull_lol_dataset.py</string><string>--no-log</string></array>
<key>StartInterval</key><integer>600</integer>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>/tmp/lol-pull.log</string><key>StandardErrorPath</key><string>/tmp/lol-pull.log</string>
</dict></plist>
EOF
launchctl unload "$P" 2>/dev/null || true
launchctl load "$P"
echo "installed $P (runs $ROOT/scripts/lol_practice/pull_lol_dataset.py --no-log every 10 min; REVIEW_LOG.md is updated by running the script without --no-log from a worktree)"
