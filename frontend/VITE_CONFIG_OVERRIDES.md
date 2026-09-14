# Vite Configuration Overrides

This document explains how to customize Vite development server settings without modifying the tracked `vite.config.ts` file.

## Why Use Local Overrides?

When working with custom domains, network configurations, or environment-specific settings, you need to modify Vite's configuration. However, `vite.config.ts` is tracked by git, which means:

- ❌ Your changes get overwritten on `git pull`
- ❌ You create merge conflicts
- ❌ You might accidentally commit sensitive/local settings

The solution: **`vite.config.local.json`** (git-ignored)

## Quick Start

```bash
# 1. Copy the example file
cp vite.config.local.example.json vite.config.local.json

# 2. Edit with your custom settings
nano vite.config.local.json

# 3. Restart Vite dev server
npm run dev
```

## Available Overrides

### 1. `allowedHosts` - Custom Domains

Add custom domains that can access your Vite dev server:

```json
{
  "allowedHosts": [
    "your-domain.example.com",
    "192.168.50.100",
    "custom-domain.example.com"
  ]
}
```

**Use case**: Accessing Vite dev server from custom domains or IP addresses

### 2. `cspFrameAncestors` - Content Security Policy

Add additional frame-ancestors for iframe embedding:

```json
{
  "cspFrameAncestors": [
    "https://your-domain.example.com",
    "http://192.168.50.100:3000",
    "https://monitoring.example.com"
  ]
}
```

**Use case**: Embedding frontend in iframes from custom domains (Grafana, monitoring dashboards)

### 3. `corsOrigin` - CORS Configuration

Control CORS origin policy:

```json
{
  "corsOrigin": true  // Allow all origins (default)
}
```

Or restrict to specific origins:

```json
{
  "corsOrigin": [
    "http://localhost:5109",
    "https://your-domain.example.com"
  ]
}
```

**Use case**: Fine-grained CORS control for API requests

## Complete Example

```json
{
  "allowedHosts": [
    "your-domain.example.com",
    "192.168.50.100",
    "monitoring.internal.net"
  ],
  "cspFrameAncestors": [
    "https://your-domain.example.com",
    "http://192.168.50.100:3000"
  ],
  "corsOrigin": true
}
```

## How It Works

1. `vite.config.ts` loads `vite.config.local.json` if it exists
2. Settings from local file are **merged** with defaults
3. Your `allowedHosts` are **added** to the default list (not replaced)
4. Your `cspFrameAncestors` are **appended** to the default CSP policy

## Git Protection

✅ `vite.config.local.json` is in `.gitignore` - never committed
✅ `vite.config.local.example.json` is tracked - provides template
✅ Your custom settings survive `git pull` and branch switches

## Troubleshooting

### Changes not taking effect?

Restart the Vite dev server:
```bash
# Stop current server (Ctrl+C)
npm run dev
```

### Server still rejecting custom domain?

Check the console output when starting Vite:
```bash
npm run dev
```

Look for:
```
✅ Loaded local config overrides from vite.config.local.json
🔗 Server URL: http://localhost:5109
🔒 HTTPS: enabled
```

### File format errors?

Validate your JSON:
```bash
cat vite.config.local.json | jq .
```

## Advanced: Environment-Specific Configs

You can maintain multiple override files:

```bash
# Development
vite.config.local.json

# Staging
vite.config.staging.json

# Copy the appropriate one
cp vite.config.staging.json vite.config.local.json
```

## Related Files

- `vite.config.ts` - Main config (tracked in git)
- `vite.config.local.json` - Your overrides (git-ignored)
- `vite.config.local.example.json` - Template (tracked in git)
- `.env` - Environment variables (git-ignored)
- `.env.example` - Env template (tracked in git)
