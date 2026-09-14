# Postman Configuration

## Architecture (like real Postman!)

This is a **general-purpose API testing system** that works like public Postman:

1. **Workspaces** → Containers for collections (fetched from Postman API)
2. **Environments** → Sets of variables (like `{{base_url}}`, `{{team_id}}`, etc.)
3. **Variable Substitution** → `{{variable}}` in paths/params are replaced with environment values

## Configuration Files

### `postman_config.json`

Main configuration file with workspaces and environments:

```json
{
  "workspaces": [
    {
      "id": "workspace-virtualpytest",
      "name": "VirtualPyTest API",
      "postmanApiKey": "PMAK-xxx",
      "workspaceId": "postman-workspace-id",
      "teamId": "postman-team-id",
      "description": "VirtualPyTest APIs"
    }
  ],
  "environments": [
    {
      "id": "env-dev-server",
      "name": "Development Server",
      "workspaceId": "workspace-virtualpytest",
      "variables": [
        { "key": "base_url", "value": "http://localhost:5109", "type": "default" },
        { "key": "team_id", "value": "7fdeb4bb-...", "type": "default" },
        { "key": "api_key", "value": "your-secret-key", "type": "secret" }
      ]
    },
    {
      "id": "env-dev-host",
      "name": "Development Host",
      "workspaceId": "workspace-virtualpytest",
      "variables": [
        { "key": "base_url", "value": "http://localhost:5000", "type": "default" },
        { "key": "host_name", "value": "host1", "type": "default" },
        { "key": "device_id", "value": "device1", "type": "default" },
        { "key": "userinterface", "value": "example_mobile", "type": "default" }
      ]
    }
  ]
}
```

### `postman_workspaces.json` (Legacy)

Kept for backward compatibility. Will be migrated to `postman_config.json` format.

## How It Works

### 1. User Flow

1. User selects a **Workspace** (e.g., "VirtualPyTest API")
2. User selects an **Environment** (e.g., "Development Server" or "Development Host")
3. User selects endpoints to test
4. System substitutes `{{variables}}` from environment and executes

### 2. Variable Substitution

Request path: `/server/userinterface/getAllUserInterfaces`

With environment:
```json
{
  "base_url": "http://localhost:5109",
  "team_id": "7fdeb4bb-..."
}
```

Result:
- URL: `http://localhost:5109/server/userinterface/getAllUserInterfaces?team_id=7fdeb4bb-...`

### 3. Environment Variable Format

Each variable has three properties:
- `key`: The variable name
- `value`: The variable value
- `type`: Either `"default"` (visible) or `"secret"` (masked with •••)

**Example:**
```json
{
  "key": "api_key",
  "value": "your-secret-key",
  "type": "secret"
}
```

### 4. Common Environment Variables

| Variable | Description | Example | Type |
|----------|-------------|---------|------|
| `base_url` | Base URL for API | `http://localhost:5109` | default |
| `api_key` | Bearer token for auth | `your-secret-key` | **secret** 🔒 |
| `team_id` | Team ID for multi-tenancy | `7fdeb4bb-...` | default |
| `host_name` | Host machine name | `host1` | default |
| `device_id` | Device identifier | `device1` | default |
| `userinterface` | UI name | `example_mobile` | default |

## Example: Multi-Environment Setup

```json
{
  "environments": [
    {
      "id": "env-local",
      "name": "Local Development",
      "variables": {
        "base_url": "http://localhost:5109",
        "team_id": "7fdeb4bb-..."
      }
    },
    {
      "id": "env-staging",
      "name": "Staging",
      "variables": {
        "base_url": "https://staging.virtualpytest.com",
        "api_key": "staging-key",
        "team_id": "7fdeb4bb-..."
      }
    },
    {
      "id": "env-prod",
      "name": "Production",
      "variables": {
        "base_url": "https://api.virtualpytest.com",
        "api_key": "prod-key",
        "team_id": "7fdeb4bb-..."
      }
    }
  ]
}
```

## UI Features

### Environment Variable Viewer

Click **"View Variables"** button to see all environment variables in a Postman-style modal:

| Variable | Value | Type |
|----------|-------|------|
| base_url | http://localhost:5109 | default |
| api_key | •••••••••••••••••••••••••••••••••••••••• | 🔒 secret |
| team_id | 7fdeb4bb-3639-4ec3-959f-b54769a219ce | default |

**Features:**
- ✅ **Secret masking**: Variables marked as `"secret"` are displayed as dots (•••)
- ✅ **Table view**: Clean table layout like Postman
- ✅ **Type indicators**: Visual badges showing variable type
- ✅ **Security icon**: 🔒 icon for secret variables

## Security

- ✅ **Postman API keys** are stored in config but **never exposed to frontend**
- ✅ **Secret variables** are masked in the UI with dots (•••••)
- ✅ **API keys** from environments are used in request headers
- ✅ All Postman API calls go through backend (`/server/postman/*`)
- ✅ Frontend only receives workspace/environment metadata

## Migration from Old Format

If you have `postman_workspaces.json`, create `postman_config.json`:

Old:
```json
[
  {
    "id": "workspace-virtualpytest",
    "apiKey": "PMAK-xxx",
    "workspaceId": "xxx"
  }
]
```

New:
```json
{
  "workspaces": [
    {
      "id": "workspace-virtualpytest",
      "postmanApiKey": "PMAK-xxx",
      "workspaceId": "xxx"
    }
  ],
  "environments": []
}
```

Both formats are supported for backward compatibility.

