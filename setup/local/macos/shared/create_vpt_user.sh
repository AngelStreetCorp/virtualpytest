#!/bin/bash

# VirtualPyTest - Create Service Account (vpt_user) for macOS
# This script creates the dedicated service account for running VirtualPyTest services
# Must be run with sudo privileges

set -e

echo "👤 Creating VirtualPyTest service account (vpt_user) for macOS..."

# Check if running as root or with sudo
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run with sudo privileges"
   echo "Usage: sudo ./create_vpt_user.sh"
   exit 1
fi

# Check if vpt_user already exists
if dscl . -read /Users/vpt_user &>/dev/null; then
    echo "⚠️ vpt_user already exists"
    echo "✅ Service account is ready"
    # Show existing user info
    echo "   • UniqueID: $(dscl . -read /Users/vpt_user UniqueID | awk '{print $2}')"
    echo "   • Home: $(dscl . -read /Users/vpt_user NFSHomeDirectory | awk '{print $2}')"
    exit 0
fi

# Find an available UID in the system range (below 500)
# macOS reserves UIDs below 500 for system accounts
find_available_uid() {
    for uid in $(seq 400 499); do
        if ! dscl . -list /Users UniqueID | grep -q " $uid$"; then
            echo $uid
            return
        fi
    done
    echo "499"  # Fallback
}

AVAILABLE_UID=$(find_available_uid)
echo "🔧 Creating vpt_user system account with UID $AVAILABLE_UID..."

# Create the user using Directory Services
dscl . -create /Users/vpt_user
dscl . -create /Users/vpt_user UserShell /usr/bin/false
dscl . -create /Users/vpt_user RealName "VirtualPyTest Service Account"
dscl . -create /Users/vpt_user UniqueID "$AVAILABLE_UID"
dscl . -create /Users/vpt_user PrimaryGroupID 20  # staff group
dscl . -create /Users/vpt_user NFSHomeDirectory /var/lib/vpt_user

# Create home directory
mkdir -p /var/lib/vpt_user
chown vpt_user:staff /var/lib/vpt_user
chmod 755 /var/lib/vpt_user

# Hide user from login window (system accounts shouldn't appear)
dscl . -create /Users/vpt_user IsHidden 1

# Verify creation
echo "✅ vpt_user created successfully"
echo "   • UniqueID: $(dscl . -read /Users/vpt_user UniqueID | awk '{print $2}')"
echo "   • PrimaryGroupID: $(dscl . -read /Users/vpt_user PrimaryGroupID | awk '{print $2}')"
echo "   • Home: $(dscl . -read /Users/vpt_user NFSHomeDirectory | awk '{print $2}')"
echo "   • Shell: $(dscl . -read /Users/vpt_user UserShell | awk '{print $2}')"
echo "   • Hidden: Yes (won't appear in login window)"
echo ""
echo "📝 Note: This is a headless service account with no login access."
echo "   Services running as vpt_user cannot access GUI resources (screen, camera)."
echo "   Use the logged-in user for services requiring screen/camera access."
