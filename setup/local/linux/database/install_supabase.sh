#!/bin/bash

# VirtualPyTest - Install Supabase Services
# This script sets up Supabase services connecting to existing PostgreSQL database
# Assumes PostgreSQL is already installed and configured
#
# Usage: ./install_supabase.sh [DATA_DIR]
#   DATA_DIR: Optional path for Supabase data (default: /data/supabase)

set -e
# Runs as root or as the installing user (install_all.sh): privileged steps go through $SUDO.
SUDO=""; [ "$EUID" -ne 0 ] && SUDO="sudo"

echo "🔗 Installing VirtualPyTest Supabase Services..."
echo "   This connects Supabase to your existing PostgreSQL database"
echo ""

# Parse arguments
SUPABASE_DATA_DIR="${1:-/data/supabase}"
PROJECT_ROOT="/opt/virtualpytest"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

echo "📁 Directory structure:"
echo "   • Project code: $PROJECT_ROOT"
echo "   • Supabase data: $SUPABASE_DATA_DIR"
echo ""

# Check for existing Supabase installations in common locations
check_existing_installations() {
    local found_installations=()
    
    # Check common installation locations
    local common_locations=(
        "/opt/virtualpytest"
        "/data/supabase"
        "/database/supabase"
        "/databases/supabase"
    )
    
    for location in "${common_locations[@]}"; do
        if [ -d "$location/supabase" ] && [ "$location" != "$SUPABASE_DATA_DIR" ]; then
            found_installations+=("$location")
        fi
    done
    
    if [ ${#found_installations[@]} -gt 0 ]; then
        echo "⚠️  Found existing Supabase installation(s) at:"
        for install in "${found_installations[@]}"; do
            echo "   • $install/supabase"
        done
        echo ""
        echo "🔄 New installation will be at: $SUPABASE_DATA_DIR"
        echo ""
        
        # Stop any running Supabase containers to avoid conflicts
        if docker ps | grep -q "supabase"; then
            echo "🛑 Stopping existing Supabase containers to avoid conflicts..."
            for install in "${found_installations[@]}"; do
                if [ -d "$install/supabase" ]; then
                    (cd "$install" && sudo -u vpt_user supabase stop 2>/dev/null || true)
                fi
            done
            # Force stop any remaining containers
            sudo -u vpt_user docker stop $(sudo -u vpt_user docker ps -q --filter "name=supabase") 2>/dev/null || true
            echo "✅ Existing containers stopped"
        fi
        
        echo "💡 Note: Old installations are not deleted. You can:"
        echo "   • Manually remove old installations if no longer needed"
        echo "   • Or migrate data from old to new location"
        echo ""
    fi
}

echo "🔍 Checking for existing Supabase installations..."
check_existing_installations

# Create Supabase data directory if it doesn't exist
if [ ! -d "$SUPABASE_DATA_DIR" ]; then
    echo "📁 Creating Supabase data directory: $SUPABASE_DATA_DIR"
    sudo mkdir -p "$SUPABASE_DATA_DIR"
else
    echo "✅ Supabase data directory already exists: $SUPABASE_DATA_DIR"
fi

# Always ensure vpt_user owns the Supabase data directory
if id "vpt_user" &>/dev/null; then
    echo "📝 Setting ownership of $SUPABASE_DATA_DIR to vpt_user..."
    sudo chown -R vpt_user:vpt_user "$SUPABASE_DATA_DIR"
    echo "✅ Directory owned by vpt_user"
else
    echo "⚠️  vpt_user does not exist, using current user"
    sudo chown -R $USER:$USER "$SUPABASE_DATA_DIR"
fi

# Change to Supabase data directory (this is where supabase init will run)
cd "$SUPABASE_DATA_DIR"

# Function to check and install Docker if needed
check_docker() {
    # Runs as the installing user (install_all.sh) or as root: privileged steps go through $SUDO.
    local SUDO=""; [ "$EUID" -ne 0 ] && SUDO="sudo"
    echo "🐳 Checking Docker installation..."

    if ! command -v docker &> /dev/null; then
        echo "📦 Docker not found, installing..."
        $SUDO apt-get update
        $SUDO apt-get install -y docker.io

        # Configure Docker daemon for Debian 13
        if [ -f /etc/debian_version ] && grep -q "13" /etc/debian_version 2>/dev/null; then
            echo "🔧 Configuring Docker daemon for Debian 13..."
            $SUDO mkdir -p /etc/docker
            $SUDO tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "iptables": true,
  "bridge": "docker0",
  "userland-proxy": false,
  "exec-opts": ["native.cgroupdriver=systemd"]
}
EOF
            echo "✅ Docker daemon configured for Debian 13"
        fi

        $SUDO systemctl enable docker
        $SUDO systemctl start docker
        echo "✅ Docker installed"
    fi

    if ! systemctl is-active --quiet docker; then
        echo "🔄 Starting Docker service..."
        $SUDO systemctl start docker
    fi

    if ! $SUDO docker info &> /dev/null; then
        echo "❌ Docker is installed but not accessible"
        echo "   Try running with sudo or add user to docker group"
        exit 1
    fi
    
    # Check and install Docker Compose (required for Supabase)
    echo "🔧 Checking Docker Compose installation..."
    if ! $SUDO docker compose version &> /dev/null; then
        echo "📦 Docker Compose not found, installing..."
        
        # Try installing via apt first (docker-compose-plugin)
        if $SUDO apt-get install -y docker-compose-plugin 2>/dev/null; then
            echo "✅ Docker Compose plugin installed via apt"
        else
            # Fallback: Download standalone docker-compose binary
            echo "   Installing standalone Docker Compose..."
            local COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep -oP '"tag_name": "\K[^"]+')
            $SUDO curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
            $SUDO chmod +x /usr/local/bin/docker-compose
            
            # Create plugin directory and symlink for "docker compose" command
            $SUDO mkdir -p /usr/lib/docker/cli-plugins
            $SUDO ln -sf /usr/local/bin/docker-compose /usr/lib/docker/cli-plugins/docker-compose
            echo "✅ Docker Compose standalone installed"
        fi
        
        # Verify installation
        if ! $SUDO docker compose version &> /dev/null; then
            echo "❌ Docker Compose installation failed"
            echo "   Supabase requires Docker Compose to run"
            exit 1
        fi
    fi
    echo "✅ Docker Compose is available: $($SUDO docker compose version --short 2>/dev/null || docker-compose --version 2>/dev/null)"
    
    # Ensure vpt_user is in docker group
    if id "vpt_user" &>/dev/null; then
        if ! groups vpt_user | grep -q docker; then
            echo "📝 Adding vpt_user to docker group..."
            $SUDO usermod -aG docker vpt_user
            echo "✅ vpt_user added to docker group"
        else
            echo "✅ vpt_user already in docker group"
        fi
    fi
    
    echo "✅ Docker and Docker Compose are installed and running"
}

# Function to check and stop host PostgreSQL if running (Supabase will manage its own)
check_host_postgresql() {
    echo "🔍 Checking for existing PostgreSQL on host..."
    
    if systemctl is-active --quiet postgresql 2>/dev/null; then
        echo "⚠️  Found PostgreSQL running on host - Supabase will use its own PostgreSQL"
        echo "   Stopping host PostgreSQL to avoid port conflict..."
        $SUDO systemctl stop postgresql
        $SUDO systemctl disable postgresql
        echo "✅ Host PostgreSQL stopped (Supabase will run PostgreSQL in Docker)"
    else
        echo "✅ No host PostgreSQL running"
    fi
}

# Function to install Node.js (optional, may be needed for some Supabase features)
install_nodejs() {
    echo "📦 Installing Node.js (optional)..."

    NODE_MAJOR=22
    if ! command -v node &> /dev/null; then
        # Install Node.js 22.x LTS
        curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | $SUDO bash -
        $SUDO apt-get install -y nodejs
        echo "✅ Node.js $(node --version) installed"
    else
        CURRENT_NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
        if [ "$CURRENT_NODE_MAJOR" -lt "$NODE_MAJOR" ]; then
            echo "🔧 Upgrading Node.js to ${NODE_MAJOR} (current: $(node --version))..."
            $SUDO apt-get remove -y nodejs npm
            curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | $SUDO bash -
            $SUDO apt-get install -y nodejs
            echo "✅ Node.js $(node --version) installed"
        else
            echo "✅ Node.js $(node --version) already installed"
        fi
    fi
}

# Function to install Supabase CLI
install_supabase_cli() {
    echo "📦 Installing Supabase CLI..."

    if ! command -v supabase &> /dev/null; then
        # Install jq if not available (needed for JSON parsing)
        if ! command -v jq &> /dev/null; then
            echo "Installing jq (required for Supabase CLI installation)..."
            $SUDO apt-get update && apt-get install -y jq
        fi

        # Install Supabase CLI from GitHub releases
        local SUPABASE_VERSION=$(curl -s https://api.github.com/repos/supabase/cli/releases/latest | jq -r '.tag_name')

        # Detect platform and architecture
        local OS=$(uname -s | tr '[:upper:]' '[:lower:]')
        local ARCH=$(uname -m)

        # Map architecture names
        case $ARCH in
            x86_64) ARCH="amd64" ;;
            aarch64|arm64) ARCH="arm64" ;;
        esac

        local SUPABASE_URL="https://github.com/supabase/cli/releases/download/${SUPABASE_VERSION}/supabase_${OS}_${ARCH}.tar.gz"

        echo "Downloading Supabase CLI ${SUPABASE_VERSION} for ${OS}/${ARCH}..."
        curl -L -o /tmp/supabase.tar.gz "${SUPABASE_URL}"

        # Verify download succeeded and is valid
        if [ $? -ne 0 ] || [ ! -s /tmp/supabase.tar.gz ]; then
            echo "❌ Failed to download Supabase CLI"
            return 1
        fi

        tar -xzf /tmp/supabase.tar.gz -C /tmp

        # Install to /usr/local/bin (the services run it as vpt_user, so it must be
        # system-wide). `sudo -v` needs a terminal even with NOPASSWD — use `sudo -n`.
        if [ -w "/usr/local/bin" ]; then
            mv /tmp/supabase /usr/local/bin/supabase && chmod +x /usr/local/bin/supabase
        elif sudo -n true 2>/dev/null; then
            sudo -n mv /tmp/supabase /usr/local/bin/supabase && sudo -n chmod +x /usr/local/bin/supabase
        else
            mkdir -p ~/.local/bin
            mv /tmp/supabase ~/.local/bin/supabase
            chmod +x ~/.local/bin/supabase
            # Add to PATH if not already there
            if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
                export PATH="$HOME/.local/bin:$PATH"
            fi
        fi

        rm -f /tmp/supabase.tar.gz

        if ! command -v supabase &> /dev/null && [ ! -x /usr/local/bin/supabase ]; then
            echo "❌ Supabase CLI was downloaded but could not be installed to /usr/local/bin"
            return 1
        fi
        echo "✅ Supabase CLI ${SUPABASE_VERSION} installed"
    else
        echo "✅ Supabase CLI already installed (version: $(supabase --version))"
    fi
}

# Function to initialize Supabase project structure
setup_supabase_project() {
    echo "🏗️ Setting up Supabase project structure..."

    # Only reinitialize if there is no existing config (preserves config.toml on reinstall)
    if [ -d "supabase" ] && [ -f "supabase/config.toml" ]; then
        echo "   • Existing Supabase project found — keeping config.toml"
        if grep -q 'jwt_secret = "super-secret-jwt-token-with-at-least-32-characters-long"' supabase/config.toml 2>/dev/null; then
            echo "   ⚠️  This install's jwt_secret is still the public Supabase CLI default —"
            echo "      anyone who can reach this DB's REST API can forge an admin (service_role)"
            echo "      token. Rotate it: edit supabase/config.toml's [auth] jwt_secret, then"
            echo "      'supabase stop && supabase start' and update every SUPABASE_JWT_SECRET"
            echo "      in .env / .env.local to match."
        fi
    else
        if [ -d "supabase" ]; then
            sudo -u vpt_user rm -rf supabase/
        fi
        sudo -u vpt_user supabase init --yes
        echo "✅ Supabase project initialized"
    fi

    # Configure for local development with increased timeout
    echo "🔧 Configuring Supabase for local development..."
    
    # Note: health_timeout 10m — the first Postgres init (image migrations) exceeds 3m on a 4-vCPU VM
    # Note: port keys removed from [auth], [storage], [edge_runtime] - not supported in Supabase CLI v2.x
    # A per-install JWT secret. The CLI default ("super-secret-jwt-token-with-at-least-32-
    # characters-long") is public knowledge: with it anyone can mint a service_role token.
    local JWT_SECRET
    JWT_SECRET="$(openssl rand -hex 32)"
    echo "$JWT_SECRET" | sudo -u vpt_user tee supabase/.jwt_secret >/dev/null
    sudo chmod 600 supabase/.jwt_secret
    sudo -u vpt_user bash -c 'cat > supabase/config.toml' << EOF
project_id = "virtualpytest-local"

[api]
enabled = true
port = 54321
schemas = ["public", "graphql_public"]
extra_search_path = ["public", "extensions"]
max_rows = 1000

[auth]
enabled = true
site_url = "http://localhost:3000"
additional_redirect_urls = ["https://localhost:3000"]
jwt_expiry = 3600
jwt_secret = "${JWT_SECRET}"
enable_signup = true
enable_anonymous_sign_ins = false

[auth.email]
enable_signup = true
double_confirm_changes = true
enable_confirmations = true

[db]
port = 54322
shadow_port = 54320
major_version = 17
health_timeout = "10m"

[storage]
enabled = true
file_size_limit = "50MiB"

[edge_runtime]
enabled = true

[studio]
enabled = true
port = 54323
api_url = "http://localhost:54321"
EOF

    # Substitute the generated secret in now that the heredoc (deliberately unexpanded, so
    # none of the literal '$'-free TOML above needed escaping) has been written.
    sudo -u vpt_user sed -i \
        "s|jwt_secret = \"super-secret-jwt-token-with-at-least-32-characters-long\"|jwt_secret = \"${GENERATED_JWT_SECRET}\"|" \
        supabase/config.toml

    echo "✅ Supabase configuration created"
}

# Function to setup Supabase services
setup_supabase_services() {
    echo "🔧 Setting up Supabase services..."

    # Create supabase temp directory (will be populated after Supabase starts)
    sudo -u vpt_user mkdir -p supabase/.temp

    echo "✅ Supabase project structure ready"
}

# Function to run database migrations against Supabase PostgreSQL
run_database_migrations() {
    echo "📋 Running VirtualPyTest database migrations against Supabase..."
    
    MIGRATION_DIR="$PROJECT_ROOT/setup/db/schema"
    
    if [ ! -d "$MIGRATION_DIR" ]; then
        echo "⚠️  Migration directory not found: $MIGRATION_DIR"
        echo "   Skipping migrations..."
        return 0
    fi
    
    # Get Supabase database connection details
    # Supabase local uses: postgres:postgres@127.0.0.1:54322/postgres
    local SUPABASE_DB_HOST="127.0.0.1"
    local SUPABASE_DB_PORT="54322"
    local SUPABASE_DB_NAME="postgres"
    local SUPABASE_DB_USER="postgres"
    local SUPABASE_DB_PASS="postgres"
    
    # Test connection
    if ! PGPASSWORD="$SUPABASE_DB_PASS" psql -h "$SUPABASE_DB_HOST" -p "$SUPABASE_DB_PORT" -U "$SUPABASE_DB_USER" -d "$SUPABASE_DB_NAME" -c "SELECT 1;" &> /dev/null; then
        echo "❌ Cannot connect to Supabase PostgreSQL"
        echo "   Trying to connect to: postgresql://$SUPABASE_DB_USER:***@$SUPABASE_DB_HOST:$SUPABASE_DB_PORT/$SUPABASE_DB_NAME"
        return 1
    fi
    
    echo "✅ Connected to Supabase PostgreSQL"
    
    # Count total migrations
    total_migrations=$(find "$MIGRATION_DIR" -name "[0-9]*_*.sql" -type f | wc -l)
    echo "📁 Found $total_migrations migration files to process"

    # Show list of migrations
    echo "Migration files detected:"
    find "$MIGRATION_DIR" -name "[0-9]*_*.sql" -type f | sort -V | while read -r f; do
        echo "   - $(basename "$f")"
    done
    echo ""

    # Run migrations
    migration_count=0
    current=0

    while IFS= read -r migration_file; do
        migration_name=$(basename "$migration_file")

        current=$((current + 1))
        echo "🔄 [$current/$total_migrations] Running migration: $migration_name"
        
        # Run migration with error handling (use 127.0.0.1 explicitly for Docker)
        set +e
        migration_output=$(PGPASSWORD="$SUPABASE_DB_PASS" psql -h 127.0.0.1 -p "$SUPABASE_DB_PORT" -U "$SUPABASE_DB_USER" -d "$SUPABASE_DB_NAME" -f "$migration_file" 2>&1)
        migration_exit_code=$?
        set -e
        
        # Filter output
        filtered_output=$(echo "$migration_output" | grep -v "NOTICE" | grep -v "^$" | grep -v "already exists" | grep -v "does not exist, skipping" || true)
        
        if [ $migration_exit_code -eq 0 ]; then
            echo "   ✅ Migration completed: $migration_name"
            migration_count=$((migration_count + 1))
        else
            if [ -n "$filtered_output" ]; then
                echo "   ⚠️  Migration had issues: $migration_name"
                echo "$filtered_output" | head -5
            else
                echo "   ✅ Migration completed: $migration_name"
                migration_count=$((migration_count + 1))
            fi
        fi
    done < <(find "$MIGRATION_DIR" -name "[0-9]*_*.sql" -type f | sort -V)
    
    echo ""
    echo "=================================================="
    echo "📊 Migration Summary:"
    echo "   • Total migrations: $total_migrations"
    echo "   • Successful: $migration_count"
    echo "=================================================="
    echo "✅ Database migrations completed"

    # The schema files still carry the historical open policies; production closed the
    # app tables to the anon key in September 2026 (TASK-10). Same posture on a fresh
    # install: apply that idempotent migration last (mirrors setup/db/apply_schema.sh).
    local LOCKDOWN="$PROJECT_ROOT/setup/db/migrations/20260908b_close_app_tables_to_public_key.sql"
    if [ -f "$LOCKDOWN" ]; then
        echo "🔒 Closing app tables to the anon key ($(basename "$LOCKDOWN")) ..."
        local lockdown_out lockdown_rc
        set +e
        lockdown_out=$(PGPASSWORD="$SUPABASE_DB_PASS" psql -h 127.0.0.1 -p "$SUPABASE_DB_PORT" -U "$SUPABASE_DB_USER" -d "$SUPABASE_DB_NAME" -v ON_ERROR_STOP=1 -q -f "$LOCKDOWN" 2>&1)
        lockdown_rc=$?
        set -e
        if [ $lockdown_rc -eq 0 ]; then
            echo "   ✅ App tables closed to anon; the server and hosts use SUPABASE_SERVICE_ROLE_KEY"
        else
            echo "   ⚠️  Lockdown migration failed (rc=$lockdown_rc) — the anon key may still read app tables"
            echo "$lockdown_out" | grep -v "does not exist, skipping" | tail -5
        fi
    fi

    return 0
}

# Function to extract Supabase configuration from running instance
extract_supabase_config() {
    echo "🔍 Extracting Supabase configuration from running instance..."

    # Extract configuration from supabase status
    # `supabase status -o env` prints KEY="value" lines: ANON_KEY / SERVICE_ROLE_KEY are the
    # legacy JWT keys the platform uses (the table view now shows the new sb_* keys instead),
    # API_URL, DB_URL and JWT_SECRET come from the same output.
    local status_output
    status_output=$(sudo -u vpt_user supabase status -o env 2>/dev/null)
    if [ -z "$status_output" ]; then
        echo "❌ Failed to get Supabase status"
        return 1
    fi
    env_get() { echo "$status_output" | grep -E "^$1=" | head -1 | cut -d= -f2- | tr -d '"'; }
    SUPABASE_URL_EXTRACTED=$(env_get API_URL)
    SUPABASE_ANON_KEY_EXTRACTED=$(env_get ANON_KEY)
    SUPABASE_SERVICE_ROLE_KEY_EXTRACTED=$(env_get SERVICE_ROLE_KEY)
    SUPABASE_JWT_SECRET_EXTRACTED=$(env_get JWT_SECRET)
    [ -n "$SUPABASE_JWT_SECRET_EXTRACTED" ] || SUPABASE_JWT_SECRET_EXTRACTED="$(sudo cat supabase/.jwt_secret 2>/dev/null || true)"
    SUPABASE_DB_URI_EXTRACTED=$(env_get DB_URL)

    # Debug: show what we extracted
    echo "   Extracted values:"
    echo "   • Project URL: ${SUPABASE_URL_EXTRACTED:-<not found>}"
    echo "   • Anon Key: ${SUPABASE_ANON_KEY_EXTRACTED:0:20}..."
    echo "   • Service Key: ${SUPABASE_SERVICE_ROLE_KEY_EXTRACTED:0:20}..."
    echo "   • DB URI: ${SUPABASE_DB_URI_EXTRACTED:-<not found>}"

    # Verify we got all values
    if [ -n "$SUPABASE_URL_EXTRACTED" ] && [ -n "$SUPABASE_ANON_KEY_EXTRACTED" ]; then
        echo "✅ Configuration extracted from Supabase status"
        
        # Update .env.local with real values
        sudo -u vpt_user bash << EOF
cat > supabase/.env.local << ENVEOF
# Supabase Local Development Environment
# Auto-generated from running Supabase instance

# Database connection
POSTGRES_URL=${SUPABASE_DB_URI_EXTRACTED}
POSTGRES_PRISMA_URL=${SUPABASE_DB_URI_EXTRACTED}
POSTGRES_URL_NO_SSL=${SUPABASE_DB_URI_EXTRACTED}
POSTGRES_URL_NON_POOLING=${SUPABASE_DB_URI_EXTRACTED}

# Supabase service keys
ANON_KEY=${SUPABASE_ANON_KEY_EXTRACTED}
SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY_EXTRACTED}

# Supabase URLs and JWT secret
SUPABASE_URL=${SUPABASE_URL_EXTRACTED}
SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY_EXTRACTED}
SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY_EXTRACTED}
SUPABASE_JWT_SECRET=${SUPABASE_JWT_SECRET_EXTRACTED}
ENVEOF
EOF
        
        echo "✅ Updated supabase/.env.local with real values"
        return 0
    else
        echo "❌ Failed to extract configuration values"
        return 1
    fi
}

# Pre-flight check: Verify all prerequisites before starting Supabase
preflight_check() {
    echo "🔍 Running pre-flight checks..."
    local errors=0
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        echo "   ❌ Docker is not installed"
        errors=$((errors + 1))
    else
        echo "   ✅ Docker installed"
    fi
    
    # Check Docker is running
    if ! $SUDO docker info &> /dev/null; then
        echo "   ❌ Docker daemon is not running"
        errors=$((errors + 1))
    else
        echo "   ✅ Docker daemon running"
    fi
    
    # Check Docker Compose
    if ! $SUDO docker compose version &> /dev/null; then
        echo "   ❌ Docker Compose is not installed (required for Supabase)"
        errors=$((errors + 1))
    else
        echo "   ✅ Docker Compose installed"
    fi
    
    # Check Supabase CLI
    if ! command -v supabase &> /dev/null; then
        echo "   ❌ Supabase CLI is not installed"
        errors=$((errors + 1))
    else
        echo "   ✅ Supabase CLI installed"
    fi
    
    # Check vpt_user exists and has Docker access
    if ! id "vpt_user" &>/dev/null; then
        echo "   ❌ vpt_user does not exist"
        errors=$((errors + 1))
    elif ! groups vpt_user | grep -q docker; then
        echo "   ❌ vpt_user is not in docker group"
        errors=$((errors + 1))
    else
        echo "   ✅ vpt_user has Docker access"
    fi
    
    # Check supabase directory exists
    if [ ! -d "supabase" ]; then
        echo "   ❌ Supabase project not initialized (supabase/ directory missing)"
        errors=$((errors + 1))
    else
        echo "   ✅ Supabase project initialized"
    fi
    
    if [ $errors -gt 0 ]; then
        echo ""
        echo "❌ Pre-flight check failed with $errors error(s)"
        echo "   Please fix the issues above before starting Supabase"
        return 1
    fi
    
    echo "✅ All pre-flight checks passed"
    return 0
}

# Function to start Supabase services
start_supabase_services() {
    echo "🚀 Starting Supabase services..."

    # Run pre-flight checks first
    if ! preflight_check; then
        return 1
    fi

    # Check if data already exists in the Supabase Docker volume
    # The CLI names volumes supabase_db_<project_id> (project_id = "virtualpytest-local" in config.toml)
    local existing_volume=$(sudo -u vpt_user docker volume ls -q | grep -E "^supabase_db_virtualpytest-local$" 2>/dev/null || true)
    local has_data=false
    if [ -n "$existing_volume" ]; then
        # Volume exists — check if it actually has PostgreSQL data files
        local pg_files=$(sudo -u vpt_user docker run --rm -v supabase_db_virtualpytest-local:/data alpine sh -c "ls /data/PG_VERSION 2>/dev/null" 2>/dev/null || true)
        if [ -n "$pg_files" ]; then
            has_data=true
        fi
    fi

    if $has_data; then
        echo "📦 Existing database detected — preserving data, restarting containers only..."
        # Stop containers only, never remove volumes when data exists
        sudo -u vpt_user supabase stop 2>/dev/null || true
        if sudo -u vpt_user docker ps -a | grep -q "supabase"; then
            sudo -u vpt_user docker stop $(sudo -u vpt_user docker ps -aq --filter "name=supabase") 2>/dev/null || true
            sudo -u vpt_user docker rm $(sudo -u vpt_user docker ps -aq --filter "name=supabase") 2>/dev/null || true
        fi
        echo "✅ Containers stopped — data volumes preserved"
    else
        echo "🧹 No existing data — performing clean installation..."
        sudo -u vpt_user supabase stop 2>/dev/null || true
        if sudo -u vpt_user docker ps -a | grep -q "supabase"; then
            echo "   • Stopping existing Supabase containers..."
            sudo -u vpt_user docker stop $(sudo -u vpt_user docker ps -aq --filter "name=supabase") 2>/dev/null || true
            echo "   • Removing existing Supabase containers..."
            sudo -u vpt_user docker rm $(sudo -u vpt_user docker ps -aq --filter "name=supabase") 2>/dev/null || true
        fi
        local supabase_volumes=$(sudo -u vpt_user docker volume ls -q | grep supabase 2>/dev/null || true)
        if [ -n "$supabase_volumes" ]; then
            echo "   • Removing empty Supabase volumes..."
            echo "$supabase_volumes" | xargs -r sudo -u vpt_user docker volume rm 2>/dev/null || true
        fi
        echo "✅ Clean slate ready"
    fi

    # Start Supabase fresh (let Supabase handle its own health checks)
    echo "Starting Supabase local development server (fresh installation)..."
    echo "   This will download Docker images (~350MB) on first run..."

    sudo -u vpt_user supabase start

    if [ $? -eq 0 ]; then
        echo "✅ Supabase services started successfully"
        return 0
    else
        echo "❌ Failed to start Supabase services"
        return 1
    fi
}


# Write config/database/local.env from the extracted Supabase values. Always rewrites the
# whole file: appending left the first (stale) block winning when shared/write_env.sh read it,
# and a leftover template writer used to overwrite the real keys afterwards.
update_config_file_with_extracted_values() {
    echo "⚙️ Writing VirtualPyTest database configuration from the running Supabase instance..."
    if [ -z "${SUPABASE_ANON_KEY_EXTRACTED:-}" ] || [ -z "${SUPABASE_SERVICE_ROLE_KEY_EXTRACTED:-}" ]; then
        echo "❌ No extracted keys — config/database/local.env not written"
        return 1
    fi
    sudo -u vpt_user mkdir -p "$PROJECT_ROOT/config/database"
    sudo -u vpt_user tee "$PROJECT_ROOT/config/database/local.env" > /dev/null << EOF
# VirtualPyTest Supabase Configuration (generated by install_supabase.sh — re-run it to refresh)
# Supabase manages PostgreSQL + Auth + API in Docker

# Supabase PostgreSQL Database (running in Docker)
VIRTUALPYTEST_DB_HOST=localhost
VIRTUALPYTEST_DB_PORT=54322
VIRTUALPYTEST_DB_NAME=postgres
VIRTUALPYTEST_DB_USER=postgres
VIRTUALPYTEST_DB_PASSWORD=postgres
VIRTUALPYTEST_DB_URI=${SUPABASE_DB_URI_EXTRACTED:-postgresql://postgres:postgres@localhost:54322/postgres}

# Supabase Configuration (extracted from the running instance)
SUPABASE_URL=${SUPABASE_URL_EXTRACTED:-http://localhost:54321}
SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY_EXTRACTED}
SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY_EXTRACTED}
SUPABASE_JWT_SECRET=${SUPABASE_JWT_SECRET_EXTRACTED}
SUPABASE_DB_URI=${SUPABASE_DB_URI_EXTRACTED:-postgresql://postgres:postgres@localhost:54322/postgres}

# Supabase Studio (Web Interface)
SUPABASE_STUDIO_URL=http://localhost:54323
EOF
    echo "✅ config/database/local.env written"
}


# Main installation logic
echo "🔍 Checking Docker (required for Supabase)..."
check_docker

echo "🔍 Installing PostgreSQL client (psql)..."
if ! command -v psql &> /dev/null; then
    $SUDO apt-get update && apt-get install -y postgresql-client
    echo "✅ PostgreSQL client installed"
else
    echo "✅ PostgreSQL client already installed"
fi

echo "🔍 Checking for host PostgreSQL..."
check_host_postgresql

echo "🔍 Installing Node.js (optional for development)..."
install_nodejs

echo "🔍 Installing Supabase CLI..."
install_supabase_cli

echo "🔍 Setting up Supabase project..."
setup_supabase_project

echo "🔍 Configuring Supabase services..."
setup_supabase_services

echo "🔍 Patching Supabase docker-compose (minimal mode)..."
if [[ -f "$PROJECT_ROOT/setup/local/linux/database/patch_supabase_compose.sh" ]]; then
    "$PROJECT_ROOT/setup/local/linux/database/patch_supabase_compose.sh" "$SUPABASE_DATA_DIR" || true
else
    echo "⚠️  patch_supabase_compose.sh not found, skipping"
fi

echo "🔍 Starting Supabase services..."
if start_supabase_services; then
    echo "🔍 Extracting Supabase configuration..."
    extract_supabase_config || echo "⚠️  Config extraction failed, continuing with migrations..."

    echo "🔍 Running database migrations..."
    run_database_migrations

    echo "🔍 Updating configuration with real values..."
    update_config_file_with_extracted_values || echo "⚠️  Config update skipped (extraction may have failed)"
else
    echo "❌ Supabase failed to start"
    exit 1
fi



# Install Supabase systemd service for auto-start on boot
install_supabase_service() {
    echo "🔧 Installing Supabase systemd service for auto-start..."
    
    # Get script directory and service config path
    CONFIG_DIR="${SCRIPT_DIR}/../config/services"
    SUPABASE_SERVICE_FILE="${CONFIG_DIR}/supabase.service"

    if [ ! -f "$SUPABASE_SERVICE_FILE" ]; then
        echo "❌ Supabase service file not found: $SUPABASE_SERVICE_FILE"
        echo "   This file should exist in the config directory"
        return 1
    fi
    
    # Stop existing service if running
    sudo systemctl stop supabase 2>/dev/null || true
    
    # Use vpt_user (VirtualPyTest service user) for consistency
    SERVICE_USER="vpt_user"
    
    # Ensure vpt_user is in docker group
    if ! groups "$SERVICE_USER" | grep -q docker; then
        echo "📝 Adding $SERVICE_USER to docker group..."
        sudo usermod -aG docker "$SERVICE_USER"
        echo "✅ $SERVICE_USER added to docker group"
    else
        echo "✅ $SERVICE_USER already in docker group"
    fi
    
    # Ensure vpt_user owns the Supabase data directory
    if [ -d "$SUPABASE_DATA_DIR" ]; then
        echo "📝 Setting ownership of $SUPABASE_DATA_DIR to $SERVICE_USER..."
        sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$SUPABASE_DATA_DIR"
        echo "✅ Ownership updated"
    fi
    
    # Process the service template and copy to systemd directory
    echo "📝 Processing Supabase service template..."
    echo "   User: $SERVICE_USER"
    echo "   Supabase Data Dir: $SUPABASE_DATA_DIR"

    if sed -e "s|%SUPABASE_DATA_DIR%|$SUPABASE_DATA_DIR|g" \
           "$SUPABASE_SERVICE_FILE" > /tmp/supabase.service.tmp 2>/dev/null; then
        echo "✅ Service file processed successfully"
    else
        echo "❌ Failed to process service file"
        echo "   Service file: $SUPABASE_SERVICE_FILE"
        echo "   Supabase data dir: $SUPABASE_DATA_DIR"
        return 1
    fi
    
    # Copy to systemd directory
    sudo cp /tmp/supabase.service.tmp /etc/systemd/system/supabase.service
    rm -f /tmp/supabase.service.tmp
    
    # Reload systemd daemon
    sudo systemctl daemon-reload
    
    # Enable service for auto-start
    sudo systemctl enable supabase
    
    echo "✅ Supabase systemd service installed and enabled"
    echo "   • Service will start automatically on boot"
    echo "   • Manages Supabase Docker containers"
    
    # Start the service now. The installer started the stack directly for the migrations;
    # hand it over to systemd from a stopped state so the unit performs one clean start
    # instead of a restart the CLI may take longer for.
    echo ""
    echo "🚀 Starting Supabase service..."
    (cd "$SUPABASE_DATA_DIR" && sudo -u vpt_user supabase stop 2>/dev/null) || true
    if sudo systemctl start supabase; then
        echo "✅ Supabase service started successfully"
        
        # Wait a moment for service to initialize
        sleep 3
        
        # Check status
        echo ""
        echo "📊 Checking Supabase service status..."
        sudo systemctl status supabase --no-pager || true
        
        echo ""
        echo "🔍 Verifying Supabase containers..."
        if sudo -u vpt_user docker ps | grep -q supabase; then
            echo "✅ Supabase containers are running"
            sudo -u vpt_user docker ps | grep supabase | awk '{print "   • " $NF}'
        else
            echo "⚠️  Supabase containers not yet started, checking logs..."
            sudo journalctl -u supabase -n 20 --no-pager
        fi
    else
        echo "⚠️  Failed to start Supabase service"
        echo "   Check logs: sudo journalctl -u supabase -f"
        return 1
    fi
    
    echo ""
    echo "📋 Service Management Commands:"
    echo "   • Check status: sudo systemctl status supabase"
    echo "   • View logs: sudo journalctl -u supabase -f"
    echo "   • Stop: sudo systemctl stop supabase"
    echo "   • Restart: sudo systemctl restart supabase"
    echo "   • Disable auto-start: sudo systemctl disable supabase"
}

echo "🔧 Installing Supabase auto-start service..."
install_supabase_service

# Install daily backup cron
install_backup_cron() {
    echo "🔧 Installing daily database backup cron..."

    local BACKUP_SCRIPT_SRC="${SCRIPT_DIR}/vpt-db-backup.sh"
    local BACKUP_SCRIPT_DST="/usr/local/bin/vpt-db-backup.sh"

    if [ ! -f "$BACKUP_SCRIPT_SRC" ]; then
        echo "⚠️  Backup script not found at $BACKUP_SCRIPT_SRC — skipping"
        return 0
    fi

    # Backend the daily backup posts its status to: SERVER_URL from the project .env when
    # set (multi-VM installs), otherwise the local server.
    local BACKEND_URL
    BACKEND_URL="$(grep -E '^SERVER_URL=' "$PROJECT_ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | sed 's/[[:space:]]*#.*$//' | xargs)"
    BACKEND_URL="${BACKEND_URL:-http://localhost:5109}"

    # Install backup script with correct BACKEND_URL substituted
    sed "s|VPT_BACKEND_URL:-http://localhost:5109|VPT_BACKEND_URL:-${BACKEND_URL}|" \
        "$BACKUP_SCRIPT_SRC" | $SUDO tee "$BACKUP_SCRIPT_DST" > /dev/null
    $SUDO chmod +x "$BACKUP_SCRIPT_DST"

    # Create backup data directory
    $SUDO mkdir -p /data/backups

    # Shared service key so the status POST passes the server's /server/* guard
    # (closed by default). Prefer VPT_API_KEY from the environment, else the
    # API_KEY of the project .env when this VM also carries the repo.
    local VPT_API_KEY="${VPT_API_KEY:-$(grep -E '^API_KEY=' "$PROJECT_ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2-)}"
    if [ -z "$VPT_API_KEY" ] || [ "$VPT_API_KEY" = "your_api_key_here" ]; then
        VPT_API_KEY=""
        echo "⚠️  VPT_API_KEY not set — backup status reports will be rejected (401) until you add VPT_API_KEY=<backend API_KEY> to /etc/cron.d/vpt-db-backup"
    fi

    # Install cron job (runs at 02:00 daily). File holds the service key: root-only.
    $SUDO tee /etc/cron.d/vpt-db-backup > /dev/null << EOF
# VirtualPyTest daily PostgreSQL backup — runs at 02:00
# Logs to /var/log/vpt-db-backup.log
VPT_API_KEY=${VPT_API_KEY}
0 2 * * * root /usr/local/bin/vpt-db-backup.sh >> /var/log/vpt-db-backup.log 2>&1
EOF
    $SUDO chmod 600 /etc/cron.d/vpt-db-backup

    echo "✅ Backup cron installed — runs daily at 02:00"
    echo "   • Script: $BACKUP_SCRIPT_DST"
    echo "   • Cron: /etc/cron.d/vpt-db-backup"
    echo "   • Log: /var/log/vpt-db-backup.log"
    echo "   • Backend URL: $BACKEND_URL"
}

echo "🔧 Installing daily backup cron..."
install_backup_cron

echo ""
echo "🎉 VirtualPyTest Supabase Installation Completed!"
echo ""
echo "📊 Database Details:"
echo "   • PostgreSQL running in Docker (managed by Supabase)"
echo "   • Port: 54322"
echo "   • Database: postgres"
echo "   • User: postgres / postgres"
echo "   • Connection: postgresql://postgres:postgres@localhost:54322/postgres"
echo ""
echo "🔗 Supabase Services:"
echo "   • Supabase URL: $SUPABASE_URL_EXTRACTED"
echo "   • Supabase Studio: http://localhost:54323"
echo "   • Supabase API: http://localhost:54321"
echo "   • Anon Key: ${SUPABASE_ANON_KEY_EXTRACTED:0:20}..."
echo "   • Service Role Key: ${SUPABASE_SERVICE_ROLE_KEY_EXTRACTED:0:20}..."
echo ""
echo "📁 Directory Structure:"
echo "   • Project code: $PROJECT_ROOT"
echo "   • Supabase data: $SUPABASE_DATA_DIR"
echo "   • Database config: $PROJECT_ROOT/config/database/local.env"
echo "   • Supabase config: $SUPABASE_DATA_DIR/supabase/config.toml"
echo "   • Next: setup/local/linux/shared/write_env.sh copies these into .env (install_all.sh does it)"
echo ""
echo "🔧 Management Commands:"
echo "   • Check service status: sudo systemctl status supabase"
echo "   • Start service: sudo systemctl start supabase"
echo "   • Stop service: sudo systemctl stop supabase"
echo "   • Restart service: sudo systemctl restart supabase"
echo "   • View service logs: sudo journalctl -u supabase -f"
echo "   • Disable auto-start: sudo systemctl disable supabase"
echo ""
echo "   • Manual Supabase commands (run from $SUPABASE_DATA_DIR):"
echo "     - cd $SUPABASE_DATA_DIR"
echo "     - supabase status"
echo "     - supabase logs"
echo "   • Connect to DB: psql postgresql://postgres:postgres@localhost:54322/postgres"
echo "   • Backup database: pg_dump postgresql://postgres:postgres@localhost:54322/postgres > backup.sql"
echo ""
echo "🌐 Access URLs:"
echo "   • Supabase Studio: http://localhost:54323"
echo "   • Supabase API: http://localhost:54321"
echo ""
echo "💡 What's been set up:"
echo "   • Supabase running in Docker with PostgreSQL, Auth, Storage, and API"
echo "   • Systemd service configured for auto-start on boot"
echo "   • Database migrations applied"
echo "   • Environment variables configured"
echo "   • Ready for VirtualPyTest application startup"
echo ""
echo "🚀 Auto-Start Configuration:"
echo "   • Supabase will automatically start on VM boot/reboot"
echo "   • Service will restart automatically if it crashes"
echo "   • No manual intervention required after reboot"
echo ""
echo "🔒 Security — before this box is reachable beyond a trusted LAN:"
echo "   • The Postgres superuser is postgres/postgres — this is the Supabase CLI's own fixed"
echo "     local-dev credential, not something this script chose, and it has no config.toml"
echo "     override. If port 54322 (or Grafana / any tool holding this password) will be"
echo "     reachable from outside a trusted network, rotate it:"
echo "       ALTER ROLE postgres PASSWORD '<new password>';  -- then update every place"
echo "       -- that connects as postgres (Grafana datasource, backup scripts, .env)."
echo "   • jwt_secret in $SUPABASE_DATA_DIR/supabase/config.toml was generated fresh for"
echo "     this install (not the Supabase CLI's public default) — leave it as is unless you"
echo "     have reason to rotate it too."
