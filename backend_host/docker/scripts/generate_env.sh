#!/bin/bash
# Generate .env file from environment variables for Docker deployments
# This allows the stream service to work without requiring a pre-existing .env file

ENV_FILE="/app/backend_host/src/.env"

echo "🔧 Generating .env file from environment variables..."

# Create .env file with all environment variables
# Filter out common Docker/system variables that aren't needed
env | grep -v '^PATH=' | \
      grep -v '^HOME=' | \
      grep -v '^HOSTNAME=' | \
      grep -v '^PWD=' | \
      grep -v '^SHLVL=' | \
      grep -v '^_=' | \
      grep -v '^LS_COLORS=' | \
      grep -v '^OLDPWD=' | \
      sort > "$ENV_FILE"

chmod 644 "$ENV_FILE"
chown vpt_user:vpt_user "$ENV_FILE"

# Count how many device configurations we have
HOST_VIDEO_COUNT=0
DEVICE_COUNT=0

if [ -n "$HOST_VIDEO_SOURCE" ]; then
    HOST_VIDEO_COUNT=1
fi

for i in {1..10}; do
    var_name="DEVICE${i}_VIDEO"
    if [ -n "${!var_name}" ]; then
        ((DEVICE_COUNT++))
    fi
done

echo "✅ .env file generated at $ENV_FILE"
echo "   Total environment variables: $(wc -l < "$ENV_FILE")"
echo "   Host video devices: $HOST_VIDEO_COUNT"
echo "   Physical devices: $DEVICE_COUNT"

# Only enable stream autostart if we have devices configured
if [ $((HOST_VIDEO_COUNT + DEVICE_COUNT)) -gt 0 ]; then
    echo "✅ Video devices detected - stream service will be available"
else
    echo "⚠️  No video devices configured - stream service will remain disabled"
fi

