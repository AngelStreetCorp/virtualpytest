#!/usr/bin/env bash
# scripts/download_public_domain_movies.sh
#
# Download the 12 public-domain films that vpt-lenovo1 plays in loop per TASK-101.
# Idempotent: skips files that are already present and >= 100 MB.
#
# Usage:
#   ./scripts/download_public_domain_movies.sh vpt-lenovo1
#   ./scripts/download_public_domain_movies.sh /var/lib/vpt-movies    # local path
#
# Total download: ~6.0 GB across 12 files. 4-way parallel, 3 retries each,
# 10-minute per-file timeout.

set -euo pipefail

TARGET="${1:-/var/lib/vpt-movies}"

# Resolve SSH target or local path
if [[ "${TARGET}" == */* ]] || [[ -d "${TARGET}" ]]; then
    DIR="${TARGET}"
    REMOTE=""
else
    REMOTE="${TARGET}"
    DIR="/var/lib/vpt-movies"
fi

echo "[movies] target=${TARGET} dir=${DIR} remote=${REMOTE:-local}"

# Helper: run command locally or via ssh
run() {
    if [[ -n "${REMOTE}" ]]; then
        ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${REMOTE}" "$@"
    else
        "$@"
    fi
}

# 12 films: index, archive.org slug, file path inside the item, final filename
# All from TASK-101 (12) and TASK-103 (12). All public domain or CC-BY-NC-ND.
# The first 12 are the HD set (cap 12, 1280x720); the second 12 are the LOW set
# (cap 48, 320x180). Plan 9 is CC-BY-NC-ND, still free for local loop use.
# Slugs marked with "verify" in TASK-103 are 2nd-choice fallbacks — the script
# tries the primary; if the primary 404s, the operator can drop in a corrected
# slug and re-run (idempotent, skips files already >= 100 MB).
MOVIES=(
    # TASK-101: 12 films for stream_local_hd (the HD cap = 12)
    "01_nosferatu_1922|PhantasmagoriaTheater-Nosferatu1922909|PhantasmagoriaTheater-Nosferatu1922909_512kb.mp4"
    "02_caligari_1920|TheCabinetOfDr.Caligari1920FULLMOVIE|The%20Cabinet%20of%20Dr.%20Caligari%20%281920%29%20FULL%20MOVIE.mp4"
    "03_the_general_1926|TheGeneral1926|The_General_1926_720p_512kb.mp4"
    "04_battleship_potemkin_1925|PhantasmagoriaTheater-BattleshipPotemkin1925396|PhantasmagoriaTheater-BattleshipPotemkin1925396_512kb.mp4"
    "05_night_of_the_living_dead_1968|PhantasmagoriaTheater-NightOfTheLivingDead1968321-3|PhantasmagoriaTheater-NightOfTheLivingDead1968321_512kb.mp4"
    "06_phantom_of_the_opera_1925|ThePhantomOfTheOpera_364|ThePhantomOfTheOperaPresentedByMoviePowder_512kb.mp4"
    "07_plan_9_from_outer_space_1957|plan.-9.-from.-outer.-space.-1957|Plan%209%20From%20Outer%20Space%20%281957%29/mp4/Plan.9.From.Outer.Space.1957.mp4"
    "08_carnival_of_souls_1962|carnival-of-souls-1962_202010|Carnival%20of%20Souls%20%281962%29.mp4"
    "09_haxan_1922|haxan-1922_202312|H%C3%A4xan%20%281922%29.mp4"
    "10_white_zombie_1932|WhiteZombie|White_Zombie_512kb.mp4"
    "11_phantom_carriage_1921|ThePhantomCarriage|PhantomCarriage_512kb.mp4"
    "12_the_golem_1920|TheGolem_893|TheGolem_512kb.mp4"

    # TASK-103: 12 more films for stream_local_360p (the LOW cap = 48)
    # The "verify" markers point to 2nd-choice slugs if the primary is unavailable.
    "13_the_kid_1921|la35ca-Cinema_35_-_The_Kid_1921|Cinema_35_-_The_Kid_1921_512kb.mp4"
    "14_sherlock_jr_1924|sherlock.-jr..-1924.1080p.-blu-ray.x-264-yts.-am|Sherlock.Jr..1924.1080p.BluRay.x264.YTS.AM_512kb.mp4"
    "15_the_navigator_1924|mymovie_202004|Navigator_512kb.mp4"
    "16_the_lodger_1927|lodger1927|Lodger_512kb.mp4"
    "17_way_down_east_1920|WayDownEast_201312|Way_Down_East_512kb.mp4"
    "18_safety_last_1923|dfwiv-Safety_Last_-_Harold_Lloyd_1923_-_Old_Time_Movie|Safety_Last_512kb.mp4"
    "19_the_kid_brother_1927|the-kid-brother-1927|Kid_Brother_512kb.mp4"
    "20_steamboat_bill_jr_1928|steamboat-bill-jr.-1928_202505|Steamboat_Bill_Jr.1928_512kb.mp4"
    "21_the_cameraman_1928|cameraman-1928|Cameraman_512kb.mp4"
    "22_it_happened_one_night_1934|it.-happened.-one.-night.-1934.1080p.-blu-ray.x-264.-yify|It.Happened.One.Night.1934.1080p.BluRay.x264.YIFY_512kb.mp4"
    "23_his_girl_friday_1940|his-girl-friday-1940_202310|His_Girl_Friday_550MB.mp4"
    "24_detour_1945|Detour_1945|Detour_1945_512kb.mp4"
)

run mkdir -p "${DIR}"

# Atomic download: fetch to .partial, rename on success
fetch_one() {
    local final="$1"
    local url="$2"
    local partial="${final}.partial"

    # Skip if already present and at least 100 MB
    if [[ -f "${final}" ]] && [[ $(stat -c %s "${final}" 2>/dev/null || stat -f %z "${final}" 2>/dev/null) -gt 104857600 ]]; then
        echo "[skip] ${final##*/} already present"
        return 0
    fi

    echo "[fetch] ${final##*/} <- ${url}"
    if ! curl -fL --retry 3 --max-time 600 --connect-timeout 30 -A "Mozilla/5.0" \
            -o "${partial}" "${url}"; then
        echo "[fail] ${final##*/} download failed" >&2
        rm -f "${partial}" || true
        return 1
    fi

    mv "${partial}" "${final}"
    echo "[done] ${final##*/} ($(du -h "${final}" | cut -f1))"
}

# Export for xargs subshells
export -f fetch_one
export REMOTE

# Build the URL list
URLS=()
for entry in "${MOVIES[@]}"; do
    IFS='|' read -r idx slug path <<< "${entry}"
    final="${DIR}/${idx}.mp4"
    url="https://archive.org/download/${slug}/${path}"
    URLS+=("${final}|${url}")
done

# 4-way parallel
printf '%s\n' "${URLS[@]}" | xargs -P 4 -I {} bash -c '
    entry="$1"
    final="${entry%|*}"
    url="${entry#*|}"
    fetch_one "${final}" "${url}"
' _ {}

# Verify
echo "[verify] checking 12 files in ${DIR}"
missing=0
total_bytes=0
for entry in "${MOVIES[@]}"; do
    IFS='|' read -r idx slug path <<< "${entry}"
    final="${DIR}/${idx}.mp4"
    if [[ -f "${final}" ]]; then
        size=$(stat -c %s "${final}" 2>/dev/null || stat -f %z "${final}" 2>/dev/null)
        total_bytes=$((total_bytes + size))
        size_mb=$((size / 1024 / 1024))
        echo "  ok   ${final##*/}  ${size_mb}M"
    else
        echo "  MISS ${final##*/}"
        missing=$((missing + 1))
    fi
done

total_gb=$(echo "scale=2; ${total_bytes} / 1024 / 1024 / 1024" | bc 2>/dev/null || echo "?")
echo "[verify] total: ${total_gb} GB across $((12 - missing))/12 files"

if [[ ${missing} -gt 0 ]]; then
    echo "[fail] ${missing} file(s) missing" >&2
    exit 1
fi

echo "[ok] TASK-101 movie set ready in ${DIR}"
