#!/bin/bash

# VirtualPyTest - Bootstrap Script (Modular Architecture)
# Shared functions for VirtualPyTest installation setup
# Provides modular setup functions for different installer types

set -e

# Shared rsync exclusions for local Linux installs.
# Keep this aligned with deployment sync behavior so installers do not push
# large local-only artifacts into /opt/virtualpytest.
VPT_INSTALL_RSYNC_EXCLUDES=(
    --exclude '.git'
    --exclude '.github'
    --exclude '.cursor'
    --exclude '.claude'
    --exclude '.codex'
    --exclude '.husky'
    --exclude '.pytest_cache'
    --exclude '.DS_Store'
    --exclude '.env'
    --exclude 'venv'
    --exclude 'node_modules'
    --exclude '__pycache__'
    --exclude '*.pyc'
    --exclude '*.pyo'
    --exclude 'tmp'
    --exclude 'security_report'
    --exclude 'playwright-report*'
    --exclude 'playwright-viewport-report*'
    --exclude 'frontend/dist'
    --exclude 'frontend/public/docs'
    --exclude 'frontend/vite.config.local.json'
    --exclude 'frontend/public/branding.json'
    --exclude 'frontend/public/brand'
    --exclude 'frontend/public/favicon.ico'
    --exclude 'frontend/public/logo.png'
    --exclude 'backend_host/config/user_data'
    --exclude 'backend_host/backend_host/config/user_data'
    --exclude 'backend_host/config/webkit_user_data'
    --exclude 'backend_host/src/backend_host/config/webkit_user_data'
    --exclude 'test_scripts/script_identity_map.json'
    --exclude 'test_campaign/campaign_identity_map.json'
)

# ============================================================================
# LEVEL 0: Git Hooks Setup (Run First)
# ============================================================================

# Configure git to use .githooks directory
# This makes hooks version-controlled and shared across all developers
# Usage: setup_git_hooks
setup_git_hooks() {
    local repo_root="$1"

    if [ -z "$repo_root" ]; then
        repo_root=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
    fi

    if [ -z "$repo_root" ] || [ ! -d "$repo_root/.git" ]; then
        echo "❌ Not a git repository. Git is required for installs."
        return 1
    fi

    if [ -d "$repo_root/.githooks" ]; then
        echo "🔧 Configuring git hooks..."
        git -C "$repo_root" config core.hooksPath .githooks
        echo "✅ Git hooks configured (using .githooks/)"
    else
        echo "⚠️  .githooks directory not found, skipping"
        return 0
    fi

    # .githooks/pre-push runs the leak gate (customer identifiers + credentials). Both of
    # its halves degrade to a SKIP rather than a failure when their input is missing, so
    # say so here — a gate that silently checks nothing is worse than no gate.
    if [ -x "$repo_root/scripts/security/leak_gate.sh" ]; then
        if ! command -v gitleaks >/dev/null 2>&1; then
            echo "⚠️  gitleaks not installed — the pre-push SECRET check will be skipped."
            echo "    Install it:  brew install gitleaks   |   https://github.com/gitleaks/gitleaks"
        fi
        if [ ! -f "$repo_root/docs/agent/leak-terms.local.txt" ]; then
            echo "⚠️  No docs/agent/leak-terms.local.txt — the pre-push IDENTIFIER check will be skipped."
            echo "    cp docs/agent/leak-terms.local.txt.example docs/agent/leak-terms.local.txt and fill it in"
            echo "    (gitignored on purpose; see docs/agent/release/ANONYMIZATION.md)"
        fi
    fi
}

# ============================================================================
# LEVEL 1: User Management (Lowest Dependency)
# ============================================================================

# Create VirtualPyTest service user only
# No directory creation, no project copying
# Usage: ensure_vpt_user "$SOURCE_ROOT"
ensure_vpt_user() {
    local source_dir="$1"
    
    # If source_dir is not provided or invalid, try to find it from the calling script
    if [ -z "$source_dir" ] || [ ! -d "$source_dir" ] || [ ! -f "$source_dir/README.md" ]; then
        # Try to find the source directory by going up from calling script location
        local calling_script="${BASH_SOURCE[1]}"
        if [ -n "$calling_script" ]; then
            local script_dir="$(cd "$(dirname "$calling_script")" && pwd)"
            # Go up 4 levels from script dir (script/subdir/install.sh → project root)
            source_dir="$(cd "$script_dir/../../../.." 2>/dev/null && pwd)"
        fi
    fi
    
    # Validate the source directory
    if [ -z "$source_dir" ] || [ ! -f "$source_dir/README.md" ]; then
        echo "❌ Could not find valid VirtualPyTest source directory"
        echo "   Tried auto-detection from calling script"
        echo "   Please ensure you're running from a valid VirtualPyTest clone"
        return 1
    fi
    
    # Always (re-)run create_vpt_user.sh. It is idempotent and the single
    # source for the service account AND its setup (dir ownership, /tmp,
    # and the systemd-journal group the log viewer needs). Running it only
    # when vpt_user was missing is exactly why legacy VMs never received
    # later-added steps like the journal group — so run it unconditionally.
    local create_script="$source_dir/setup/local/linux/shared/create_vpt_user.sh"
    if [ ! -f "$create_script" ]; then
        echo "❌ create_vpt_user.sh not found at: $create_script"
        return 1
    fi
    if id "vpt_user" &>/dev/null; then
        echo "👤 Ensuring VirtualPyTest service user is up to date..."
    else
        echo "👤 Creating VirtualPyTest service user..."
    fi
    # Invoke via `bash` rather than executing directly so the script does not
    # need the +x bit set on disk. Source trees that arrived via `cp -r`,
    # rsync without --perms, scp, or git with `core.fileMode=false` may have
    # the execute bit stripped — without `bash`, sudo reports the file as
    # "command not found" even though it exists.
    if command -v sudo >/dev/null 2>&1; then
        if sudo -n true 2>/dev/null; then
            sudo bash "$create_script"
        else
            echo "❌ Need sudo access to set up the service user."
            echo "Please run: sudo bash $create_script"
            exit 1
        fi
    else
        echo "❌ sudo not available. Cannot set up service user."
        exit 1
    fi
}

# ============================================================================
# LEVEL 2: Directory Structure
# ============================================================================

# Create /opt/virtualpytest directory (empty)
# Sets ownership to vpt_user
# NO project copying yet
# Usage: ensure_opt_directory
ensure_opt_directory() {
    # Check if /opt/virtualpytest exists
    if [ ! -d "/opt/virtualpytest" ]; then
        echo "📋 Creating VirtualPyTest standard directory..."
        sudo mkdir -p /opt/virtualpytest
        sudo chown vpt_user:vpt_user /opt/virtualpytest
        sudo chmod 775 /opt/virtualpytest
        sudo find /opt/virtualpytest -type f -exec chmod 755 {} +
        sudo find /opt/virtualpytest -type d -exec chmod 755 {} +
        echo "✅ Created /opt/virtualpytest"
    else
        echo "✅ Directory /opt/virtualpytest already exists"
        # Ensure permissions are correct for multi-user access
        local current_perms=$(stat -c %a /opt/virtualpytest 2>/dev/null || echo "unknown")
        if [ "$current_perms" != "775" ]; then
            echo "🔧 Fixing directory permissions for multi-user access..."
            sudo chmod 775 /opt/virtualpytest
            sudo find /opt/virtualpytest -type f -exec chmod 755 {} +
            sudo find /opt/virtualpytest -type d -exec chmod 755 {} +
            echo "✅ Permissions updated to allow root and other users access"
        fi
    fi
}

# ============================================================================
# LEVEL 3: Project Setup (Highest Dependency)
# ============================================================================

# Copy project from source to /opt/virtualpytest
# Checks if update needed
# Creates version file
# Usage: ensure_project_copied "$SOURCE_ROOT"
ensure_project_copied() {
    local source_dir="$1"
    local target_dir="/opt/virtualpytest"
    
    if [ -z "$source_dir" ] || [ ! -f "$source_dir/README.md" ]; then
        echo "❌ Invalid source directory: $source_dir"
        return 1
    fi
    
    # Always sync project without wiping target directory
    local needs_copy=true
    echo "📋 Syncing VirtualPyTest to $target_dir..."
    
    # Copy if needed
    if [ "$needs_copy" = true ]; then
        echo "📋 Copying VirtualPyTest to $target_dir..."
        if command -v rsync >/dev/null 2>&1; then
            sudo rsync -a --delete \
              "${VPT_INSTALL_RSYNC_EXCLUDES[@]}" \
              "$source_dir/" "$target_dir/"
        else
            echo "⚠️ rsync not available; falling back to cp without full exclude support"
            sudo cp -r "$source_dir"/* "$target_dir/" 2>/dev/null || true
            sudo cp -r "$source_dir"/.* "$target_dir/" 2>/dev/null || true
        fi
        sudo find "$target_dir" \
          -path "$target_dir/venv" -prune -o \
          -path "$target_dir/frontend/node_modules" -prune -o \
          -path "$target_dir/frontend/public/docs" -prune -o \
          -path "$target_dir/frontend/public/brand" -prune -o \
          -not -path '*/.env' \
          -exec chown -h vpt_user:vpt_user {} + 2>/dev/null || true

        # Save version info
        save_version_info "$source_dir" "$target_dir"

        echo "✅ Project copied to $target_dir"
    fi
}

# Copy only specific files/directories from project
# Usage: copy_selective_files "$SOURCE_ROOT" "path/to/files/*"
copy_selective_files() {
    local source_dir="$1"
    local files_pattern="$2"
    local target_dir="/opt/virtualpytest"
    
    if [ -z "$source_dir" ] || [ -z "$files_pattern" ]; then
        echo "❌ Invalid parameters for selective copy"
        return 1
    fi
    
    echo "📋 Copying selective files: $files_pattern"
    sudo mkdir -p "$target_dir"
    sudo cp -r "$source_dir/$files_pattern" "$target_dir/" 2>/dev/null || true
    sudo chown -R vpt_user:vpt_user "$target_dir"
    echo "✅ Files copied to $target_dir"
}

# Save version information to track installations
# Usage: save_version_info "$SOURCE_ROOT" "$TARGET_DIR"
save_version_info() {
    local source_dir="$1"
    local target_dir="$2"
    
    # Save git information if available
    if [ -d "$source_dir/.git" ] && command -v git >/dev/null 2>&1; then
        cd "$source_dir"
        local commit_hash=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
        local branch=$(git branch --show-current 2>/dev/null || echo "unknown")
        local remote_url=$(git config --get remote.origin.url 2>/dev/null || echo "unknown")
        
        sudo tee "$target_dir/.version" > /dev/null << EOF
# VirtualPyTest Version Information
# Saved during installation/update

INSTALL_DATE=$(date)
GIT_COMMIT=$commit_hash
GIT_BRANCH=$branch
GIT_REMOTE=$remote_url
SOURCE_DIR=$source_dir
TARGET_DIR=$target_dir
EOF
        echo "✅ Version information saved"
    fi
}

# Check if we need to update the installation
# Returns 0 if update needed, 1 if not
# Usage: check_installation_update "$SOURCE_ROOT"
check_installation_update() {
    local source_dir="$1"
    local version_file="/opt/virtualpytest/.version"
    
    # If no version file exists, assume update needed
    if [ ! -f "$version_file" ]; then
        return 0
    fi
    
    # Check git information if available
    if [ -d "$source_dir/.git" ] && command -v git >/dev/null 2>&1; then
        cd "$source_dir"
        local current_commit=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
        local installed_commit=$(grep "^GIT_COMMIT=" "$version_file" | cut -d'=' -f2 || echo "unknown")
        
        if [ "$current_commit" != "$installed_commit" ]; then
            return 0
        fi
    fi
    
    # No updates detected
    return 1
}

# ============================================================================
# STANDARD SETUP FUNCTION (One Approach for All)
# ============================================================================

# Standard setup used by ALL installers
# Creates user, directory, copies entire project
# Usage: setup_for_code_installer "$SOURCE_ROOT"
#
# This provides:
# - Consistent behavior across all VMs
# - Simple mental model (always the same)
# - Complete project available for debugging/reference
# - No broken dependencies or missing files
setup_for_code_installer() {
    local source_root="$1"
    echo "🔧 Setting up standard VirtualPyTest environment..."
    echo "   • Creating service user"
    echo "   • Creating /opt/virtualpytest"
    echo "   • Copying project code"
    ensure_vpt_user "$source_root"
    ensure_opt_directory
    ensure_project_copied "$source_root"
    echo "✅ Standard setup complete"
}

# ============================================================================
# LEGACY FUNCTIONS (Deprecated - kept for compatibility)
# ============================================================================

# Legacy: service-only installer (DEPRECATED - use setup_for_code_installer instead)
setup_for_service_installer() {
    local source_root="$1"
    echo "⚠️  setup_for_service_installer is deprecated, using standard setup"
    setup_for_code_installer "$source_root"
}

# Legacy: hybrid installer (DEPRECATED - use setup_for_code_installer instead)
setup_for_hybrid_installer() {
    local source_root="$1"
    local files_to_copy="$2"
    echo "⚠️  setup_for_hybrid_installer is deprecated, using standard setup"
    setup_for_code_installer "$source_root"
}

# ============================================================================
# LEGACY COMPATIBILITY (Deprecated - for backward compatibility)
# ============================================================================

# Old function name - redirects to new modular approach
# Usage: ensure_virtualpytest_setup "$SOURCE_ROOT" ["false"]
ensure_virtualpytest_setup() {
    local source_dir="$1"
    local create_version_file="${2:-true}"
    
    echo "⚠️  Using legacy ensure_virtualpytest_setup() - consider using modular functions"
    
    # Perform full setup (equivalent to setup_for_code_installer)
    ensure_vpt_user "$source_dir"
    ensure_opt_directory
    
    if [ "$create_version_file" = "true" ]; then
        ensure_project_copied "$source_dir"
    fi
}

# Old function name - kept for compatibility
bootstrap_virtualpytest() {
    local current_dir="$1"
    local standard_dir="/opt/virtualpytest"
    
    echo "⚠️  Using legacy bootstrap_virtualpytest() - consider using modular functions"
    
    # If we're already in the standard location, nothing to do
    if [ "$current_dir" = "$standard_dir" ]; then
        echo "✅ Already in standard VirtualPyTest location"
        return 0
    fi
    
    echo "📁 Detected installation from: $current_dir"
    echo "🎯 Standard location is: $standard_dir"
    
    # Full setup
    setup_for_code_installer "$current_dir"
    
    echo "🔄 Please run the installation from the standard location:"
    echo "   cd $standard_dir"
    echo "   ./setup/local/linux/YOUR_INSTALL_SCRIPT.sh"
    exit 0
}
