# VirtualPyTest Architecture

**High-level system design for developers and system administrators.**

---

## 🎯 **System Overview**

VirtualPyTest uses a **microservices architecture** with clear separation of concerns:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    Frontend     │    │ Backend Server  │    │  Backend Host   │
│   (React/TS)    │◄──►│   (Flask/Py)    │◄──►│   (Flask/Py)    │
│                 │    │                 │    │                 │
│ • Test UI       │    │ • API Routes    │    │ • Device Control│
│ • Monitoring    │    │ • Test Logic    │    │ • Hardware I/O  │
│ • Config        │    │ • Data Storage  │    │ • Verification  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌───────────────────────┐
                    │  Shared / Core Logic  │
                    │ (shared/, backend_host│
                    │  /src/{controllers,   │
                    │  services,interfaces})│
                    └───────────────────────┘
```

---

## 🏢 **Complete Infrastructure Diagram**

```
                                    ┌─────────────────────────────────────────────────────────────┐
                                    │                         CLOUD                               │
                                    │  ┌─────────────────┐   ┌─────────────────┐                  │
                                    │  │   Cloudflare    │   │    OpenRouter   │                  │
                                    │  │      R2         │   │    (AI/LLM)     │                  │
                                    │  │  ┌───────────┐  │   │  ┌───────────┐  │                  │
                                    │  │  │Screenshots│  │   │  │ GPT-4o    │  │                  │
                                    │  │  │  Videos   │  │   │  │ Claude    │  │                  │
                                    │  │  │  Logs     │  │   │  │ Gemini    │  │                  │
                                    │  │  └───────────┘  │   │  └───────────┘  │                  │
                                    │  └────────▲────────┘   └────────▲────────┘                  │
                                    │           │                     │                           │
                                    │           │ S3 API              │ REST API                  │
                                    │           │                     │                           │
┌──────────────────────────────┐    │  ┌─────────────────────────────────────┐                  │
│         INTERNET             │    │  │              Backend Server         │                  │
│  ┌─────────────────────┐     │    │  │           (Render / Docker)         │                  │
│  │      Frontend       │     │    │  │  ┌─────────────────────────────┐    │                  │
│  │   (Vercel / CDN)    │     │    │  │  │          Flask API           │   │                  │
│  │  ┌───────────────┐  │ HTTPS    │  │  │          Port 5109           │   │                  │
│  │  │   React App   │──┼─────┼────┼──┼─►│                               │   │                  │
│  │  │    :5073      │  │     │    │  │  │ • REST API (/server/*)       │   │                  │
│  │  └───────────────┘  │     │    │  │  │ • WebSocket                  │   │                  │
│  └─────────────────────┘     │    │  │  │ • MCP Server                 │   │                  │
│                              │    │  │  └──────────────┬───────────────┘   │                  │
└──────────────────────────────┘    │  └─────────────────┼───────────────────┘                  │
                                    │                    │                                       │
                                    │                    │ SQL Queries                           │
                                    │                    ▼                                       │
                                    │  ┌─────────────────────────────────────────┐                │
                                    │  │              Supabase                   │                │
                                    │  │            (PostgreSQL)                 │                │
                                    │  │  ┌───────────┐  ┌───────────────────┐   │                │
                                    │  │  │   Data    │  │  Real-time Subs   │   │                │
                                    │  │  │  Tables   │  │  (WebSocket)      │   │                │
                                    │  │  └───────────┘  └───────────────────┘   │                │
                                    │  └─────────────────────────────────────────┘                │
                                    └─────────────────────────────────────────────────────────────┘
                                                         │
                                                         │ HTTPS (Outbound from Host)
                                                         │
┌────────────────────────────────────────────────────────┼────────────────────────────────────────┐
│                                    LOCAL NETWORK       │                                        │
│  ┌─────────────────────────────────────────────────────┴───────────────────────────────────┐   │
│  │                            Backend Host (Raspberry Pi / Local)                          │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │   │
│  │  │   Flask API     │  │   VNC Server    │  │     NoVNC       │  │  FFmpeg Capture │     │   │
│  │  │   Port 6109     │  │   Port 5900     │  │   Port 6080     │  │   (Streaming)   │     │   │
│  │  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘     │   │
│  │           │                    │                    │                    │              │   │
│  │           └────────────────────┴────────────────────┴────────────────────┘              │   │
│  │                                           │                                              │   │
│  │                              Hardware Abstraction Layer                                  │   │
│  │                                           │                                              │   │
│  │     ┌─────────────┬─────────────┬─────────────┬─────────────┬─────────────┐             │   │
│  │     │  USB/ADB    │    HDMI     │   GPIO/IR   │   Audio     │   Network   │             │   │
│  │     │  Devices    │   Capture   │   Control   │   Capture   │   Devices   │             │   │
│  │     └──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┘             │   │
│  └────────────┼─────────────┼─────────────┼─────────────┼─────────────┼─────────────────────┘   │
│               │             │             │             │             │                         │
│         ┌─────┴─────┐ ┌─────┴─────┐ ┌─────┴─────┐ ┌─────┴─────┐ ┌─────┴─────┐                  │
│         │  Android  │ │   TV /    │ │   Set-Top │ │   Audio   │ │   Smart   │                  │
│         │  Mobile   │ │  Display  │ │    Box    │ │  Devices  │ │   Plugs   │                  │
│         └───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

> **Note**: Grafana runs as a separate Docker service (`setup/docker/grafana/`), not embedded
> in the Render `backend_server` deployment. It queries the same Supabase database directly.

---

## 🌐 **Network Architecture & Requirements**

### Port Requirements

| Service | Port | Protocol | Direction | Description |
|---------|------|----------|-----------|-------------|
| **Frontend** | 5073 | HTTP/HTTPS | Inbound | Vite dev server / Nginx |
| **Backend Server** | 5109 | HTTP/HTTPS | Inbound | Flask REST API + WebSocket |
| **Grafana** | 3001 | HTTP/HTTPS | Inbound | Monitoring dashboards (separate Docker service) |
| **Backend Host** | 6109 | HTTP/HTTPS | Inbound | Host REST API |
| **VNC** | 5900 | TCP | Inbound | VNC server (raw) |
| **NoVNC** | 6080 | HTTP/WS | Inbound | VNC web interface |
| **Supabase** | 54321-54324 | TCP | Outbound | Database, API, Studio, Mailpit |
| **R2 Storage** | 443 | HTTPS | Outbound | S3-compatible API |
| **OpenRouter** | 443 | HTTPS | Outbound | AI/LLM API |

### Connection Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     CONNECTION FLOW                                          │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

  USER BROWSER                    CLOUD SERVICES                         LOCAL NETWORK
       │                               │                                      │
       │    ①  HTTPS :443              │                                      │
       ├───────────────────────────────►  Frontend (Vercel CDN)               │
       │                               │     │                                │
       │    ②  HTTPS :443              │     │ Static Assets                  │
       │◄──────────────────────────────┼─────┘                                │
       │                               │                                      │
       │    ③  HTTPS :5109             │                                      │
       ├───────────────────────────────►  Backend Server (Render)             │
       │       REST API + WebSocket    │     │                                │
       │                               │     │ ④  SQL :5432                   │
       │                               │     ├───────► Supabase               │
       │                               │     │                                │
       │                               │     │ ⑤  HTTPS :443                  │
       │                               │     ├───────► Cloudflare R2          │
       │                               │     │                                │
       │                               │     │ ⑥  HTTPS :443                  │
       │                               │     ├───────► OpenRouter (AI)        │
       │                               │     │                                │
       │                               │     │ ⑦  HTTPS :6109                 │
       │                               │     └───────────────────────────────►│ Backend Host
       │                               │                                      │     │
       │    ⑧  HTTPS :6080             │                                      │     │
       ├──────────────────────────────────────────────────────────────────────►│ NoVNC
       │       VNC Web Access          │                                      │     │
       │                               │                                      │     │
       │                               │                                      │     │ ⑨  Local
       │                               │                                      │     └──► Devices
       │                               │                                      │
       └───────────────────────────────┴──────────────────────────────────────┘

  LEGEND:
  ─────────────────────────────────────────────────────────────────────────────
  ① User loads frontend from CDN
  ② Static React app delivered
  ③ Frontend calls Backend Server API (REST + WebSocket)
  ④ Backend Server queries Supabase PostgreSQL
  ⑤ Backend Server uploads/downloads from R2 storage
  ⑥ Backend Server calls AI/LLM for analysis
  ⑦ Backend Server coordinates with Backend Host
  ⑧ User accesses VNC via NoVNC web interface
  ⑨ Backend Host controls physical devices
```

### Reverse Proxy Configuration

**For production deployment with Nginx:**

```nginx
# Backend Server Proxy (if self-hosted)
server {
    listen 443 ssl;
    server_name api.virtualpytest.com;
    
    ssl_certificate /etc/ssl/certs/virtualpytest.crt;
    ssl_certificate_key /etc/ssl/private/virtualpytest.key;
    
    # REST API
    location /server/ {
        proxy_pass http://localhost:5109;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # WebSocket
    location /socket.io/ {
        proxy_pass http://localhost:5109;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
    
    # Grafana
    location /grafana/ {
        proxy_pass http://localhost:3001/;
        proxy_set_header Host $host;
    }
}

# Backend Host Proxy (local network exposure)
server {
    listen 443 ssl;
    server_name host.virtualpytest.local;
    
    # Host API
    location /host/ {
        proxy_pass http://localhost:6109;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
    
    # NoVNC Web Interface
    location /vnc/ {
        proxy_pass http://localhost:6080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # Video Stream (HLS/captures)
    location /stream/ {
        alias /var/www/html/stream/;
        # Try hot storage first (RAM), fallback to cold (SD)
        try_files $uri @cold_storage;
        add_header Cache-Control "no-cache";
    }
    
    location @cold_storage {
        root /var/www/html;
    }
}
```

### Firewall Rules

```bash
# Backend Server (Cloud / Render)
# Managed by cloud provider - no manual config needed

# Backend Host (Raspberry Pi / Local)
# Required inbound ports:
sudo ufw allow 6109/tcp   # Host API
sudo ufw allow 6080/tcp   # NoVNC web interface
sudo ufw allow 5900/tcp   # VNC (optional, if direct VNC access needed)

# Required outbound ports:
# 443/tcp  - HTTPS to Backend Server, Supabase, R2
# 54321-54324/tcp - Supabase services (API, Database, Studio, Mailpit)
```

### Network Security Requirements

| Requirement | Local Dev | Production |
|-------------|-----------|------------|
| **HTTPS/TLS** | Optional | Required |
| **API Authentication** | Only 5 route files enforce `@require_user_auth`/`@require_role` today (auth, security, system, storage, device-info-overrides); most of `/server/*` is currently unauthenticated | Same posture today; hardening this is tracked as ongoing work |
| **VPN/Tunnel** | Not needed | Recommended for Host |
| **IP Allowlist** | Not needed | Optional |

> Note: `backend_server` does not currently call Flask-CORS (`CORS(app, ...)`) anywhere, despite
> `Flask-CORS` being a listed dependency — there is no active CORS origin restriction today.

---

## 🏗️ **Component Architecture**

### Frontend (React TypeScript)
**Purpose**: Web-based user interface
- **Technology**: React 18, TypeScript, Material-UI, Vite
- **Deployment**: Static files (Vercel, Nginx)
- **Communication**: REST API + WebSocket to Backend Server

**Key Features**:
- Device management interface
- Test execution dashboard
- Real-time monitoring
- Campaign configuration

### Backend Server (Flask Python)
**Purpose**: API orchestration and business logic
- **Technology**: Flask, Gunicorn, SQLAlchemy
- **Deployment**: Docker container (Render, local)
- **Database**: PostgreSQL (Supabase)

**Key Features**:
- REST API endpoints
- WebSocket real-time updates
- Test orchestration
- Host coordination
- Grafana integration

### Backend Host (Flask Python)
**Purpose**: Hardware interface and device control
- **Technology**: Flask, device drivers, system libraries
- **Deployment**: Docker on hardware (Pi, local machine)
- **Hardware Access**: USB, video capture, GPIO

**Key Features**:
- Direct device control
- Hardware abstraction
- Screenshot capture
- Power management

### Backend Core (Python Library)
**Purpose**: Shared business logic and device controllers
- **Technology**: Pure Python, no web dependencies
- **Deployment**: Imported by other services
- **Structure**: Controllers, Services, Interfaces

**Key Features**:
- Device controller implementations
- Navigation pathfinding
- Test execution logic
- Verification services

### Shared Library (Python)
**Purpose**: Common utilities and configuration
- **Technology**: Python utilities, configuration management
- **Deployment**: Imported by all Python services
- **Structure**: Config, Models, Utils

**Key Features**:
- Environment configuration
- Data models
- Validation utilities
- Constants and exceptions

---

## 🔄 **Data Flow**

### Test Execution Flow
```
1. User creates test via Frontend
2. Frontend sends request to Backend Server
3. Backend Server finds available Backend Host
4. Backend Server sends execution request to Backend Host
5. Backend Host uses Backend Core controllers
6. Backend Host executes test on physical device
7. Results flow back: Host → Server → Frontend
8. Screenshots and logs stored for analysis
```

### Real-Time Monitoring Flow
```
1. Backend Host captures device state/screenshots
2. Backend Host sends updates to Backend Server
3. Backend Server stores metrics in database
4. Grafana queries database for dashboard updates
5. Frontend receives WebSocket updates
6. User sees real-time status in web interface
```

---

## 📊 **Database Design**

### Core Tables
- **devices**: Physical device configurations
- **hosts**: Available host machines
- **test_cases**: Test definitions
- **campaigns**: Test campaign configurations
- **test_executions**: Test run history
- **navigation_trees**: Device UI navigation maps
- **screenshots**: Captured images and metadata

### Relationships
```
campaigns (1) → (N) test_executions
test_executions (1) → (N) screenshots
devices (1) → (N) test_executions
hosts (1) → (N) test_executions
navigation_trees (1) → (N) devices
```

---

## 🌐 **API Architecture**

### REST API Endpoints
**Backend Server** exposes ~40 route groups, almost all under the `/server/*` prefix (a single legacy blueprint uses `/api/events`), including:
- `/server/campaigns/*` - Campaign management
- `/server/devices/*`, `/server/devicemodel/*`, `/server/device-flags/*` - Device configuration
- `/server/navigation/*`, `/server/navigationTrees/*` - Navigation tree CRUD
- `/server/script/*` - Script execution
- `/server/auth/*` - Authentication
- `/server/monitoring/*`, `/server/metrics/*` - Metrics and monitoring
- `/server/mcp/*` - MCP tool server

See the full [API Reference](../../api/README.md) and OpenAPI specs for the complete, generated endpoint list.

### WebSocket Events
**Real-time communication** for:
- Test execution progress
- Device status updates
- System health notifications
- Alert broadcasts

### Host Communication
**Backend Server ↔ Backend Host**:
- Host registration and heartbeat
- Test execution requests
- Status updates and results
- Screenshot and log transfer

---

## 🔧 **Deployment Architecture**

### Environment Comparison

| Component | Local Development | Production (Cloud + Local) |
|-----------|-------------------|----------------------------|
| **Frontend** | Docker :5073 | Vercel (CDN) |
| **Backend Server** | Docker :5109 | Render (Auto-scale) |
| **Grafana** | Docker :3001 | Separate Docker service (`setup/docker/grafana/`) |
| **Backend Host** | Docker :6109 | Raspberry Pi / Local |
| **Database** | Supabase (self-hosted or cloud) | Supabase Cloud |
| **Storage** | Local / R2 | Cloudflare R2 |
| **AI/LLM** | Anthropic (default) / OpenRouter / others | Anthropic (default) / OpenRouter / others |

### Local Development

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DOCKER COMPOSE ENVIRONMENT                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐            │
│  │    frontend     │   │ backend_server  │   │  backend_host   │            │
│  │     :5073       │──►│     :5109       │──►│     :6109       │            │
│  │  Hot Reload     │   │                 │   │     :5900       │            │
│  │                 │   │                 │   │     :6080       │            │
│  └─────────────────┘   └─────────────────┘   └─────────────────┘            │
│           │                     │                     │                     │
│           └──────────────┬──────┴─────────────────────┘                     │
│                          │                     ┌─────────────────┐          │
│                   Shared Volumes               │ grafana (:3001) │          │
│           (/backend_host, /shared, /frontend)  │ separate stack  │          │
│                                                 └─────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────┐
                          │    Supabase     │
                          │     Cloud       │
                          └─────────────────┘
```

### Production Deployment

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PRODUCTION ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   CLOUD (Fully Managed)                    LOCAL (Self-Managed)             │
│  ┌─────────────────────────────────────┐  ┌─────────────────────────────┐   │
│  │                                     │  │                             │   │
│  │  ┌─────────────┐  ┌─────────────┐   │  │  ┌─────────────────────┐    │   │
│  │  │   Vercel    │  │   Render    │   │  │  │   Raspberry Pi /    │    │   │
│  │  │  Frontend   │  │   Server    │◄──┼──┼──│   Local Machine     │    │   │
│  │  │    CDN      │  │             │   │  │  │                     │    │   │
│  │  └─────────────┘  └──────┬──────┘   │  │  │  • Backend Host     │    │   │
│  │                          │          │  │  │  • VNC Server       │    │   │
│  │  ┌─────────────┐  ┌──────┴──────┐   │  │  │  • Device Control   │    │   │
│  │  │ Cloudflare  │  │  Supabase   │   │  │  │  • Video Capture    │    │   │
│  │  │     R2      │  │ PostgreSQL  │   │  │  └─────────────────────┘    │   │
│  │  │  Storage    │  │  Database   │   │  │             │               │   │
│  │  └─────────────┘  └─────────────┘   │  │             ▼               │   │
│  │                                     │  │  ┌─────────────────────┐    │   │
│  │  ┌─────────────┐                    │  │  │  Physical Devices   │    │   │
│  │  │ OpenRouter  │                    │  │  │  • Android Mobile   │    │   │
│  │  │   AI/LLM    │                    │  │  │  • TV / Set-Top Box │    │   │
│  │  │   API       │                    │  │  │  • Smart Plugs      │    │   │
│  │  └─────────────┘                    │  │  └─────────────────────┘    │   │
│  │                                     │  │                             │   │
│  └─────────────────────────────────────┘  └─────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

> Grafana (port 3001) is deployed as its own separate Docker service (`setup/docker/grafana/`)
> alongside these components, not embedded in the Render `backend_server` deployment.

### Container Architecture

```
backend_server container:
├── Flask application (port 5109)
├── Supervisor process manager
└── Shared volumes (backend_host, shared)

grafana container (separate stack, setup/docker/grafana/):
└── Grafana service (port 3001)

backend_host container:
├── Flask application (port 6109)
├── VNC server (port 5900)
├── NoVNC web interface (port 6080)
└── Hardware device access (/dev/*)
```

### Host-to-Server Communication

**Backend Host → Backend Server connection options:**

| Method | Use Case | Configuration |
|--------|----------|---------------|
| **Direct HTTPS** | Host has public IP | `SERVER_URL=https://api.virtualpytest.com` |
| **ngrok Tunnel** | Development/testing | `ngrok http 6109` + use ngrok URL |
| **Cloudflare Tunnel** | Production (no public IP) | `cloudflared tunnel` service |
| **VPN** | Enterprise networks | Connect to VPN, use internal URL |
| **Tailscale** | Zero-config mesh VPN | Install Tailscale on both |

---

## 🔒 **Security Architecture**

### Authentication & Authorization
- **API Keys**: Service-to-service communication
- **Supabase Auth (JWT)**: User authentication, enforced on a subset of `/server/*` routes today — see the note above
- **Environment Variables**: Sensitive configuration
- **Network Isolation**: Docker container networking

### Data Protection
- **Encrypted Storage**: Sensitive configuration data
- **Secure Communication**: HTTPS/WSS in production
- **Access Control**: Role-based permissions
- **Audit Logging**: Security event tracking

---

## ⚡ **Performance Architecture**

### Scalability Patterns
- **Horizontal Host Scaling**: Multiple Backend Host instances
- **Load Balancing**: Request distribution across hosts
- **Caching**: Configuration and navigation tree caching
- **Async Processing**: Non-blocking test execution

### Resource Management
- **Connection Pooling**: Database connections
- **Memory Management**: Screenshot and log cleanup
- **CPU Optimization**: Efficient image processing
- **Storage Management**: Automated cleanup policies

---

## 🔄 **Integration Architecture**

### External Services

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL SERVICES                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────┐    ┌──────────────────────┐                       │
│  │      SUPABASE        │    │    CLOUDFLARE R2     │                       │
│  │    (PostgreSQL)      │    │   (Object Storage)   │                       │
│  ├──────────────────────┤    ├──────────────────────┤                       │
│  │ • Database tables    │    │ • Screenshots        │                       │
│  │ • Row Level Security │    │ • Video recordings   │                       │
│  │ • Real-time subs     │    │ • Log archives       │                       │
│  │ • Auth (optional)    │    │ • S3-compatible API  │                       │
│  │                      │    │                      │                       │
│  │ Port: 5432 (TCP)     │    │ Port: 443 (HTTPS)    │                       │
│  │ Region: Global       │    │ Region: Global CDN   │                       │
│  └──────────────────────┘    └──────────────────────┘                       │
│                                                                             │
│  ┌──────────────────────┐    ┌──────────────────────┐                       │
│  │     AI PROVIDER       │    │       GRAFANA        │                       │
│  │  (Anthropic default,  │    │    (Monitoring)      │                       │
│  │  OpenRouter/others)   │    ├──────────────────────┤                       │
│  ├──────────────────────┤    │ • Dashboards         │                       │
│  │ • Agent / Vision /    │    │ • Alerting           │                       │
│  │   Text analysis       │    │ • SQL queries        │                       │
│  │                      │    │ • Separate Docker svc│                       │
│  │ Port: 443 (HTTPS)    │    │ Port: 3001           │                       │
│  │ Auth: API Key        │    │ Auth: Admin user     │                       │
│  └──────────────────────┘    └──────────────────────┘                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Supabase (Database)
- **Purpose**: PostgreSQL database hosting with real-time capabilities
- **Connection**: Direct PostgreSQL (port 5432) + REST API (port 443)
- **Features**: Row Level Security, real-time subscriptions, auto-backups
- **Used by**: Backend Server, Grafana (as a separate datasource)

#### Cloudflare R2 (Object Storage)
- **Purpose**: Store screenshots, videos, and logs
- **Connection**: S3-compatible API (HTTPS port 443)
- **Features**: Global CDN, no egress fees, 10GB free tier
- **Used by**: Backend Server, Backend Host

#### AI Provider (Anthropic default, OpenRouter/OpenAI/others supported)
- **Purpose**: AI-powered agent, vision analysis, UI detection, verification
- **Connection**: REST API (HTTPS port 443)
- **Default**: Anthropic (agent task); OpenRouter (vision/text tasks) unless overridden — see `shared/src/lib/ai/config.py`
- **Used by**: Backend Server (via MCP tools)

#### Grafana (Monitoring)
- **Purpose**: Real-time monitoring dashboards and alerting
- **Connection**: Separate Docker service (`setup/docker/grafana/`), NOT embedded in the Backend Server container — queries Supabase directly
- **Features**: PostgreSQL datasource, pre-built dashboards
- **Access**: Port 3001

### Hardware Integration
- **USB Devices**: Android ADB, iOS tools
- **Video Capture**: HDMI capture cards, cameras
- **Network Devices**: Smart plugs, IoT devices
- **Serial/GPIO**: Direct hardware control

---

## 📈 **Monitoring Architecture**

### Metrics Collection
```
Application Metrics:
├── Test execution statistics
├── Device performance data
├── System resource usage
└── Error rates and patterns

Infrastructure Metrics:
├── Container resource usage
├── Network connectivity
├── Database performance
└── External service health
```

### Alerting Strategy
- **Threshold-based**: Numeric metric alerts
- **Anomaly Detection**: Pattern-based alerts
- **Composite Alerts**: Multiple condition alerts
- **Escalation Policies**: Multi-level notifications

---

## 🔧 **Development Architecture**

### Code Organization
```
Project Structure:
├── frontend/              # React TypeScript app
├── backend_server/        # API orchestration service
├── backend_host/          # Hardware interface service + core controllers/services/interfaces
├── shared/                # Common utilities library
├── setup/docker/          # Container orchestration
└── docs/                  # Documentation
```

Note: there is no separate `backend_core/` directory — controller/service/interface logic lives under
`backend_host/src/{controllers,services,interfaces}` (see [Backend Core](components/backend-core.md)).

### Build & Deployment Pipeline
- **Frontend**: Vite build → Static files → CDN
- **Backend Services**: Docker build → Container registry → Deploy
- **Libraries**: Python package → Import in services
- **Documentation**: Markdown → Static site generation

---

## 🎯 **Design Principles**

### Microservices Benefits
- **Separation of Concerns**: Each service has single responsibility
- **Technology Diversity**: Best tool for each job
- **Independent Scaling**: Scale components based on load
- **Fault Isolation**: Service failures don't cascade

### Shared Library Strategy
- **Code Reuse**: Common logic in backend_host and shared
- **Consistency**: Same interfaces across services
- **Maintainability**: Single source of truth for business logic
- **Testing**: Isolated unit testing of core functionality

---

**Want to understand specific components?**
- [Frontend](components/frontend.md) - React TypeScript web interface
- [Backend Server](components/backend-server.md) - API orchestration
- [Backend Host](components/backend-host.md) - Hardware interface service
- [Backend Core](components/backend-core.md) - Core controllers/services/interfaces (lives under backend_host/src)
- [Shared Library](components/shared.md) - Common utilities
