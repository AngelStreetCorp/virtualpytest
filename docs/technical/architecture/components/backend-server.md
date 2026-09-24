# Backend Server Technical Documentation

**API orchestration service.**

---

## 🎯 **Purpose**

Backend Server provides:
- **REST API**: Central API layer for the frontend, under `/server/*`
- **WebSocket**: Real-time communication (Socket.IO)
- **Host Coordination**: Manages multiple Backend Host instances
- **Business Logic**: Test orchestration, campaign management, MCP tool server

Grafana monitoring is a **separate** Docker service (`setup/docker/grafana/`) that queries the
same Supabase database directly — it is not part of the `backend_server` container or deployment.

---

## 🏗️ **Architecture**

```
backend_server container:
├── Flask Application (Port 5109, or 80 on the Render blueprint)
│   ├── REST API Routes (/server/*, ~40 blueprints)
│   ├── WebSocket Handlers (Socket.IO)
│   ├── Business Logic Services (backend_server/src/services/)
│   └── Database Layer (Supabase, via shared/src/lib/database/*.py)
├── heatmap_processor (background process, scripts/heatmap_processor.py)
└── Supervisor Process Manager (backend_server/docker/supervisord.conf)
```

---

## 🌐 **API Endpoints**

Real routes live in `backend_server/src/routes/*.py`, almost all registered under the `/server`
prefix. A representative sample (see the full [API Reference](../../../api/README.md) and OpenAPI
specs under `docs/api/specs/` for the generated, complete list):

### Core / System
```
GET  /server/health                # Health check
```

### Script Execution
```
GET  /server/script/list           # -> scripts[] (bare names) + items[] {script_ref, prefix, display_name, label}
POST /server/script/execute        # send items[].script_ref, never items[].label
POST /server/script/abortRunning
GET  /server/script/status/<task_id>
```

### Campaign Management
```
GET  /server/campaigns
POST /server/campaigns
```

### Device Management
```
GET    /server/devices
POST   /server/devices
PUT    /server/devices/<id>
DELETE /server/devices/<id>
```

### Navigation Trees
```
GET/POST      /server/navigationTrees
GET/PUT/DELETE /server/navigationTrees/<tree_id>
```

---

## 🔄 **Request Flow**

### Script Execution Flow
1. Frontend calls `POST /server/script/execute` with `host_name`, `device_id`, `script_name` (and
   `team_id` as a query param).
2. `backend_server/src/routes/server_script_routes.py` validates the request and, for virtual
   scripts, fetches the DB-stored source.
3. Backend Server proxies the execution to the target Backend Host.
4. Execution status/results flow back via polling (`/server/script/status/<task_id>`) or an
   optional `callback_url` (see [webhook.md](../../webhook.md)).

### WebSocket Events
Real-time updates are pushed over Socket.IO for execution progress and device/host status —
see `backend_server/src/app.py` and the relevant service modules for the actual event names,
which evolve with the codebase; this doc intentionally doesn't hardcode a fixed payload shape.

---

## 🏢 **Business Logic Services**

Business logic lives under `backend_server/src/services/` (e.g. campaign orchestration) and
`shared/src/lib/executors/` (e.g. `script_executor.py`, `campaign_executor.py`,
`step_executor.py`) — not as ORM model classes. There is no `TestOrchestrator`/`CampaignManager`/
`HostManager` class hierarchy; look at the executor modules and route handlers directly for the
current implementation.

---

## 📊 **Database Integration**

VirtualPyTest does **not** use an ORM (no Flask-SQLAlchemy). Database access goes through
`shared/src/lib/database/*.py` modules, which call the Supabase REST API / run SQL against the
self-hosted or cloud Supabase Postgres instance using the `SUPABASE_ANON_KEY` (there is no
service-role key in this setup). See `setup/db/schema/*.sql` for the real table definitions,
applied in order via `setup/db/apply_schema.sh`.

---

## 📈 **Grafana Integration**

Grafana is deployed as its own Docker Compose stack (`setup/docker/grafana/`), with a PostgreSQL
datasource pointed at the same Supabase database backend_server uses. It is provisioned and run
independently — there is no Grafana process inside the `backend_server` container, and no
Grafana installation step in `backend_server/Dockerfile`.

---

## 🔧 **Configuration**

### Environment Variables (real, from `.env.example`)
```bash
# Server Configuration
SERVER_PORT=5109

# Database Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_DB_URI=postgresql://postgres:<password>@...supabase.com:6543/postgres

# AI Provider
AI_AGENT_PROVIDER=anthropic          # anthropic | openrouter | openai | minimax | google | local
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=
# LOCAL_AI_BASE_URL=http://10.10.10.10:8000/v1   # provider "local": any OpenAI-compatible server
# LOCAL_AI_MODEL=qwen3:8b
MCP_SECRET_KEY=your_mcp_secret

# Grafana (separate service, not this container)
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=admin123
```

> Note: `backend_server/src/app.py` never calls Flask-CORS's `CORS(app, ...)`, despite
> `Flask-CORS` being a listed dependency — there is no `CORS_ORIGINS` variable and no active
> CORS origin restriction today.

---

## 🚀 **Deployment**

### Docker
The real `backend_server/Dockerfile` installs Python 3.11, system packages (`postgresql-client`,
`xvfb`, etc.), copies `shared/` and `backend_server/`, and runs everything under `supervisord`
(`backend_server/docker/supervisord.conf`) — a `flask` program (`python src/app.py`) and a
`heatmap_processor` background program. No Grafana installation step is present.

### Render (Cloud)
Production deploys via `backend_server/src/render.yaml`, a Docker Blueprint that builds the same
Dockerfile and runs the service on port 80 (`SERVER_PORT=80`) — not a manual Python buildpack
configuration.

---

## 🔍 **Monitoring & Logging**

### Health Check
```
GET /server/health
```
Registered via the `server_core_bp` blueprint (`url_prefix='/server'`); `backend_host` also
exposes a bare `/health` alias for its own health check.

---

## 🔐 **Security**

### User Authentication
Real middleware lives in `backend_server/src/lib/auth_middleware.py`: `@require_user_auth`
validates a Supabase JWT (from the `Authorization` header), `@require_role(*roles)` and
`@require_permission(permission)` layer role/permission checks on top. Permissions use a
`namespace:action` format (e.g. `dashboard:view`, `device_control:execute`) defined in
`backend_server/src/routes/server_permissions_routes.py`'s `_ROLE_PERMISSIONS` dict.

**As of this writing, only 5 route files actually apply these decorators**:
`server_auth_routes.py`, `server_security_routes.py`, `server_system_routes.py`,
`server_storage_routes.py`, `server_device_info_overrides_routes.py`. Most of `/server/*` is
currently unauthenticated — don't assume a route is protected without checking.

Example (from `server_security_routes.py`):
```python
@server_security_bp.route('/security/report', methods=['GET'])
@require_user_auth
@require_role('admin')
def get_security_report():
    ...
```

There is no input-validation library (Marshmallow) or SQLAlchemy model layer in the real code —
request validation is done inline in each route handler.

---

**Want to understand host communication? Check [Backend Host Documentation](backend-host.md)!** 🔧
