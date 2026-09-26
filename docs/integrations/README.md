# Integrations

**Connect VirtualPyTest to external tools and services.**

Integration guides for third-party tools, services, and platforms.

---

## Available Integrations

### 📬 Postman API collections

Browse and test the published VirtualPyTest REST API collections. The public Postman workspace
contains curated Server collections plus generated Server and Host route inventories; it is
maintained from the OpenAPI specs and covers registered route/method pairs.

**Workspace:** [VirtualPyTest on Postman](https://martian-zodiac-279215.postman.co/workspace/virtualpytest~4e7a465c-a542-4440-8903-48787f03942a)\
**Guide:** [Postman integration](postman.md) · [API coverage and sync](../api/COVERAGE.md)

VirtualPyTest users can browse it from the app with the `plugins.postman:view` permission. The
shared workspace ID is public; its Postman API key stays on the backend server.

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

### 📱 Cloud device farms (Sauce Labs, BrowserStack)

Lease a phone from a vendor's cloud and drive it exactly like one on a desk — same remote
panel, same navigation trees, same scripts, same reports. Sauce Labs is complete;
BrowserStack runs sessions against an uploaded build. LambdaTest sits behind the same
provider seam but has not been run against a real account.

**Guide:** [device-farms.md](device-farms.md)

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

**Device farms:** LambdaTest (session half written, never run against an account)

**Test Management:** TestRail · Zephyr · qTest · PractiTest

**CI/CD:** Jenkins · GitLab CI · Azure DevOps · CircleCI

**Communication:** Microsoft Teams · Discord · Mattermost

**Monitoring:** Datadog · New Relic · Prometheus

**Cloud Storage:** AWS S3 · Google Cloud Storage · Azure Blob Storage

Want one of these sooner? [Open a feature request](https://github.com/AngelStreetCorp/virtualpytest/issues/new?labels=integration).

---

## Related Documentation

- **[Features - Integrations](../features/integrations.md)** - Integration capabilities
- **[API Reference](../api/README.md)** - REST API documentation
- **[User Guide](../user-guide/README.md)** - Using integrations

---

**Ready to connect VirtualPyTest?**

- [Cloud Device Farms Guide](device-farms.md)
- [User Provisioning Guide](user-provisioning.md) — the one integration with no card on the grid, because it is an API rather than a product
- [JIRA Integration Guide](jira-setup.md)
- [Slack Integration Guide](slack-setup.md)
- [Postman Integration Guide](postman.md)
