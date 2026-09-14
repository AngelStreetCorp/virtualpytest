#!/bin/bash

# VirtualPyTest - Verify Supabase Database Installation
# Shows detailed information about what's installed in the Supabase database
#
# Usage: ./test_database.sh [SUPABASE_DATA_DIR]
#   SUPABASE_DATA_DIR: Optional path to Supabase data directory (default: /data/supabase)

set -e

echo "🔍 VirtualPyTest Supabase Database Verification"
echo "========================================"
echo ""

# Parse arguments
SUPABASE_DATA_DIR="${1:-/data/supabase}"
PROJECT_ROOT="/opt/virtualpytest"

echo "📁 Configuration:"
echo "   • Supabase data directory: $SUPABASE_DATA_DIR"
echo "   • Project root: $PROJECT_ROOT"
echo ""

# Supabase database connection details (standard Supabase defaults)
SUPABASE_DB_HOST="localhost"
SUPABASE_DB_PORT="54322"
SUPABASE_DB_NAME="postgres"
SUPABASE_DB_USER="postgres"
SUPABASE_DB_PASS="postgres"

# Function to run SQL query
run_query() {
    PGPASSWORD=$SUPABASE_DB_PASS psql -h $SUPABASE_DB_HOST -p $SUPABASE_DB_PORT -U $SUPABASE_DB_USER -d $SUPABASE_DB_NAME -t -A -c "$1"
}

# Check Docker installation and status
echo "🐳 Checking Docker (required for Supabase)..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed"
    exit 1
fi
echo "✅ Docker is installed"

if ! docker info &> /dev/null; then
    echo "❌ Docker is not running or not accessible"
    exit 1
fi
echo "✅ Docker is running"
echo ""

# Check if Supabase CLI is installed
echo "🔧 Checking Supabase CLI..."
if command -v supabase &> /dev/null; then
    echo "✅ Supabase CLI installed ($(supabase --version))"
else
    echo "❌ Supabase CLI not found"
    exit 1
fi
echo ""

# Check if Supabase containers are running
echo "📦 Checking Supabase containers..."
if docker ps --format '{{.Names}}' | grep -q "supabase"; then
    echo "✅ Supabase containers are running:"
    docker ps --filter "name=supabase" --format "   • {{.Names}} ({{.Status}})"
else
    echo "❌ No Supabase containers are running"
    echo "   Run: cd $SUPABASE_DATA_DIR && supabase start"
    exit 1
fi
echo ""

# Check if systemd service exists and is active
echo "⚙️ Checking Supabase systemd service..."
if systemctl list-unit-files | grep -q "supabase.service"; then
    echo "✅ Supabase systemd service exists"
    if systemctl is-active --quiet supabase; then
        echo "✅ Supabase service is active"
    else
        echo "⚠️  Supabase service is not active (containers may be running manually)"
    fi
else
    echo "⚠️  Supabase systemd service not installed (containers running manually)"
fi
echo ""

# Check Supabase project directory structure
echo "📂 Checking Supabase project structure..."
if [ -d "$SUPABASE_DATA_DIR/supabase" ]; then
    echo "✅ Supabase project directory exists at $SUPABASE_DATA_DIR/supabase"
    
    if [ -f "$SUPABASE_DATA_DIR/supabase/config.toml" ]; then
        echo "✅ Supabase configuration file exists"
    else
        echo "❌ Supabase config.toml not found"
    fi
    
    if [ -f "$SUPABASE_DATA_DIR/supabase/.env.local" ]; then
        echo "✅ Supabase environment file exists"
    else
        echo "⚠️  Supabase .env.local not found"
    fi
else
    echo "❌ Supabase project directory not found at $SUPABASE_DATA_DIR/supabase"
    exit 1
fi
echo ""

# Check Supabase status
echo "🔍 Checking Supabase status..."
if (cd "$SUPABASE_DATA_DIR" && supabase status) &> /dev/null; then
    echo "✅ Supabase is running and responding"
    echo ""
    echo "Supabase Services:"
    (cd "$SUPABASE_DATA_DIR" && supabase status) | grep -E "(API URL|GraphQL URL|DB URL|Studio URL|Inbucket URL)" || true
else
    echo "⚠️  Unable to get Supabase status"
    echo "   This may indicate Supabase is not fully initialized"
fi
echo ""

# Check if database exists and is accessible
echo "📊 Checking database connectivity..."
if ! PGPASSWORD=$SUPABASE_DB_PASS psql -h $SUPABASE_DB_HOST -p $SUPABASE_DB_PORT -U $SUPABASE_DB_USER -d $SUPABASE_DB_NAME -c "SELECT version();" &> /dev/null; then
    echo "❌ Cannot connect to Supabase PostgreSQL database"
    echo "   Connection: postgresql://$SUPABASE_DB_USER:***@$SUPABASE_DB_HOST:$SUPABASE_DB_PORT/$SUPABASE_DB_NAME"
    exit 1
fi
echo "✅ Database is accessible"
PG_VERSION=$(PGPASSWORD=$SUPABASE_DB_PASS psql -h $SUPABASE_DB_HOST -p $SUPABASE_DB_PORT -U $SUPABASE_DB_USER -d $SUPABASE_DB_NAME -t -A -c "SELECT version();")
echo "   PostgreSQL version: $(echo $PG_VERSION | cut -d' ' -f2)"
echo ""

# Get list of all tables
echo "📋 Tables installed in database:"
echo "--------------------------------"
table_count=$(run_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';")
echo "Total tables: $table_count"
echo ""

# List all tables with row counts
echo "Table Name                                    | Row Count"
echo "----------------------------------------------|----------"
while IFS='|' read -r table_name; do
    if [ ! -z "$table_name" ]; then
        row_count=$(run_query "SELECT COUNT(*) FROM \"$table_name\";")
        printf "%-45s | %s\n" "$table_name" "$row_count"
    fi
done < <(run_query "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")

echo ""

# Check for migration tracking (if exists)
echo "🔄 Checking migration status..."
if run_query "SELECT to_regclass('public.schema_migrations');" | grep -q "schema_migrations"; then
    echo "Migration tracking table found:"
    run_query "SELECT * FROM schema_migrations ORDER BY version;"
else
    echo "⚠️  No migration tracking table found (migrations may have run but not tracked)"
fi

echo ""

# Show core tables status
echo "🎯 Core VirtualPyTest Tables Status:"
echo "------------------------------------"

CORE_TABLES=(
    "device"
    "device_flags"
    "deployments"
    "testcase_definitions"
    "campaigns"
    "agent_registry"
    "team_members"
)

for table in "${CORE_TABLES[@]}"; do
    if run_query "SELECT to_regclass('public.$table');" | grep -q "$table"; then
        row_count=$(run_query "SELECT COUNT(*) FROM \"$table\";")
        echo "✅ $table ($row_count rows)"
    else
        echo "❌ $table (NOT FOUND)"
    fi
done

echo ""

# Check which migration files should have been applied
echo "📂 Expected Migrations vs Database State:"
echo "-----------------------------------------"

MIGRATION_DIR="$PROJECT_ROOT/setup/db/schema"

if [ -d "$MIGRATION_DIR" ]; then
    migration_files=$(find "$MIGRATION_DIR" -name "[0-9]*_*.sql" -type f | sort -V | wc -l)
    echo "Migration files available: $migration_files"
    echo ""
    echo "List of migration files:"
    find "$MIGRATION_DIR" -name "[0-9]*_*.sql" -type f | sort -V | while read -r file; do
        echo "  - $(basename "$file")"
    done
else
    echo "⚠️  Migration directory not found: $MIGRATION_DIR"
fi

echo ""

# Check VirtualPyTest configuration
echo "🔗 Checking VirtualPyTest Configuration:"
echo "----------------------------------------"

# Check configuration file for Supabase settings
if [ -f "$PROJECT_ROOT/config/database/local.env" ]; then
    echo "✅ Configuration file exists: $PROJECT_ROOT/config/database/local.env"
    if grep -q "SUPABASE_URL" "$PROJECT_ROOT/config/database/local.env"; then
        echo "✅ Supabase URLs configured in local.env"
        
        # Show extracted configuration values
        SUPABASE_URL=$(grep "^SUPABASE_URL=" "$PROJECT_ROOT/config/database/local.env" | cut -d'=' -f2 | sed 's/\${[^}]*:-\([^}]*\)}/\1/')
        echo "   • Supabase URL: $SUPABASE_URL"
    else
        echo "❌ Supabase URLs not found in local.env"
    fi
else
    echo "❌ Configuration file not found: $PROJECT_ROOT/config/database/local.env"
fi

# Check PostgreSQL auth schema (required for Supabase compatibility)
echo ""
echo "🔐 Checking Supabase-Compatible Schema:"
echo "---------------------------------------"

AUTH_CHECKS=(
    "auth.users table"
    "auth.uid() function"
    "auth.jwt() function"
    "authenticated role"
    "service_role role"
)

for check in "${AUTH_CHECKS[@]}"; do
    case $check in
        "auth.users table")
            if run_query "SELECT to_regclass('auth.users');" | grep -q "users"; then
                echo "✅ auth.users table exists"
            else
                echo "❌ auth.users table missing"
            fi
            ;;
        "auth.uid() function")
            if run_query "SELECT proname FROM pg_proc WHERE proname = 'uid' AND pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'auth');" | grep -q "uid"; then
                echo "✅ auth.uid() function exists"
            else
                echo "❌ auth.uid() function missing"
            fi
            ;;
        "auth.jwt() function")
            if run_query "SELECT proname FROM pg_proc WHERE proname = 'jwt' AND pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'auth');" | grep -q "jwt"; then
                echo "✅ auth.jwt() function exists"
            else
                echo "❌ auth.jwt() function missing"
            fi
            ;;
        "authenticated role")
            if run_query "SELECT rolname FROM pg_roles WHERE rolname = 'authenticated';" | grep -q "authenticated"; then
                echo "✅ authenticated role exists"
            else
                echo "❌ authenticated role missing"
            fi
            ;;
        "service_role role")
            if run_query "SELECT rolname FROM pg_roles WHERE rolname = 'service_role';" | grep -q "service_role"; then
                echo "✅ service_role role exists"
            else
                echo "❌ service_role role missing"
            fi
            ;;
    esac
done

echo ""
echo "========================================"
echo "✅ Supabase Database Verification Complete"
echo "========================================"
echo ""
echo "📋 Summary:"
echo "   • Docker: Running"
echo "   • Supabase CLI: Installed"
echo "   • Supabase Containers: Running"
echo "   • PostgreSQL: Connected ($(run_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';") tables in public schema)"
echo "   • Configuration: Located at $PROJECT_ROOT/config/database/local.env"
echo "   • Data Directory: $SUPABASE_DATA_DIR"
echo ""
echo "🌐 Access URLs:"
echo "   • Supabase Studio: http://localhost:54323"
echo "   • Supabase API: http://localhost:54321"
echo "   • PostgreSQL: postgresql://$SUPABASE_DB_USER:***@$SUPABASE_DB_HOST:$SUPABASE_DB_PORT/$SUPABASE_DB_NAME"
echo ""
echo "🔧 Management Commands:"
echo "   • Check status: cd $SUPABASE_DATA_DIR && supabase status"
echo "   • View logs: cd $SUPABASE_DATA_DIR && supabase logs"
echo "   • Stop Supabase: cd $SUPABASE_DATA_DIR && supabase stop"
echo "   • Start Supabase: cd $SUPABASE_DATA_DIR && supabase start"
echo ""
echo "✅ Status: All systems operational"
