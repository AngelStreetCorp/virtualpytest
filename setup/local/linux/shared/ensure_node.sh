#!/bin/bash
# VirtualPyTest - Node.js version guard (CVE-2026-111497 / "HTTP2Shell")
#
# Node.js vendors Google Brotli in node:zlib. Brotli 1.0.3 .. 1.2.0 has an
# out-of-bounds write in the decoder (c/dec/decode.c), so any Node process that
# decodes a Brotli payload can be driven to heap corruption and remote code
# execution: pre-auth on a server that accepts `Content-Encoding: br` request
# bodies, and client-side on a process that fetches a Brotli response from a
# host it does not control.
#
# Node fixed it in 22.23.4, 24.22.1 and 26.12.1. The fix is a cherry-pick of
# the upstream Brotli commit, NOT a version bump — `process.versions.brotli`
# still reports 1.1.0 / 1.2.0 on the fixed builds, so the Node version itself
# is the only reliable signal. Node 18, 20, 23 and 25 are EOL and get no fix:
# they have to move to a supported line.
#
# Usage:
#   source ensure_node.sh
#   ensure_patched_node <target_major> [sudo_cmd]
#
# <target_major> is the supported LTS line an EOL host is moved to (22).
# <sudo_cmd> is "sudo" on a normal install, or "" when running as root.
# Returns 1 (without touching anything else) when the host still runs a
# vulnerable build, so the install stops instead of shipping a broken host.

# The fixed build of each supported line. Anything not listed here is EOL.
VPT_NODE_FIXED_VERSIONS=(
    "22:22.23.4"
    "24:24.22.1"
    "26:26.12.1"
)

# node_fixed_min_version <major> -> the fixed build of that line, or "" when the
# line is EOL and has no upstream fix.
node_fixed_min_version() {
    local major="$1" pair
    for pair in "${VPT_NODE_FIXED_VERSIONS[@]}"; do
        if [ "${pair%%:*}" = "$major" ]; then
            echo "${pair##*:}"
            return 0
        fi
    done
    echo ""
}

# node_version_at_least <have> <want> -> true when <have> >= <want>
node_version_at_least() {
    [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" = "$2" ]
}

# ensure_patched_node <target_major> [sudo_cmd]
#
# Leaves the host on a Node.js build without CVE-2026-111497:
#   * a host already on a fixed build of its own line is left alone;
#   * a host below the fixed build of its own line is upgraded in place;
#   * a host on an EOL line (18/20/23/25) is moved to <target_major>.
ensure_patched_node() {
    local target_major="${1:-22}"
    local sudo_cmd="${2:-sudo}"
    local current_version="" current_major="" fixed_min=""
    local install_major="$target_major"

    local setup_cmd=(bash -)
    local apt_cmd=(apt-get)
    if [ -n "$sudo_cmd" ]; then
        # No -E: some sudoers policies refuse to preserve the environment
        # ("sorry, you are not allowed to preserve the environment") and the
        # NodeSource setup script then fails silently, leaving the host on the
        # old runtime. The script picks its own sudo up from $EUID, so running
        # it as root is enough.
        setup_cmd=("$sudo_cmd" bash -)
        apt_cmd=("$sudo_cmd" apt-get)
    fi

    if command -v node >/dev/null 2>&1; then
        current_version="$(node --version | sed 's/^v//')"
        current_major="${current_version%%.*}"
        fixed_min="$(node_fixed_min_version "$current_major")"

        if [ -n "$fixed_min" ] && node_version_at_least "$current_version" "$fixed_min"; then
            echo "✅ Node.js ${current_version} is patched for CVE-2026-111497"
            return 0
        fi

        if [ -n "$fixed_min" ]; then
            # Same line, just below the fixed build: upgrade in place.
            install_major="$current_major"
        fi
        # Otherwise the line is EOL with no upstream fix -> move to target_major.
    fi

    echo "🔧 Installing Node.js ${install_major}.x (CVE-2026-111497 fix)..."
    if [ -n "$current_version" ] && [ "${current_major:-0}" != "$install_major" ]; then
        echo "   Removing the old Node.js ${current_version} first"
        "${apt_cmd[@]}" remove -y nodejs npm >/dev/null 2>&1 || true
    fi
    # Add the NodeSource repository for this line. The exit status of the piped
    # setup script is checked: a silent failure here used to leave the host on
    # the old runtime while the install reported success.
    if ! curl -fsSL "https://deb.nodesource.com/setup_${install_major}.x" | "${setup_cmd[@]}" >/dev/null 2>&1; then
        echo "   ❌ Could not add the NodeSource repository for Node.js ${install_major}.x"
        echo "      (check the network to deb.nodesource.com and the sudo policy on this host)"
        return 1
    fi
    "${apt_cmd[@]}" update >/dev/null 2>&1 || true
    "${apt_cmd[@]}" install -y nodejs

    local installed_version="" installed_min=""
    installed_version="$(node --version 2>/dev/null | sed 's/^v//')"
    if [ -n "$installed_version" ]; then
        installed_min="$(node_fixed_min_version "${installed_version%%.*}")"
    fi
    if [ -z "$installed_version" ] || [ -z "$installed_min" ] || ! node_version_at_least "$installed_version" "$installed_min"; then
        echo "❌ Node.js ${installed_version:-not installed} is still vulnerable to CVE-2026-111497 (HTTP2Shell)"
        echo "   Required: 22.23.4 / 24.22.1 / 26.12.1 or newer on a supported line"
        return 1
    fi
    echo "✅ Node.js ${installed_version} installed (patched for CVE-2026-111497)"
    return 0
}
