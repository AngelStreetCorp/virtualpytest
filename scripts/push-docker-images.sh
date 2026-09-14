#!/bin/bash

# Parse command line arguments
BUILD_HOST=false
BUILD_SERVER=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --host)
            BUILD_HOST=true
            shift
            ;;
        --server)
            BUILD_SERVER=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--host] [--server]"
            echo "  --host    Build and push only backend_host"
            echo "  --server  Build and push only backend_server"
            echo "  (no args) Build and push both"
            exit 1
            ;;
    esac
done

# If no flags specified, build both
if [ "$BUILD_HOST" = false ] && [ "$BUILD_SERVER" = false ]; then
    BUILD_HOST=true
    BUILD_SERVER=true
fi

# Load environment variables from .env file (in parent directory)
if [ -f ../.env ]; then
    export $(cat ../.env | grep -E '^(GITHUB_USERNAME|GITHUB_PAT)=' | xargs)
else
    echo "Error: .env file not found in parent directory"
    exit 1
fi

# Check if required variables are set
if [ -z "$GITHUB_USERNAME" ] || [ -z "$GITHUB_PAT" ]; then
    echo "Error: GITHUB_USERNAME or GITHUB_PAT not found in .env file"
    echo "GITHUB_USERNAME: '$GITHUB_USERNAME'"
    echo "GITHUB_PAT length: ${#GITHUB_PAT}"
    exit 1
fi

echo "🔐 Logging in to GitHub Container Registry..."
echo "Username: $GITHUB_USERNAME"
echo "PAT length: ${#GITHUB_PAT} characters"

# Test if Docker is running
if ! docker info &>/dev/null; then
    echo "❌ Docker is not running! Please start Docker Desktop."
    exit 1
fi

# Login
echo "Attempting login..."
echo "Running: docker login ghcr.io -u $GITHUB_USERNAME"
echo "$GITHUB_PAT" | docker login ghcr.io -u "$GITHUB_USERNAME" --password-stdin 2>&1

LOGIN_RESULT=$?
echo "Login command finished with exit code: $LOGIN_RESULT"

if [ $LOGIN_RESULT -ne 0 ]; then
    echo "❌ Failed to login to GHCR"
    exit 1
fi

echo "✅ Login successful!"

echo ""
echo "🔧 Setting up Docker buildx..."
echo "Checking available builders..."
docker buildx ls

echo "Using default builder..."
docker buildx use default

echo "Inspecting and bootstrapping builder..."
docker buildx inspect --bootstrap

echo "✅ Buildx setup complete!"

# Set BuildKit environment variables
export BUILDKIT_PROGRESS=plain
export DOCKER_BUILDKIT=1
echo "BuildKit variables set"

# Build and push backend_host if requested
if [ "$BUILD_HOST" = true ]; then
    echo ""
    echo "🏗️  Building virtualpytest-host for linux/amd64..."
    echo "Optimized build: Using BuildKit cache and inline cache for faster builds"
    echo "Expected image size: ~3.7GB (65% smaller after removing torch/CUDA)"
    echo "Starting build at $(date)..."

    docker buildx build \
      --platform linux/amd64 \
      --tag ghcr.io/$GITHUB_USERNAME/virtualpytest-host:latest \
      --file ../backend_host/Dockerfile \
      --build-arg BUILDKIT_INLINE_CACHE=1 \
      --cache-from ghcr.io/$GITHUB_USERNAME/virtualpytest-host:latest \
      --push \
      --progress=plain \
      ..

    BUILD_RESULT=$?
    echo "Build finished at $(date) with exit code: $BUILD_RESULT"
    if [ $BUILD_RESULT -ne 0 ]; then
        echo "❌ Failed to build virtualpytest-host"
        exit 1
    fi

    echo "✅ virtualpytest-host pushed successfully!"
    docker manifest inspect ghcr.io/$GITHUB_USERNAME/virtualpytest-host:latest --verbose 2>/dev/null | grep -E '(size|platform)' | head -5 || echo "Image available at ghcr.io/$GITHUB_USERNAME/virtualpytest-host:latest"
fi

# Build and push backend_server if requested
if [ "$BUILD_SERVER" = true ]; then
    echo ""
    echo "🏗️  Building virtualpytest-server for linux/amd64..."
    echo "Optimized build: Using BuildKit cache and inline cache for faster builds"
    echo "Starting build at $(date)..."

    docker buildx build \
      --platform linux/amd64 \
      --tag ghcr.io/$GITHUB_USERNAME/virtualpytest-server:latest \
      --file ../backend_server/Dockerfile \
      --build-arg BUILDKIT_INLINE_CACHE=1 \
      --cache-from ghcr.io/$GITHUB_USERNAME/virtualpytest-server:latest \
      --push \
      --progress=plain \
      ..

    BUILD_RESULT=$?
    echo "Build finished at $(date) with exit code: $BUILD_RESULT"
    if [ $BUILD_RESULT -ne 0 ]; then
        echo "❌ Failed to build virtualpytest-server"
        exit 1
    fi

    echo "✅ virtualpytest-server pushed successfully!"
    docker manifest inspect ghcr.io/$GITHUB_USERNAME/virtualpytest-server:latest --verbose 2>/dev/null | grep -E '(size|platform)' | head -5 || echo "Image available at ghcr.io/$GITHUB_USERNAME/virtualpytest-server:latest"
fi

echo ""
echo "✅ Build and push complete!"
echo ""
echo "Images pushed:"
if [ "$BUILD_HOST" = true ]; then
    echo "  - ghcr.io/$GITHUB_USERNAME/virtualpytest-host:latest"
fi
if [ "$BUILD_SERVER" = true ]; then
    echo "  - ghcr.io/$GITHUB_USERNAME/virtualpytest-server:latest"
fi
echo ""
echo "✅ Compatible with Render (linux/amd64)"

