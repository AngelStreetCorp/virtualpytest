#!/bin/bash

# VirtualPyTest - Android Emulator Post-Boot Optimizer
# Run this INSIDE the VM after the emulator has booted.
# It disables animations, unnecessary services, and fixes "System UI not responding" ANRs.
#
# Usage: bash optimize_emulator.sh
# Can be run multiple times safely (idempotent).
# Docs:  docs/agent/devices/EMULATOR.md

set -euo pipefail

EMU="emulator-5554"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  VirtualPyTest — Emulator Post-Boot Optimizer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check ADB
if ! adb -s "$EMU" get-state 2>/dev/null | grep -q "device"; then
    echo "ERROR: Emulator not found or not ready (adb -s $EMU get-state)"
    echo "Wait for the emulator to fully boot, then retry."
    exit 1
fi

# 1. Dismiss any ANR dialogs
echo "1. Dismissing any ANR dialogs..."
adb -s "$EMU" shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS 2>/dev/null || true
adb -s "$EMU" shell input keyevent KEYCODE_HOME 2>/dev/null || true
echo "   Done"

# 2. Disable all animations (reduces CPU load significantly)
echo "2. Disabling animations..."
adb -s "$EMU" shell settings put global window_animation_scale 0
adb -s "$EMU" shell settings put global transition_animation_scale 0
adb -s "$EMU" shell settings put global animator_duration_scale 0
echo "   Done"

# 3. Increase screen-off timeout (prevent lock screen during tests)
echo "3. Setting screen timeout to 30 minutes..."
adb -s "$EMU" shell settings put system screen_off_timeout 1800000
echo "   Done"

# 4. Disable background ANR dialogs for non-foreground apps
echo "4. Disabling background ANR dialogs..."
adb -s "$EMU" shell settings put secure anr_show_background 0
# A test device's screen is what the capture records; an ANR/crash dialog left on it after
# the post-boot storm (gms, Gmail, search) hides the app under test for as long as nobody
# taps "Wait" — 12 days once. The failures still land in logcat and /data/anr.
adb -s "$EMU" shell settings put global hide_error_dialogs 1
echo "   Done"

# 5. Disable auto-updates and unnecessary background activity
echo "5. Disabling auto-updates and background sync..."
adb -s "$EMU" shell settings put global package_verifier_enable 0 2>/dev/null || true
adb -s "$EMU" shell settings put global auto_time 0 2>/dev/null || true
adb -s "$EMU" shell content update --uri content://com.google.settings/partner --bind value:s:0 --where "name='use_location_for_services'" 2>/dev/null || true
echo "   Done"

# 6. Force-stop heavy background apps that cause ANRs
echo "6. Stopping heavy background apps..."
for pkg in com.google.android.apps.nexuslauncher \
           com.google.android.apps.wellbeing \
           com.google.android.apps.turbo \
           com.google.android.setupwizard \
           com.google.android.apps.restore; do
    adb -s "$EMU" shell am force-stop "$pkg" 2>/dev/null || true
done
echo "   Done"

# 7. Verify
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Verification:"
echo "  Animations: $(adb -s "$EMU" shell settings get global window_animation_scale)"
echo "  Screen timeout: $(adb -s "$EMU" shell settings get system screen_off_timeout)ms"
echo "  Background ANR: $(adb -s "$EMU" shell settings get secure anr_show_background)"
echo "  Error dialogs hidden: $(adb -s "$EMU" shell settings get global hide_error_dialogs)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Emulator optimized. If 'System UI not responding' persists:"
echo "  adb -s $EMU shell am force-stop com.android.systemui"
echo "  adb -s $EMU shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS"
