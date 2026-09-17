FROM python:3.11-slim

# Install system dependencies for hardware control, VNC, and NoVNC
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    supervisor \
    xvfb \
    x11-utils \
    x11vnc \
    tigervnc-tools \
    novnc \
    websockify \
    fluxbox \
    xterm \
    scrot \
    python3-tk \
    python3-dev \
    libopencv-dev \
    ffmpeg \
    gcc \
    g++ \
    make \
    build-essential \
    linux-libc-dev \
    android-tools-adb \
    libpq-dev \
    libpq5 \
    libgl1-mesa-dri \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    chromium \
    chromium-driver \
    nano \
    dnsutils \
    iputils-ping \
    traceroute \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy shared library
COPY shared/ shared/
# Add shared to PYTHONPATH
ENV PYTHONPATH="/app/shared:/app/shared/src/lib:/app/backend_host/src"

# Copy backend_host requirements and install with exact versions
COPY backend_host/requirements.txt backend_host/
RUN pip install --no-cache-dir -r backend_host/requirements.txt

# Install Playwright WebKit browser and all its system dependencies
RUN playwright install-deps webkit
RUN playwright install webkit

# Copy backend_host source scripts configuration
COPY backend_host/src/ backend_host/src/
COPY backend_host/scripts/ backend_host/scripts/
COPY backend_host/config/ backend_host/config/

# No .env is baked into the image: backend_host/src/.env is mounted at runtime
# (see setup/docker/docker-compose.yml) and the entrypoint refuses to start without it.

# Set working directory to backend_host
WORKDIR /app/backend_host

# Create non-root user for security (VirtualPyTest Service Account)
RUN useradd --system \
        --shell /bin/false \
        --home /var/lib/vpt_user \
        --create-home \
        --comment "VirtualPyTest Service Account" \
        vpt_user && chmod 1777 /tmp

# Create directories and set proper permissions
RUN mkdir -p /var/www/html \
    && mkdir -p /var/www/html/stream \
    && mkdir -p /var/log/supervisor \
    && mkdir -p /var/run \
    && mkdir -p /tmp/.X11-unix \
    && mkdir -p /home/vpt_user/.android \
    && mkdir -p /home/vpt_user/.vnc \
    && mkdir -p /app/backend_host/src \
    && chown -R vpt_user:vpt_user /app \
    && chown -R vpt_user:vpt_user /var/www \
    && chown -R vpt_user:vpt_user /home/vpt_user \
    && chmod -R 755 /var/www \
    && chmod -R 1777 /tmp/.X11-unix


# No VNC password in the image. This image is published to GHCR, so anything baked here
# would be the same password on every pull. The entrypoint writes
# /home/vpt_user/.vnc/passwd on each start from HOST_VNC_PASSWORD, and generates a
# per-container one when that is unset.

# Copy supervisor configuration from docker folder
COPY backend_host/docker/supervisord.conf /etc/supervisor/conf.d/virtualpytest.conf

# Copy Docker helper scripts (use absolute path to avoid WORKDIR confusion)
COPY backend_host/docker/scripts/ /app/backend_host/docker/scripts/
# Fix Windows line endings if present (very common on Win hosts)
RUN sed -i 's/\r$//' /app/backend_host/docker/scripts/*.sh \
    && chmod +x /app/backend_host/docker/scripts/*.sh
RUN sed -i 's/\r$//' /app/backend_host/scripts/*.sh \
    && chmod +x /app/backend_host/scripts/*.sh

# Expose port 6109 for flask
EXPOSE 6109

# Set display and ADB environment
ENV DISPLAY=:1
ENV HOST_VIDEO_SOURCE=:1
ENV ANDROID_HOME=/home/vpt_user/.android
ENV ADB_VENDOR_KEYS=/home/vpt_user/.android

# Health check for Flask API
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:6109/host/system/health || exit 1

# SECURITY NOTE: supervisord runs as root to manage all services
# However, all processes drop privileges to 'vpt_user' via supervisord config
USER root

# Use entrypoint script to generate .env and start supervisord
CMD ["/app/backend_host/docker/scripts/entrypoint.sh"]

