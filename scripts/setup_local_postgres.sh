#!/bin/bash

# Local PostgreSQL Setup Script for VirtualPyTest
# This script helps you set up and manage local PostgreSQL for development

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/setup/docker/docker-compose.local.yml"
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/env.local.example"

echo -e "${BLUE}🐘 VirtualPyTest Local PostgreSQL Setup${NC}"
echo "=================================================="

# Function to print colored output
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    print_status "Docker is running"
}

# Check if docker-compose is available
check_compose() {
    if ! command -v docker-compose >/dev/null 2>&1; then
        print_error "docker-compose is not installed. Please install it and try again."
        exit 1
    fi
    print_status "docker-compose is available"
}

# Setup environment file
setup_env() {
    if [ ! -f "$ENV_FILE" ]; then
        if [ -f "$ENV_EXAMPLE" ]; then
            print_info "Creating .env file from template..."
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            print_status "Environment file created: $ENV_FILE"
            print_warning "Please review and update the .env file with your specific values"
        else
            print_error "Environment template not found: $ENV_EXAMPLE"
            exit 1
        fi
    else
        print_status "Environment file already exists: $ENV_FILE"
    fi
}

# Start PostgreSQL services
start_postgres() {
    print_info "Starting local PostgreSQL services..."
    
    cd "$PROJECT_ROOT"
    docker-compose -f "$COMPOSE_FILE" up -d postgres grafana_metrics_db redis
    
    print_status "PostgreSQL services started"
    print_info "Waiting for databases to be ready..."
    
    # Wait for PostgreSQL to be ready
    for i in {1..30}; do
        if docker-compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U vpt_user -d virtualpytest >/dev/null 2>&1; then
            print_status "Main PostgreSQL database is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            print_error "PostgreSQL failed to start within 30 seconds"
            exit 1
        fi
        sleep 1
    done
    
    # Wait for Grafana metrics DB to be ready
    for i in {1..30}; do
        if docker-compose -f "$COMPOSE_FILE" exec -T grafana_metrics_db pg_isready -U grafana_user -d grafana_metrics >/dev/null 2>&1; then
            print_status "Grafana metrics database is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            print_error "Grafana metrics database failed to start within 30 seconds"
            exit 1
        fi
        sleep 1
    done
}

# Initialize database schema
init_schema() {
    print_info "Initializing database schema..."
    
    # Run initialization script
    if [ -f "$PROJECT_ROOT/setup/db/init_local_postgres.sql" ]; then
        docker-compose -f "$COMPOSE_FILE" exec -T postgres psql -U vpt_user -d virtualpytest < "$PROJECT_ROOT/setup/db/init_local_postgres.sql"
        print_status "Database schema initialized"
    else
        print_warning "Database initialization script not found, skipping schema setup"
    fi
}

# Start all services
start_all() {
    print_info "Starting all VirtualPyTest services..."
    
    cd "$PROJECT_ROOT"
    docker-compose -f "$COMPOSE_FILE" up -d
    
    print_status "All services started"
    
    echo ""
    echo -e "${GREEN}🎉 VirtualPyTest is now running with local PostgreSQL!${NC}"
    echo ""
    echo "Services available at:"
    echo "  • Frontend:        http://localhost:3000"
    echo "  • Backend API:     http://localhost:5109"
    echo "  • Backend Host:    http://localhost:6109"
    echo "  • Grafana:         http://localhost:5109/grafana"
    echo "  • PostgreSQL:      localhost:5432"
    echo "  • Grafana DB:      localhost:5433"
    echo "  • Redis:           localhost:6379"
    echo ""
    echo "Database credentials:"
    echo "  • Main DB:         vpt_user / vpt_local_pass"
    echo "  • Grafana DB:      grafana_user / grafana_pass"
    echo ""
}

# Stop services
stop_services() {
    print_info "Stopping VirtualPyTest services..."
    
    cd "$PROJECT_ROOT"
    docker-compose -f "$COMPOSE_FILE" down
    
    print_status "Services stopped"
}

# Show service status
show_status() {
    print_info "Service Status:"
    
    cd "$PROJECT_ROOT"
    docker-compose -f "$COMPOSE_FILE" ps
}

# Show logs
show_logs() {
    local service=${1:-""}
    
    cd "$PROJECT_ROOT"
    if [ -n "$service" ]; then
        print_info "Showing logs for $service..."
        docker-compose -f "$COMPOSE_FILE" logs -f "$service"
    else
        print_info "Showing logs for all services..."
        docker-compose -f "$COMPOSE_FILE" logs -f
    fi
}

# Connect to PostgreSQL
connect_postgres() {
    print_info "Connecting to PostgreSQL..."
    docker-compose -f "$COMPOSE_FILE" exec postgres psql -U vpt_user -d virtualpytest
}

# Reset database
reset_database() {
    print_warning "This will destroy all data in the local database!"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Resetting database..."
        
        cd "$PROJECT_ROOT"
        docker-compose -f "$COMPOSE_FILE" down -v
        docker-compose -f "$COMPOSE_FILE" up -d postgres grafana_metrics_db redis
        
        # Wait for PostgreSQL to be ready
        sleep 5
        init_schema
        
        print_status "Database reset complete"
    else
        print_info "Database reset cancelled"
    fi
}

# Show help
show_help() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  setup     - Set up environment and start PostgreSQL"
    echo "  start     - Start all services"
    echo "  stop      - Stop all services"
    echo "  status    - Show service status"
    echo "  logs      - Show logs for all services"
    echo "  logs <service> - Show logs for specific service"
    echo "  psql      - Connect to PostgreSQL"
    echo "  reset     - Reset database (destroys all data)"
    echo "  help      - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 setup              # Initial setup"
    echo "  $0 start              # Start all services"
    echo "  $0 logs postgres      # Show PostgreSQL logs"
    echo "  $0 psql               # Connect to database"
}

# Main script logic
case "${1:-setup}" in
    "setup")
        check_docker
        check_compose
        setup_env
        start_postgres
        init_schema
        print_status "Setup complete! Run '$0 start' to start all services."
        ;;
    "start")
        check_docker
        check_compose
        start_all
        ;;
    "stop")
        stop_services
        ;;
    "status")
        show_status
        ;;
    "logs")
        show_logs "$2"
        ;;
    "psql")
        connect_postgres
        ;;
    "reset")
        reset_database
        ;;
    "help"|"-h"|"--help")
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
