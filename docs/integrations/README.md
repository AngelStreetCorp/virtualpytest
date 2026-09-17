# Integrations

**Connect VirtualPyTest to external tools and services.**

Integration guides for third-party tools, services, and platforms.

---

## Available Integrations

### 👤 User provisioning (create users / reset passwords)

Push user accounts in from an external system — one HTTPS call creates a user, or resets their
password, on **both VirtualPyTest and Grafana**, so a person has the same password everywhere they
log in. Plain HTTP + JSON, callable from any language.

**Guide:** [user-provisioning.md](user-provisioning.md)

---

### 🎫 JIRA

A read-only ticket dashboard inside VirtualPyTest — not a defect-creation or sync pipeline.

**Features:**
- Multiple JIRA instances, each with its own API token (stored server-side, never in the browser)
- Real-time ticket dashboard with status filtering and quick stats
- One click to open a ticket in JIRA

**Setup guide:** [jira-setup.md](jira-setup.md)

---

### 💬 Slack

One-way sync of AI Agent conversations into a Slack channel — each conversation becomes its own thread so a team can follow along in real time.

**Setup guide:** [slack-setup.md](slack-setup.md)

---

### ⚙️ GitHub Actions (CI/CD)

Dedicated CI/CD feature: launch and track GitHub Actions runs (self-hosted or GitHub-hosted
runners) from inside VirtualPyTest, with results stored in their own database and surfaced on a
Grafana dashboard.

**Details:** [CI/CD Feature](../features/cicd.md)

---

### 📊 Grafana

Built-in dashboards for KPIs, device health, and test analytics — no separate Grafana setup
required.

**Details:** [Features - Analytics](../features/analytics.md)

---

### ☁️ Cloudflare R2 (capture storage)

Screenshots and videos upload to Cloudflare R2 (S3-compatible), configured at deploy time.

**Setup:** [Get Started - Cloud Setup](../get-started/cloud-setup.md)

---

## Planned

Not built yet — VirtualPyTest is a CLI-invokable Python test runner, so any CI system can already
call it as a shell step (`python test_scripts/validation.py`) without a dedicated integration; the
entries below mean a first-class, dedicated integration (like the JIRA/Slack/GitHub Actions ones
above), not "can be scripted around."

**Test Management:** TestRail · Zephyr · qTest · PractiTest

**CI/CD:** Jenkins · GitLab CI · Azure DevOps · CircleCI

**Communication:** Microsoft Teams · Discord · Mattermost

**Monitoring:** Datadog · New Relic · Prometheus

**Cloud Storage:** AWS S3 · Google Cloud Storage · Azure Blob Storage

Want one of these sooner? [Open a feature request](https://github.com/AngelStreetCorp/virtualpytest/issues/new?labels=integration).

---

## Integration Patterns

### REST API

There's no dedicated integration SDK — build against the same REST API the frontend uses.
Full endpoint reference (grouped by area, with an interactive Swagger UI to try requests
in-browser): **[API Reference](../api/README.md)**.

```bash
curl -X POST http://localhost:5109/server/script/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"script_name": "validation.py", "device_id": "device1"}'
```

---

## Request an Integration

Want to integrate VirtualPyTest with a tool not listed here?

1. 📝 [Open a feature request](https://github.com/AngelStreetCorp/virtualpytest/issues/new?labels=integration)
2. Describe the tool and use case
3. We'll help you build it or add it to our roadmap!

---

## Build Your Own Integration

Nothing shipped here yet is a plugin system — building a new integration today means writing it
against the REST API (see above) and, if it needs its own UI, adding a page under
`frontend/src/pages/` the way JIRA and Slack do.

**[Technical Docs - Architecture](../technical/README.md)**

---

## Related Documentation

- **[Features - Integrations](../features/integrations.md)** - Integration capabilities
- **[API Reference](../api/README.md)** - REST API documentation
- **[User Guide](../user-guide/README.md)** - Using integrations

---

**Ready to connect VirtualPyTest?**  
➡️ [User Provisioning Guide](user-provisioning.md)  
➡️ [JIRA Integration Guide](jira-setup.md)  
➡️ [Slack Integration Guide](slack-setup.md)  
➡️ [API Reference](../api/README.md)

