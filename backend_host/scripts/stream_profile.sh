#!/bin/bash
# stream_profile.sh — TASK-102 STREAM_PROFILE loader (sourced by run_ffmpeg.sh).
#
# Bundle table: one named profile expands to STREAM_TYPE_DEFAULT + VAAPI_MODE +
# VAAPI_MIN_QUALITY + SW_THREADS + MONITOR_PROFILE + HOST_TIER_CAP. Per-device
# DEVICE<N>_* overrides win at the per-device loop (run_ffmpeg.sh). A typo'd
# profile name falls back to stream_hls_720p (24 cap, the safe default).
# Hosts that don't set STREAM_PROFILE keep their hand-tuned keys (legacy mode).
#
# Caps are the nipogi 8c/13.9 GB ceiling per TASK-95 §8: smaller hosts can
# override with HOST_TIER_CAP=N in .env (the contract is in TASK-100 §3).
#
# DEFAULT_STREAM_QUALITY (low|sd|hd) is the quality every device streams after a (re)start of vpt-stream;
# run_ffmpeg.sh get_device_quality uses it when active_captures.conf has no entry (it is wiped on start).
# An operator STREAM_QUALITY in .env wins over the profile.
#
# Source this file with: source stream_profile.sh  (or . stream_profile.sh)
# Requires bash 4+ for the declare -A associative array.
apply_stream_profile() {
  declare -A STREAM_PROFILES=(
    ["stream_local_hd"]="STREAM_TYPE_DEFAULT=videofile VAAPI_MODE=off VAAPI_MIN_QUALITY=low SW_THREADS=1 MONITOR_PROFILE=tv_lite HOST_TIER_CAP=12 DEFAULT_STREAM_QUALITY=hd"
    ["stream_local_360p"]="STREAM_TYPE_DEFAULT=videofile VIDEOFILE_COPY=1 VAAPI_MODE=off VAAPI_MIN_QUALITY=low SW_THREADS=1 MONITOR_PROFILE=tv_lite HOST_TIER_CAP=48 DEFAULT_STREAM_QUALITY=low"
    ["stream_hls_720p"]="STREAM_TYPE_DEFAULT=hls      VAAPI_MODE=decode_only VAAPI_MIN_QUALITY=low SW_THREADS=1 MONITOR_PROFILE=tv_lite HOST_TIER_CAP=24 DEFAULT_STREAM_QUALITY=low"
    ["stream_hls_360p"]="STREAM_TYPE_DEFAULT=hls      VAAPI_MODE=off VAAPI_MIN_QUALITY=low SW_THREADS=1 MONITOR_PROFILE=tv_lite HOST_TIER_CAP=48 DEFAULT_STREAM_QUALITY=low"
  )
  if [ -n "${STREAM_PROFILE:-}" ]; then
    if [ -v "STREAM_PROFILES[${STREAM_PROFILE}]" ]; then
      echo "INFO: STREAM_PROFILE=${STREAM_PROFILE} — applying bundled env"
      for kv in ${STREAM_PROFILES[${STREAM_PROFILE}]}; do
        export "${kv%%=*}=${kv#*=}"
      done
    else
      echo "WARN: unknown STREAM_PROFILE='${STREAM_PROFILE}' — falling back to stream_hls_720p" >&2
      STREAM_PROFILE=stream_hls_720p
      for kv in ${STREAM_PROFILES[${STREAM_PROFILE}]}; do
        export "${kv%%=*}=${kv#*=}"
      done
    fi
  else
    # No STREAM_PROFILE set: legacy mode (operator-set VAAPI_MODE / SW_THREADS / etc.).
    # STREAM_TYPE_DEFAULT is "hls" — same default the autodetect used before TASK-102.
    STREAM_TYPE_DEFAULT="${STREAM_TYPE_DEFAULT:-hls}"
  fi
  export STREAM_PROFILE STREAM_TYPE_DEFAULT
}

# Echo the active profile's name + cap as "name|cap" on stdout. Used by
# scripts/apply_stream_profile.sh and by /host/system/config (TASK-102 §8).
# Returns 0 even when no profile is set (output is "legacy|").
stream_profile_summary() {
  apply_stream_profile
  echo "${STREAM_PROFILE:-legacy}|${HOST_TIER_CAP:-}"
}
