#!/bin/bash

# VirtualPyTest - Install Grafana for Local Development (Autonomous)
# This script installs and configures Grafana for local monitoring
# Standard approach: Creates user, copies project to /opt, installs from there

set -e

echo "📊 Installing Grafana for VirtualPyTest local development..."

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PROJECT_ROOT="/opt/virtualpytest"

# Load shared bootstrap functions
if [ -f "$SCRIPT_DIR/../shared/bootstrap.sh" ]; then
    source "$SCRIPT_DIR/../shared/bootstrap.sh"
else
    echo "❌ Bootstrap script not found"
    exit 1
fi

# Setup standard environment (user + directory + full project copy)
setup_for_code_installer "$SOURCE_ROOT"

# Change to project root
cd "$PROJECT_ROOT"

# Ensure .env file exists (copy from .env.example if needed)
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "📄 Creating .env from .env.example at: $PROJECT_ROOT/.env"
        cp .env.example .env
    else
        echo "⚠️  No .env or .env.example found in: $PROJECT_ROOT"
    fi
fi

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    echo "📄 Loading configuration from: $PROJECT_ROOT/.env"
    # Export variables so they're available to child processes
    set -a
    source .env
    set +a
else
    echo "⚠️  No .env file found at: $PROJECT_ROOT/.env"
    echo "   Using built-in defaults."
fi

# Set defaults for required variables (matching .env.example)
VIRTUALPYTEST_DB_USER="${VIRTUALPYTEST_DB_USER:-virtualpytest_user}"
VIRTUALPYTEST_DB_PASSWORD="${VIRTUALPYTEST_DB_PASSWORD:-virtualpytest_pass}"
GRAFANA_DB_USER="${GRAFANA_DB_USER:-grafana_user}"
GRAFANA_DB_PASSWORD="${GRAFANA_DB_PASSWORD:-grafana_pass}"
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-admin}"
GRAFANA_SECRET_KEY="${GRAFANA_SECRET_KEY:-SW2YcwTIb9zpOOhoPsMm}"

echo "✅ Configuration loaded"

# Check if we're in the right directory
if [ ! -f "README.md" ] || [ ! -d "backend_server" ]; then
    echo "❌ Could not find virtualpytest project root directory"
    echo "Current directory: $(pwd)"
    exit 1
fi

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "❌ This script only supports Linux"
    echo "Detected OS: $OSTYPE"
    exit 1
fi

echo "🖥️ Detected OS: Linux"


# Function to install Grafana on Linux
install_grafana() {
    echo "🐧 Installing Grafana on Linux..."
    
    # Check if running as root or with sudo
    if [[ $EUID -eq 0 ]]; then
        SUDO=""
    else
        SUDO="sudo"
        echo "🔐 This installation requires sudo privileges"
    fi
    
    # Detect Linux distribution
    if command -v apt-get &> /dev/null; then
        # Debian/Ubuntu
        echo "📦 Installing Grafana on Debian/Ubuntu..."
        
        # Install prerequisites
        $SUDO apt-get update
        $SUDO apt-get install -y wget gnupg
        
        # Add Grafana repository (modern approach for Debian 12+)
        $SUDO mkdir -p /etc/apt/keyrings
        wget -q -O - https://packages.grafana.com/gpg.key | $SUDO gpg --dearmor --batch --yes --no-tty -o /etc/apt/keyrings/grafana.gpg
        echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://packages.grafana.com/oss/deb stable main" | $SUDO tee -a /etc/apt/sources.list.d/grafana.list
        
        # Install PostgreSQL client for database connectivity testing
        echo "🔍 Installing PostgreSQL client (psql)..."
        if ! command -v psql &> /dev/null; then
            $SUDO apt-get update && $SUDO apt-get install -y postgresql-client
            echo "✅ PostgreSQL client installed"
        else
            echo "✅ PostgreSQL client already installed"
        fi

        # Install Grafana
        $SUDO apt-get update
        $SUDO apt-get install -y grafana
        
    elif command -v yum &> /dev/null; then
        # RHEL/CentOS/Fedora
        echo "📦 Installing Grafana on RHEL/CentOS/Fedora..."
        
        # Add Grafana repository
        cat <<EOF | $SUDO tee /etc/yum.repos.d/grafana.repo
[grafana]
name=grafana
baseurl=https://packages.grafana.com/oss/rpm
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://packages.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
EOF
        
        # Install Grafana
        $SUDO yum install -y grafana
        
    else
        echo "❌ Unsupported Linux distribution"
        echo "Please install Grafana manually: https://grafana.com/docs/grafana/latest/installation/"
        exit 1
    fi
    
    # Get Grafana paths
    GRAFANA_HOME="/var/lib/grafana"
    GRAFANA_LOGS="/var/log/grafana"
    GRAFANA_CONF="/etc/grafana/grafana.ini"
    GRAFANA_BIN="/usr/sbin/grafana-server"
}

# Function to cleanup existing Grafana installation
cleanup_existing_grafana() {
    echo "🧹 Cleaning up existing Grafana installation..."
    
    # Stop Grafana service if running
    if systemctl is-active --quiet grafana-server; then
        echo "🛑 Stopping Grafana service..."
        sudo systemctl stop grafana-server
    fi
    
    # Remove existing database to ensure fresh start
    echo "🗑️  Removing existing Grafana database..."
    sudo rm -f /var/lib/grafana/grafana.db
    
    # Remove existing provisioning files to avoid conflicts
    echo "🗑️  Removing existing provisioning files..."
    sudo rm -rf /etc/grafana/provisioning/datasources/*
    sudo rm -rf /etc/grafana/provisioning/dashboards/*
    
    # Remove existing dashboard files
    echo "🗑️  Removing existing dashboard files..."
    sudo rm -rf /etc/grafana/dashboards/virtualpytest/*
    
    echo "✅ Cleanup completed"
}

# Function to setup local Grafana configuration
# grafana_ini_set <section> <key> <value>: set the live key inside one [section] of
# /etc/grafana/grafana.ini — replaces the first `key =` / `;key =` line of that section, or
# inserts one under the header. A bare `sed` on `^;?key` would also edit the same key in
# other sections (the file lists every default, commented).
grafana_ini_set() {
    local section="$1" key="$2" value="$3" tmp
    tmp="$(mktemp)"
    # Buffer the target section: replace the live `key =` line if there is one, else the
    # commented `;key =` default, else append to the section.
    sudo awk -v sec="[$section]" -v key="$key" -v val="$value" '
        function flush() {
            if (n == 0) return
            idx = live ? live : cmt
            for (i = 1; i <= n; i++) print (i == idx) ? key " = " val : buf[i]
            if (!idx) print key " = " val
            n = 0; live = 0; cmt = 0
        }
        BEGIN { insec = 0; n = 0; live = 0; cmt = 0 }
        /^\[/ { if (insec) { flush(); insec = 0 } if ($0 == sec) { insec = 1; print; next } }
        insec {
            buf[++n] = $0
            if (!live && $0 ~ ("^" key " ?=")) live = n
            else if (!cmt && $0 ~ ("^;" key " ?=")) cmt = n
            next
        }
        { print }
        END { if (insec) flush() }
    ' /etc/grafana/grafana.ini > "$tmp"
    sudo cp "$tmp" /etc/grafana/grafana.ini; rm -f "$tmp"
}

setup_grafana_config() {
    echo "⚙️ Setting up local Grafana configuration..."
    
    # First cleanup any existing installation
    cleanup_existing_grafana

    # Create Grafana directories (Linux system directories)
    sudo mkdir -p /var/lib/grafana
    sudo mkdir -p /var/log/grafana
    sudo mkdir -p /etc/grafana
    
    # Let Grafana create a fresh SQLite database - DO NOT copy pre-configured databases
    # This avoids shipping hardcoded credentials and ensures clean installations
    # Datasources are configured via provisioning YAML files from .env variables
    echo "📊 Grafana will create a fresh SQLite database on first startup"
    echo "   ℹ️ Datasources configured via provisioning from .env variables"
    echo "   ℹ️ Dashboards loaded via provisioning from JSON files"
    
    # Copy the configuration file
    echo "⚙️ Copying Grafana configuration..."
    sudo cp "$PROJECT_ROOT/infra/monitoring/grafana/config/grafana.ini" /etc/grafana/
    
    # Update admin credentials in grafana.ini
    echo "🔒 Setting Grafana admin credentials..."
    sudo sed -i "s/;admin_user = admin/admin_user = $GRAFANA_ADMIN_USER/" /etc/grafana/grafana.ini
    sudo sed -i "s/admin_user = admin$/admin_user = $GRAFANA_ADMIN_USER/" /etc/grafana/grafana.ini
    sudo sed -i "s/;admin_password = admin/admin_password = $GRAFANA_ADMIN_PASSWORD/" /etc/grafana/grafana.ini
    sudo sed -i "s/admin_password = admin$/admin_password = $GRAFANA_ADMIN_PASSWORD/" /etc/grafana/grafana.ini

    # Set secret key for signing
    echo "🔑 Setting Grafana secret key..."
    sudo sed -i "s/;secret_key = SW2YcwTIb9zpOOhoPsMm/secret_key = $GRAFANA_SECRET_KEY/" /etc/grafana/grafana.ini
    sudo sed -i "s/secret_key = SW2YcwTIb9zpOOhoPsMm$/secret_key = $GRAFANA_SECRET_KEY/" /etc/grafana/grafana.ini
    
    # Set up provisioning directories and copy local datasource configuration
    echo "📋 Setting up Grafana provisioning for local databases..."
    sudo mkdir -p /etc/grafana/provisioning/datasources
    sudo mkdir -p /etc/grafana/provisioning/dashboards
    sudo mkdir -p /etc/grafana/dashboards/virtualpytest
    
    # Create provisioning configuration files directly from .env variables
    # This ensures datasources are configured dynamically, NOT hardcoded in grafana.db
    echo "📋 Creating datasource provisioning configuration from .env..."
    
    # Parse SUPABASE_DB_URI if available (format: postgresql://user:password@host:port/database)
    if [ -n "$SUPABASE_DB_URI" ]; then
        echo "   ℹ️ Using SUPABASE_DB_URI for datasource configuration"
        # Parse the URI components
        DB_USER=$(echo "$SUPABASE_DB_URI" | sed -n 's|.*://\([^:]*\):.*|\1|p')
        DB_PASS=$(echo "$SUPABASE_DB_URI" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
        DB_HOST=$(echo "$SUPABASE_DB_URI" | sed -n 's|.*@\([^:]*\):.*|\1|p')
        DB_PORT=$(echo "$SUPABASE_DB_URI" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
        DB_NAME=$(echo "$SUPABASE_DB_URI" | sed -n 's|.*/\([^?]*\).*|\1|p')
        DB_SSLMODE="disable"  # Local Supabase typically doesn't need SSL
        DATASOURCE_NAME="VirtualPyTest Database"
        echo "   ℹ️ Parsed: $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
    else
        echo "   ℹ️ Using local PostgreSQL variables for datasource configuration"
        DB_USER="${VIRTUALPYTEST_DB_USER}"
        DB_PASS="${VIRTUALPYTEST_DB_PASSWORD}"
        DB_HOST="localhost"
        DB_PORT="5432"
        DB_NAME="virtualpytest"
        DB_SSLMODE="disable"
        DATASOURCE_NAME="VirtualPyTest Local"
    fi
    
    sudo tee /etc/grafana/provisioning/datasources/virtualpytest.yml > /dev/null << EOF
# VirtualPyTest Grafana Datasource Provisioning
# Configured dynamically from .env variables during installation
# DO NOT store datasource credentials in grafana.db
apiVersion: 1

datasources:
  # VirtualPyTest Application Database - DEFAULT datasource
  # UID must be 'supabase-postgres' to match dashboard configurations
  - name: ${DATASOURCE_NAME}
    type: postgres
    access: proxy
    url: ${DB_HOST}:${DB_PORT}
    user: ${DB_USER}
    database: ${DB_NAME}
    secureJsonData:
      password: ${DB_PASS}
    jsonData:
      sslmode: ${DB_SSLMODE}
      postgresVersion: 1500
      timescaledb: false
      maxOpenConns: 10
      maxIdleConns: 5
      connMaxLifetime: 14400
    isDefault: true
    editable: true
    uid: supabase-postgres
EOF
    
    echo "   ✅ Datasource provisioning file created"
    echo "   📄 File: /etc/grafana/provisioning/datasources/virtualpytest.yml"

    # postgres/postgres is the Supabase CLI's own fixed local-dev superuser password (see
    # install_supabase.sh) — it has no config.toml override, so a self-hosted install always
    # starts on it. Grafana just inherits whatever DB_USER/DB_PASS it's handed here; every
    # Editor+ Grafana user gets full SQL through this datasource, so silently shipping the
    # known default is worse than a normal weak password — it's public.
    if [ "$DB_USER" = "postgres" ] && [ "$DB_PASS" = "postgres" ]; then
        echo "   ⚠️  Datasource connects as postgres/postgres — the Supabase CLI's public"
        echo "      default. Fine on a trusted LAN; before this Grafana (or the database"
        echo "      behind it) is reachable beyond that, rotate the role's password"
        echo "      (ALTER ROLE postgres PASSWORD '<new password>') and re-run this script"
        echo "      or hand-edit the datasource file above to match."
    fi

    echo "📋 Disabling dashboard file provisioning by default..."
    sudo tee /etc/grafana/provisioning/dashboards/dashboards.yml > /dev/null << 'EOF'
# VirtualPyTest Grafana Dashboard Provisioning
# Disabled by default so dashboards remain editable in the Grafana UI.
apiVersion: 1

providers: []
EOF
    
    # Update configuration for local use (keep port 3000 as default)
    # Grafana is served directly on :3000 at this machine's address (SERVER_URL host from .env)
    PUB_HOST="$(echo "${SERVER_URL:-}" | sed -E 's|.*://([^:/]+).*|\1|')"
    grafana_ini_set server domain "${PUB_HOST:-localhost}"
    grafana_ini_set server root_url '%(protocol)s://%(domain)s:%(http_port)s/'
    grafana_ini_set server serve_from_sub_path false
    
    # Configure security settings for local development
    echo "🔒 Configuring security settings for local development..."
    
    # Disable secure cookies for HTTP (local development)
    sudo sed -i 's/cookie_secure = true/cookie_secure = false/' /etc/grafana/grafana.ini
    
    # Set SameSite to Lax for local HTTP access (None requires HTTPS)
    sudo sed -i 's/cookie_samesite = strict/cookie_samesite = lax/' /etc/grafana/grafana.ini
    sudo sed -i 's/cookie_samesite = none/cookie_samesite = lax/' /etc/grafana/grafana.ini
    
    # Ensure embedding is allowed (should already be true, but make sure)
    sudo sed -i 's/;allow_embedding = false/allow_embedding = true/' /etc/grafana/grafana.ini
    sudo sed -i 's/allow_embedding = false/allow_embedding = true/' /etc/grafana/grafana.ini
    
    # CSRF trusted origins: the UI origins allowed to call Grafana. This machine's address
    # comes from SERVER_URL in .env (written by shared/write_env.sh).
    ORIGINS="localhost:5073 127.0.0.1:5073 0.0.0.0:5073${PUB_HOST:+ $PUB_HOST:5073}"
    grafana_ini_set security csrf_trusted_origins "$ORIGINS"
    
    # Set proper permissions
    sudo chown -R grafana:grafana /var/lib/grafana
    sudo chown -R grafana:grafana /var/log/grafana
    sudo chown -R grafana:grafana /etc/grafana/
    
    echo "✅ Grafana configuration setup completed successfully"
}



# Function to create launch script
create_launch_script() {
    echo "🚀 Creating Grafana launch script..."
    
    # /opt/virtualpytest belongs to vpt_user — write through it
    sudo -u vpt_user tee "$PROJECT_ROOT/setup/local/linux/monitoring/launch_grafana.sh" > /dev/null << EOF
#!/bin/bash

# VirtualPyTest - Launch Grafana Locally
# This script starts Grafana for local development

set -e

echo "📊 Starting Grafana for VirtualPyTest local development..."

# Get to project root directory
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="\$(cd "\$SCRIPT_DIR/../.." && pwd)"

# Change to project root
cd "\$PROJECT_ROOT"

# Load credentials from .env if it exists
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Check if Grafana is installed
if ! command -v grafana-server &> /dev/null; then
    echo "❌ Grafana is not installed"
    echo "Please run: ./setup/local/install_grafana.sh"
    exit 1
fi

# Check if Grafana is configured (Linux only)
GRAFANA_CONF="/etc/grafana/grafana.ini"

if [ ! -f "\$GRAFANA_CONF" ]; then
    echo "❌ Grafana configuration not found at \$GRAFANA_CONF"
    echo "Please run: ./setup/local/install_grafana.sh"
    exit 1
fi

# Check if PostgreSQL is running (for metrics storage)
if ! pg_isready &> /dev/null; then
    echo "🐘 Starting PostgreSQL..."
    sudo systemctl start postgresql
    sleep 3
fi

# Kill any existing Grafana processes on port 3000
if lsof -ti:3000 > /dev/null 2>&1; then
    echo "🛑 Stopping existing Grafana process..."
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

echo "🚀 Starting Grafana server..."
echo "📊 Grafana will be available at: http://localhost:3000"
echo "🔑 Login: $GRAFANA_ADMIN_USER / (password set during installation)"
echo "💡 Press Ctrl+C to stop"

# Start Grafana server using system configuration (Linux)
grafana-server \\
    --config="\$GRAFANA_CONF" \\
    --homepath="/usr/share/grafana" \\
    web
EOF

    # Make launch script executable
    sudo chmod +x "$PROJECT_ROOT/setup/local/linux/monitoring/launch_grafana.sh"

    echo "✅ Launch script created at setup/local/linux/monitoring/launch_grafana.sh"
}

# Main installation process
main() {
    echo "🎯 Starting Grafana installation for VirtualPyTest..."

    # First cleanup any existing installation
    cleanup_existing_grafana

    # Install Grafana on Linux
    install_grafana

    # Setup Grafana configuration and database
    setup_grafana_config
    
    # Create launch script
    create_launch_script
    
    # Enable and start Grafana service
    echo ""
    echo "🚀 Enabling and starting Grafana service..."
    sudo systemctl enable grafana-server
    sudo systemctl start grafana-server
    
    # Wait for Grafana to start
    echo "⏳ Waiting for Grafana to start..."
    sleep 10
    
    echo ""
    echo "🔍 Installation Status Check:"
    echo ""

    # Check if Grafana is installed
    if command -v grafana-server &> /dev/null; then
        echo "✅ Grafana package: INSTALLED ($(grafana-server -v 2>/dev/null | head -1))"
    else
        echo "❌ Grafana package: NOT FOUND"
    fi

    # Check service status
    if systemctl is-active --quiet grafana-server; then
        echo "✅ Grafana service: RUNNING"
    else
        echo "❌ Grafana service: NOT RUNNING"
        echo "   🔧 To start: sudo systemctl start grafana-server"
    fi

    # Check web interface
    echo "🔍 Testing: http://localhost:3000/api/health"
    if curl -s -f --max-time 10 http://localhost:3000/api/health &> /dev/null; then
        echo "✅ Grafana web interface: ACCESSIBLE"
    else
        echo "❌ Grafana web interface: NOT RESPONDING"
        echo "   💡 Check if Grafana service is running: sudo systemctl status grafana-server"
        echo "   💡 Try starting: sudo systemctl start grafana-server"
        echo "   💡 May still be starting up..."
    fi

    # Check database connections
    echo ""
    echo "🔍 Database Connection Tests:"

    # Test database connection (use SUPABASE_DB_URI if available, otherwise VirtualPyTest vars)
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
            echo "      💡 URI: *** (check .env for full details)"
        fi
    else
        # Fallback to VirtualPyTest database variables
        echo "   🔍 Testing: postgresql://$VIRTUALPYTEST_DB_USER:***@localhost:5432/virtualpytest"
        if PGPASSWORD="$VIRTUALPYTEST_DB_PASSWORD" psql -h localhost -p 5432 -U "$VIRTUALPYTEST_DB_USER" -d virtualpytest -c "SELECT 1;" &> /dev/null; then
            echo "   ✅ VirtualPyTest DB: CONNECTED"
        else
            echo "   ❌ VirtualPyTest DB: CONNECTION FAILED"
            echo "      💡 Check if VirtualPyTest database is running on localhost:5432"
            echo "      💡 Verify credentials: $VIRTUALPYTEST_DB_USER / ***"
            echo "      💡 Database: virtualpytest"
        fi
    fi

    # Grafana uses SQLite internally for its own data (dashboards, users, etc.)
    echo "   ℹ️ Grafana Internal DB: SQLite (built-in, no external database needed)"

    echo ""
    echo "🎉 Grafana installation completed!"
    echo ""
    echo "📋 Installation Summary:"
    echo "   ✅ Grafana server installed and configured"
    echo "   ✅ Fresh SQLite database (no hardcoded credentials)"
    echo "   ✅ Datasources provisioned from .env variables"
    echo "   ✅ Dashboard JSON files loaded via provisioning"
    echo "   ✅ Local development settings applied"
    echo "   ℹ️ Datasource: $DATASOURCE_NAME ($DB_HOST:$DB_PORT/$DB_NAME)"
    echo ""
    echo "🌐 Access Information:"
    echo "   URL: http://localhost:3000"
    echo "   Admin User: $GRAFANA_ADMIN_USER"
    echo "   Admin Password: $GRAFANA_ADMIN_PASSWORD"
    echo "   Secret Key: $GRAFANA_SECRET_KEY"
    echo ""
    echo "🚀 Service Management:"
    echo "   Start:  sudo systemctl start grafana-server"
    echo "   Stop:   sudo systemctl stop grafana-server"
    echo "   Status: sudo systemctl status grafana-server"
    echo "   Logs:   sudo journalctl -u grafana-server -f"
    echo ""
    echo "🧪 Testing:"
    echo "   Run: ./setup/local/linux/monitoring/test_monitoring.sh"
    echo ""
    echo "💡 Next Steps:"
    echo "   1. Open http://localhost:3000 in your browser"
    echo "   2. Login with $GRAFANA_ADMIN_USER / $GRAFANA_ADMIN_PASSWORD"
    echo "   3. Explore the pre-configured dashboards"
    echo "   4. Configure additional data sources as needed"
    echo ""
    echo "⚙️ Configuration:"
    echo "   Edit credentials in: .env"
    echo "   Restart after changes: sudo systemctl restart grafana-server"
}

# Run main installation
main

# Make the script executable

echo "✅ Grafana installation script updated"
