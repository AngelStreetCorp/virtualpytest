FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    nano \
    htop \
    net-tools \
    git \
    dnsutils \
    lsof \
    nfs-common \
    curl \
    gnupg2 \
    supervisor \
    postgresql-client \
    libpq-dev \
    libpq5 \
    libgl1-mesa-dri \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    xvfb \
    vim \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy shared library
COPY shared/ shared/
# Add shared to PYTHONPATH
ENV PYTHONPATH="/app/shared:/app/shared/src/lib:/app/backend_server/src"

# Copy backend_server requirements and install with exact versions
COPY backend_server/requirements.txt backend_server/
RUN pip install --no-cache-dir -r backend_server/requirements.txt

# Copy backend_server source scripts configuration
COPY backend_server/src/ backend_server/src/
COPY backend_server/scripts/ backend_server/scripts/
COPY backend_server/config/ backend_server/config/
# shared/src/lib/executors import backend_host modules — ship them (no runtime mount)
COPY backend_host/src/ backend_host/src/

# No .env is baked into the image: configuration arrives at runtime
# (docker compose `env_file:` / `environment:`, or a mounted /app/.env).

# Set working directory to backend_server
WORKDIR /app/backend_server

# Create non-root user for security (VirtualPyTest Service Account)
RUN useradd --system \
        --shell /bin/false \
        --home /var/lib/vpt_user \
        --create-home \
        --comment "VirtualPyTest Service Account" \
        vpt_user && chmod 1777 /tmp \
    && mkdir -p /var/log/supervisor \
    && chown -R vpt_user:vpt_user /var/log/supervisor /app

# Copy supervisor configuration from docker folder
COPY backend_server/docker/supervisord.conf /etc/supervisor/conf.d/virtualpytest.conf

# Expose ports for Flask
EXPOSE 5109

# Health check for Flask API
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:5109/server/health || exit 1

# SECURITY NOTE: supervisord runs as vpt_user for better security
USER vpt_user

# Run supervisor to manage Flask
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf", "-n"] 