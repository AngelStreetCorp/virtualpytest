#!/bin/bash
# Grafana Container Startup Script (Standalone Deployment)
# Generates dynamic datasource configuration at runtime
# Supports multiple database types: PostgreSQL, Supabase, etc.

set -e

echo "🔧 Setting up Grafana datasources..."

# Create datasources directory (not mounted, so writable)
mkdir -p /etc/grafana/provisioning/datasources

DATASOURCES_CONFIGURED=0

# Function to create PostgreSQL datasource
create_postgres_datasource() {
    local name="$1"
    local host="$2"
    local port="$3"
    local db="$4"
    local user="$5"
    local password="$6"
    local uid="$7"
    local is_default="${8:-false}"

    # Resolve hostname to IPv4 address to avoid IPv6 issues
    echo "   Resolving $host to IPv4..."
    local db_ip=$(getent ahostsv4 "$host" 2>/dev/null | head -1 | awk '{print $1}' || true)
    [ -z "$db_ip" ] && db_ip="$host"
    if [ "$db_ip" != "$host" ]; then
        echo "   Resolved to IPv4: $db_ip"
    fi

    local datasource_file="/etc/grafana/provisioning/datasources/${uid}.yaml"

    cat > "$datasource_file" << EOF
# Grafana Datasource Provisioning (Auto-generated)
# Generated at runtime from environment variables

apiVersion: 1

datasources:
  - name: ${name}
    type: postgres
    access: proxy
    url: ${db_ip}:${port}
    database: ${db}
    user: ${user}
    secureJsonData:
      password: ${password}
    jsonData:
      database: ${db}
      sslmode: '${GRAFANA_DS_SSLMODE:-require}'
      postgresVersion: 1500
      timescaledb: false
      maxOpenConns: 10
      maxIdleConns: 2
      connMaxLifetime: 14400
    isDefault: ${is_default}
    editable: true
    uid: ${uid}
EOF

    echo "✅ Created PostgreSQL datasource: $name ($datasource_file)"
    DATASOURCES_CONFIGURED=$((DATASOURCES_CONFIGURED + 1))
}

# 1. Check for SUPABASE_DB_URI (primary method for Supabase)
if [ -n "$SUPABASE_DB_URI" ]; then
    echo "🔍 Configuring Supabase datasource from SUPABASE_DB_URI..."

    # Parse the connection string
    # Format: postgresql://user:password@host:port/database
    if [[ $SUPABASE_DB_URI =~ ^postgres(ql)?://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+)$ ]]; then
        DB_USER="${BASH_REMATCH[2]}"
        DB_PASSWORD="${BASH_REMATCH[3]}"
        DB_HOST="${BASH_REMATCH[4]}"
        DB_PORT="${BASH_REMATCH[5]}"
        DB_NAME="${BASH_REMATCH[6]}"

        echo "✅ Parsed Supabase connection:"
        echo "   Host: $DB_HOST:$DB_PORT"
        echo "   Database: $DB_NAME"
        echo "   User: $DB_USER"
        echo "   Password: [HIDDEN]"

        create_postgres_datasource "Supabase PostgreSQL" "$DB_HOST" "$DB_PORT" "$DB_NAME" "$DB_USER" "$DB_PASSWORD" "supabase-postgres" "true"
    else
        echo "⚠️  Failed to parse SUPABASE_DB_URI"
        echo "   Expected format: postgresql://user:password@host:port/database"
        echo "   Got: $SUPABASE_DB_URI"
    fi
fi

# 2. Check for DATABASE_URL (alternative method)
if [ -n "$DATABASE_URL" ] && [ -z "$SUPABASE_DB_URI" ]; then
    echo "🔍 Configuring datasource from DATABASE_URL..."

    if [[ $DATABASE_URL =~ ^postgres(ql)?://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+)$ ]]; then
        DB_USER="${BASH_REMATCH[2]}"
        DB_PASSWORD="${BASH_REMATCH[3]}"
        DB_HOST="${BASH_REMATCH[4]}"
        DB_PORT="${BASH_REMATCH[5]}"
        DB_NAME="${BASH_REMATCH[6]}"

        echo "✅ Parsed DATABASE_URL connection:"
        echo "   Host: $DB_HOST:$DB_PORT"
        echo "   Database: $DB_NAME"
        echo "   User: $DB_USER"
        echo "   Password: [HIDDEN]"

        create_postgres_datasource "PostgreSQL Database" "$DB_HOST" "$DB_PORT" "$DB_NAME" "$DB_USER" "$DB_PASSWORD" "postgres-db" "true"
    else
        echo "⚠️  Failed to parse DATABASE_URL"
        echo "   Expected format: postgresql://user:password@host:port/database"
        echo "   Got: $DATABASE_URL"
    fi
fi

# 3. Check for individual PostgreSQL environment variables (fallback)
if [ -n "$POSTGRES_HOST" ] && [ -n "$POSTGRES_DB" ] && [ -n "$POSTGRES_USER" ] && [ -n "$POSTGRES_PASSWORD" ]; then
    if [ "$DATASOURCES_CONFIGURED" -eq 0 ]; then
        echo "🔍 Configuring datasource from individual POSTGRES_* variables..."

        POSTGRES_PORT="${POSTGRES_PORT:-5432}"

        echo "✅ Using PostgreSQL environment variables:"
        echo "   Host: $POSTGRES_HOST:$POSTGRES_PORT"
        echo "   Database: $POSTGRES_DB"
        echo "   User: $POSTGRES_USER"
        echo "   Password: [HIDDEN]"

        create_postgres_datasource "PostgreSQL Database" "$POSTGRES_HOST" "$POSTGRES_PORT" "$POSTGRES_DB" "$POSTGRES_USER" "$POSTGRES_PASSWORD" "postgres-db" "true"
    fi
fi

# 4. Create a sample/test datasource if no real datasources configured
if [ "$DATASOURCES_CONFIGURED" -eq 0 ]; then
    echo "⚠️  No database connection configured"
    echo "ℹ️  Grafana will start with default SQLite database"
    echo "ℹ️  You can add datasources manually in the Grafana web interface"
    echo ""
    echo "💡 To connect to a database, set one of these environment variables:"
    echo "   SUPABASE_DB_URI=postgresql://user:password@host:port/database"
    echo "   DATABASE_URL=postgresql://user:password@host:port/database"
    echo "   Or set POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD"
fi

# Dashboard file provisioning is disabled by default so UI edits are persistent.
mkdir -p /etc/grafana/provisioning/dashboards
if [ "${GRAFANA_ENABLE_DASHBOARD_PROVISIONING:-false}" = "true" ] && [ -d "/var/lib/grafana/dashboards" ] && [ "$(ls -A /var/lib/grafana/dashboards 2>/dev/null)" ]; then
    echo "🔍 Dashboard provisioning explicitly enabled, creating file provider..."

    cat > /etc/grafana/provisioning/dashboards/default.yaml << EOF
# Grafana Dashboard Provisioning (Auto-generated)

apiVersion: 1

providers:
  - name: 'default'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards
EOF

    echo "✅ Created dashboard provisioning config"
else
    cat > /etc/grafana/provisioning/dashboards/default.yaml << EOF
apiVersion: 1
providers: []
EOF
    echo "ℹ️  Dashboard file provisioning disabled"
fi

echo ""
if [ "$DATASOURCES_CONFIGURED" -gt 0 ]; then
    echo "🎉 Grafana configured with $DATASOURCES_CONFIGURED datasource(s)"
else
    echo "🎉 Grafana starting with default configuration"
fi

echo "🚀 Starting Grafana..."
exec /run.sh
