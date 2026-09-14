#!/bin/bash
# Grafana Container Startup Script (Hetzner Deployment)
# Generates dynamic datasource configuration at runtime

set -e

echo "🔧 Setting up Grafana datasource from SUPABASE_DB_URI..."

# Create datasources directory (not mounted, so writable)
mkdir -p /etc/grafana/provisioning/datasources

# Check if SUPABASE_DB_URI is set
if [ -z "$SUPABASE_DB_URI" ]; then
    echo "⚠️ SUPABASE_DB_URI environment variable is not set"
    echo "⚠️ Grafana will start without Supabase datasource"
    echo "⚠️ You can add it manually in Grafana UI"
else
    # Parse the connection string
    # Format: postgresql://user:password@host:port/database
    if [[ $SUPABASE_DB_URI =~ ^postgres(ql)?://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+)$ ]]; then
        DB_USER="${BASH_REMATCH[2]}"
        DB_PASSWORD="${BASH_REMATCH[3]}"
        DB_HOST="${BASH_REMATCH[4]}"
        DB_PORT="${BASH_REMATCH[5]}"
        DB_NAME="${BASH_REMATCH[6]}"
        
        echo "✅ Parsed Supabase connection:"
        echo "   Host: $DB_HOST"
        echo "   Port: $DB_PORT"
        echo "   Database: $DB_NAME"
        echo "   User: $DB_USER"
        echo "   Password: [HIDDEN]"
        
        # Resolve hostname to IPv4 address to avoid IPv6 issues
        echo "   Resolving hostname to IPv4..."
        DB_IP=$(getent ahostsv4 "$DB_HOST" | head -1 | awk '{print $1}')
        if [ -z "$DB_IP" ]; then
            echo "⚠️  Failed to resolve $DB_HOST to IPv4, using hostname directly"
            DB_IP="$DB_HOST"
        else
            echo "   Resolved to IPv4: $DB_IP"
        fi
        
        # Create datasource configuration
        DATASOURCE_FILE="/etc/grafana/provisioning/datasources/supabase.yaml"
        
        cat > "$DATASOURCE_FILE" << EOF
# Grafana Datasource Provisioning (Auto-generated)
# Generated from SUPABASE_DB_URI environment variable

apiVersion: 1

datasources:
  - name: Supabase PostgreSQL
    type: postgres
    access: proxy
    url: ${DB_IP}:${DB_PORT}
    database: ${DB_NAME}
    user: ${DB_USER}
    secureJsonData:
      password: ${DB_PASSWORD}
    jsonData:
      database: ${DB_NAME}
      sslmode: 'require'
      postgresVersion: 1500
      timescaledb: false
      maxOpenConns: 10
      maxIdleConns: 2
      connMaxLifetime: 14400
    isDefault: true
    editable: false
    uid: supabase-postgres
EOF
        
        echo "✅ Grafana datasource configuration created at $DATASOURCE_FILE"
    else
        echo "⚠️ Failed to parse SUPABASE_DB_URI"
        echo "   Expected format: postgresql://user:password@host:port/database"
        echo "   Got: $SUPABASE_DB_URI"
        echo "⚠️ Grafana will start without Supabase datasource"
    fi
fi

# Start Grafana
echo ""
echo "🚀 Starting Grafana..."
exec /run.sh
