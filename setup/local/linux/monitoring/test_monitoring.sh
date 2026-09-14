#!/bin/bash

# VirtualPyTest - Test Monitoring Setup
# Quick test script to verify Grafana and monitoring components

set -e

echo "🧪 Testing VirtualPyTest Monitoring Setup"
echo "========================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "📄 Loading configuration from: $PROJECT_ROOT/.env"
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
else
    echo "⚠️  No .env file found at: $PROJECT_ROOT/.env"
    echo "   Using built-in defaults."
fi

echo ""

# Test 1: Grafana Package
echo "1️⃣ Testing Grafana Installation:"
GRAFANA_BIN=""
if command -v grafana-server &> /dev/null; then
    GRAFANA_BIN="$(command -v grafana-server)"
elif [ -x "/usr/sbin/grafana-server" ]; then
    GRAFANA_BIN="/usr/sbin/grafana-server"
elif [ -x "/usr/bin/grafana-server" ]; then
    GRAFANA_BIN="/usr/bin/grafana-server"
elif [ -x "/usr/local/sbin/grafana-server" ]; then
    GRAFANA_BIN="/usr/local/sbin/grafana-server"
fi

if [ -n "$GRAFANA_BIN" ]; then
    echo "   ✅ Grafana package: INSTALLED ($($GRAFANA_BIN -v 2>/dev/null | head -1))"
else
    echo "   ❌ Grafana package: NOT FOUND"
    exit 1
fi

# Test PostgreSQL Client
echo ""
echo "1️⃣.5️⃣ Testing PostgreSQL Client:"
if command -v psql &> /dev/null; then
    echo "   ✅ PostgreSQL client: INSTALLED ($(psql --version | head -1))"
else
    echo "   ❌ PostgreSQL client: NOT FOUND"
    echo "   💡 Install with: sudo apt-get update && sudo apt-get install -y postgresql-client"
fi

# Test 2: Grafana Service
echo ""
echo "2️⃣ Testing Grafana Service:"
if systemctl is-active --quiet grafana-server; then
    echo "   ✅ Grafana service: RUNNING"
else
    echo "   ❌ Grafana service: NOT RUNNING"
    echo "   💡 Start with: sudo systemctl start grafana-server"
fi

# Test 3: Web Interface
echo ""
echo "3️⃣ Testing Web Interface:"
echo "   🔍 Testing: http://localhost:3000/api/health"
if curl -s -f --max-time 5 http://localhost:3000/api/health &> /dev/null; then
    echo "   ✅ Grafana web interface: ACCESSIBLE"

    # Test login via API using Basic Auth (avoids CSRF issues on /login)
    echo "   🔍 Testing: Admin login via API (/api/user)"
    if curl -s -f --max-time 5 -u "${GRAFANA_ADMIN_USER:-admin}:${GRAFANA_ADMIN_PASSWORD:-admin}" \
         http://localhost:3000/api/user | grep -q "\"login\":\"${GRAFANA_ADMIN_USER:-admin}\""; then
        echo "   ✅ Admin login: SUCCESSFUL"
    else
        echo "   ❌ Admin login: FAILED"
        echo "      💡 Try logging in manually with: ${GRAFANA_ADMIN_USER:-admin} / ${GRAFANA_ADMIN_PASSWORD:-admin}"
    fi
else
    echo "   ❌ Grafana web interface: NOT RESPONDING"
    echo "      💡 Check if service is running: sudo systemctl status grafana-server"
fi

# Test 4: Database Connections
echo ""
echo "4️⃣ Testing Database Connections:"

# Database Connection Test
if [ -n "$SUPABASE_DB_URI" ]; then
    # Parse SUPABASE_DB_URI for connection details
    DB_URI="$SUPABASE_DB_URI"
    DB_USER=$(echo "$DB_URI" | sed -n 's|.*://\([^:]*\):.*|\1|p')
    DB_PASS=$(echo "$DB_URI" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
    DB_HOST=$(echo "$DB_URI" | sed -n 's|.*@\([^:]*\):.*|\1|p')
    DB_PORT=$(echo "$DB_URI" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
    DB_NAME=$(echo "$DB_URI" | sed -n 's|.*/\([^?]*\).*|\1|p')

    echo "   🔍 Testing: postgresql://$DB_USER:***@$DB_HOST:$DB_PORT/$DB_NAME"
    if PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" &> /dev/null; then
        echo "   ✅ Supabase DB: CONNECTED"
    else
        echo "   ❌ Supabase DB: CONNECTION FAILED"
        echo "      💡 Check if database is running on $DB_HOST:$DB_PORT"
        echo "      💡 Verify SUPABASE_DB_URI in .env file"
    fi
else
    # Fallback to VirtualPyTest database variables
    echo "   🔍 Testing: postgresql://${VIRTUALPYTEST_DB_USER:-virtualpytest_user}:***@localhost:5432/virtualpytest"
    if PGPASSWORD="${VIRTUALPYTEST_DB_PASSWORD:-virtualpytest_pass}" psql -h localhost -p 5432 -U "${VIRTUALPYTEST_DB_USER:-virtualpytest_user}" -d virtualpytest -c "SELECT 1;" &> /dev/null; then
        echo "   ✅ VirtualPyTest DB: CONNECTED"
    else
        echo "   ❌ VirtualPyTest DB: CONNECTION FAILED"
        echo "      💡 Check if VirtualPyTest database is running on localhost:5432"
        echo "      💡 Verify credentials and database name"
    fi
fi

# Grafana Metrics Database
if command -v psql &> /dev/null && sudo -u postgres psql -c "SELECT 1;" &> /dev/null; then
    if PGPASSWORD="${GRAFANA_DB_PASSWORD:-grafana_pass}" psql -h localhost -U "${GRAFANA_DB_USER:-grafana_user}" -d grafana_metrics -c "SELECT 1;" &> /dev/null; then
        echo "   ✅ Grafana Metrics DB: CONNECTED"
    else
        echo "   ❌ Grafana Metrics DB: CONNECTION FAILED"
    fi
else
    echo "   ℹ️ Grafana Metrics DB: SKIPPED (PostgreSQL not available)"
fi

# Test 5: Configuration Files
echo ""
echo "5️⃣ Testing Configuration Files:"
if [ -f "/etc/grafana/grafana.ini" ]; then
    echo "   ✅ Grafana config: EXISTS (/etc/grafana/grafana.ini)"
else
    echo "   ❌ Grafana config: MISSING"
fi

if [ -d "/var/lib/grafana" ]; then
    echo "   ✅ Grafana data dir: EXISTS (/var/lib/grafana)"
else
    echo "   ❌ Grafana data dir: MISSING"
fi

# Test 6: Dashboards
echo ""
echo "6️⃣ Testing Dashboards:"
dashboard_count=$(find "$PROJECT_ROOT/infra/monitoring/grafana/dashboards" -name "*.json" 2>/dev/null | wc -l)
if [ "$dashboard_count" -gt 0 ]; then
    echo "   ✅ Dashboard files: $dashboard_count FOUND"
else
    echo "   ⚠️ Dashboard files: NONE FOUND"
fi

# Test 7: Environment Variables
echo ""
echo "7️⃣ Testing Environment Configuration:"
missing_vars=()
[ -z "$GRAFANA_ADMIN_USER" ] && missing_vars+=("GRAFANA_ADMIN_USER")
[ -z "$GRAFANA_ADMIN_PASSWORD" ] && missing_vars+=("GRAFANA_ADMIN_PASSWORD")
[ -z "$GRAFANA_SECRET_KEY" ] && missing_vars+=("GRAFANA_SECRET_KEY")

if [ ${#missing_vars[@]} -eq 0 ]; then
    echo "   ✅ Environment variables: ALL SET"
else
    echo "   ⚠️ Missing environment variables: ${missing_vars[*]}"
fi

echo ""
echo "🏁 Monitoring Test Complete!"
echo ""
echo "📊 Quick Access:"
echo "   Grafana: http://localhost:3000"
echo "   Login: ${GRAFANA_ADMIN_USER:-admin} / ${GRAFANA_ADMIN_PASSWORD:-admin}"
echo ""
echo "🔧 If issues found, check:"
echo "   Logs: sudo journalctl -u grafana-server -f"
echo "   Status: sudo systemctl status grafana-server"
echo "   Config: /etc/grafana/grafana.ini"
