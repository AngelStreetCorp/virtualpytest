#!/bin/bash

# =============================================================================
# Langfuse Self-Hosted Installation Script
# LLM Observability for AI Agent System
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           Langfuse Self-Hosted Installation               ║${NC}"
echo -e "${BLUE}║           LLM Observability for AI Agents                 ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Configuration
LANGFUSE_PORT=${LANGFUSE_PORT:-3001}
LANGFUSE_DIR="$HOME/.langfuse"
DOCKER_COMPOSE_FILE="$LANGFUSE_DIR/docker-compose.yml"

# Check prerequisites
check_prerequisites() {
    echo -e "${YELLOW}→ Checking prerequisites...${NC}"
    
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}✗ Docker is not installed. Please install Docker first.${NC}"
        echo "  Visit: https://docs.docker.com/get-docker/"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        echo -e "${RED}✗ Docker Compose is not installed.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Prerequisites met${NC}"
}

# Check if port is available
check_port() {
    if lsof -Pi :$LANGFUSE_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠ Port $LANGFUSE_PORT is already in use.${NC}"
        
        # Check if it's Langfuse
        if docker ps | grep -q langfuse; then
            echo -e "${GREEN}✓ Langfuse is already running on port $LANGFUSE_PORT${NC}"
            echo -e "  Dashboard: ${BLUE}http://localhost:$LANGFUSE_PORT${NC}"
            exit 0
        fi
        
        echo -e "${YELLOW}  Trying port $((LANGFUSE_PORT + 1))...${NC}"
        LANGFUSE_PORT=$((LANGFUSE_PORT + 1))
        
        if lsof -Pi :$LANGFUSE_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
            echo -e "${RED}✗ Port $LANGFUSE_PORT also in use. Please free a port or set LANGFUSE_PORT.${NC}"
            exit 1
        fi
    fi
    echo -e "${GREEN}✓ Port $LANGFUSE_PORT is available${NC}"
}

# Create docker-compose file
create_compose_file() {
    echo -e "${YELLOW}→ Creating Langfuse configuration...${NC}"
    
    mkdir -p "$LANGFUSE_DIR"
    
    # Generate secrets
    NEXTAUTH_SECRET=$(openssl rand -base64 32)
    SALT=$(openssl rand -base64 32)
    
    cat > "$DOCKER_COMPOSE_FILE" << EOF
version: '3.8'

services:
  langfuse-server:
    image: langfuse/langfuse:2
    container_name: langfuse-web
    restart: unless-stopped
    ports:
      - "${LANGFUSE_PORT}:3000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@langfuse-db:5432/postgres
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
      - SALT=${SALT}
      - NEXTAUTH_URL=http://localhost:${LANGFUSE_PORT}
      - TELEMETRY_ENABLED=false
      - LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES=false
      # Allow iframe embedding for local development
      - NEXT_PUBLIC_ENABLE_EXPERIMENTAL_FEATURES=false
      # Configure CSP to allow embedding from localhost
      - CSP_ALLOW_IFRAME_SELF=true
    depends_on:
      langfuse-db:
        condition: service_healthy
    networks:
      - langfuse-network

  langfuse-db:
    image: postgres:15-alpine
    container_name: langfuse-db
    restart: unless-stopped
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=postgres
    volumes:
      - langfuse-postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - langfuse-network


volumes:
  langfuse-postgres-data:

networks:
  langfuse-network:
    driver: bridge
EOF
    
    echo -e "${GREEN}✓ Configuration created at $DOCKER_COMPOSE_FILE${NC}"
}

# Start Langfuse
start_langfuse() {
    echo -e "${YELLOW}→ Starting Langfuse...${NC}"
    
    cd "$LANGFUSE_DIR"
    
    # Use docker compose (v2) or docker-compose (v1)
    if docker compose version &> /dev/null; then
        docker compose up -d
    else
        docker-compose up -d
    fi
    
    echo -e "${GREEN}✓ Langfuse containers started${NC}"
}

# Wait for Langfuse to be ready
wait_for_ready() {
    echo -e "${YELLOW}→ Waiting for Langfuse to be ready (this may take 1-2 minutes)...${NC}"
    
    local max_attempts=60
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s "http://localhost:$LANGFUSE_PORT" > /dev/null 2>&1; then
            echo ""
            echo -e "${GREEN}✓ Langfuse is ready!${NC}"
            return 0
        fi
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo ""
    echo -e "${RED}✗ Langfuse did not become ready in time.${NC}"
    echo "  Check logs with: docker logs langfuse-web"
    echo "  Check database: docker logs langfuse-db"
    exit 1
}

# Generate environment config
generate_env_config() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}✓ Langfuse Installation Complete!${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo ""
    echo "1. Open Langfuse dashboard:"
    echo -e "   ${BLUE}http://localhost:$LANGFUSE_PORT${NC}"
    echo ""
    echo "2. Create your account (first user becomes admin)"
    echo ""
    echo "3. Go to Settings → API Keys → Create new API keys"
    echo ""
    echo "4. Add to .env (project root):"
    echo ""
    echo -e "${GREEN}# Langfuse LLM Observability${NC}"
    echo -e "${GREEN}LANGFUSE_ENABLED=true${NC}"
    echo -e "${GREEN}LANGFUSE_HOST=http://localhost:$LANGFUSE_PORT${NC}"
    echo -e "${GREEN}LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key${NC}"
    echo -e "${GREEN}LANGFUSE_SECRET_KEY=sk-lf-your-secret-key${NC}"
    echo ""
    echo "5. Restart backend_server to enable observability"
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
}

# Stop command
stop_langfuse() {
    echo -e "${YELLOW}→ Stopping Langfuse...${NC}"
    cd "$LANGFUSE_DIR" 2>/dev/null || { echo -e "${RED}Langfuse not installed${NC}"; exit 1; }
    
    if docker compose version &> /dev/null; then
        docker compose down
    else
        docker-compose down
    fi
    
    echo -e "${GREEN}✓ Langfuse stopped${NC}"
}

# Status command
status_langfuse() {
    if docker ps | grep -q langfuse; then
        echo -e "${GREEN}✓ Langfuse is running${NC}"
        echo -e "  Dashboard: ${BLUE}http://localhost:$LANGFUSE_PORT${NC}"
        docker ps --filter "name=langfuse" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        echo -e "${YELLOW}○ Langfuse is not running${NC}"
        echo "  Start with: ./scripts/langfuse_install.sh"
    fi
}

# Uninstall command
uninstall_langfuse() {
    echo -e "${YELLOW}→ Uninstalling Langfuse...${NC}"
    
    cd "$LANGFUSE_DIR" 2>/dev/null || { echo -e "${RED}Langfuse not installed${NC}"; exit 1; }
    
    if docker compose version &> /dev/null; then
        docker compose down -v
    else
        docker-compose down -v
    fi
    
    rm -rf "$LANGFUSE_DIR"
    
    echo -e "${GREEN}✓ Langfuse uninstalled${NC}"
}

# Main
case "${1:-install}" in
    install)
        check_prerequisites
        check_port
        create_compose_file
        start_langfuse
        wait_for_ready
        generate_env_config
        ;;
    stop)
        stop_langfuse
        ;;
    start)
        cd "$LANGFUSE_DIR"
        if docker compose version &> /dev/null; then
            docker compose up -d
        else
            docker-compose up -d
        fi
        echo -e "${GREEN}✓ Langfuse started at http://localhost:$LANGFUSE_PORT${NC}"
        ;;
    status)
        status_langfuse
        ;;
    uninstall)
        uninstall_langfuse
        ;;
    *)
        echo "Usage: $0 {install|start|stop|status|uninstall}"
        exit 1
        ;;
esac

