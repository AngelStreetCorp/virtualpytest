# Integrations

**Connect VirtualPyTest to the other tools you already use.**

Each guide explains one connection.

---

## Available Integrations

### Postman API collections

Try the API from Postman.

**Workspace:** [VirtualPyTest on Postman](https://martian-zodiac-279215.postman.co/workspace/virtualpytest~4e7a465c-a542-4440-8903-48787f03942a)\
**Guide:** [Postman integration](postman.md) · [API coverage and sync](../api/COVERAGE.md)

<div data-technical>

You can also browse the collections inside the app, if your account has the Postman view permission.

The public Postman workspace has curated Server collections plus generated Server and Host route lists. The collections are maintained from the OpenAPI specs and cover each registered route and method pair. The shared workspace ID is public. Its Postman API key stays on the backend server. Permission: `plugins.postman:view`.

</div>

### User provisioning (create users, reset passwords)

Add users from your own system with one web call. The user gets the same password in **VirtualPyTest and Grafana**.

<div data-technical>

Plain HTTP and JSON. It works from any language that can send an HTTPS request.

</div>

**Guide:** [user-provisioning.md](user-provisioning.md)

---

### Zammad (support tickets)

Users send a support ticket from **Settings -> Open a ticket**. It goes to your Zammad helpdesk.

<div data-technical>

The ticket carries the version, server, team and page.

</div>

**Guide:** [zammad-setup.md](zammad-setup.md)

---

### JIRA

See and filter your JIRA tickets inside VirtualPyTest. It does not create tickets.

<div data-technical>

You can connect more than one JIRA site. Filter by status, see quick counts and open a ticket in JIRA with one click.

</div>

<div data-technical>

Each JIRA instance has its own API token, stored server-side and never in the browser. Read-only.

</div>

**Setup guide:** [jira-setup.md](jira-setup.md)

---

### Slack

Copies your AI Agent conversations into a Slack channel, one thread each.

<div data-technical>

One-way sync only: VirtualPyTest posts to Slack, and nothing comes back.

</div>

**Setup guide:** [slack-setup.md](slack-setup.md)

---

### GitHub Actions (CI/CD)

Start and follow GitHub Actions runs from VirtualPyTest.

<div data-technical>

The results are shown on a Grafana dashboard.

</div>

<div data-technical>

A dedicated CI/CD feature. Runs use self-hosted or GitHub-hosted runners. Results are stored in their own database.

</div>

**Details:** [CI/CD Feature](../features/cicd.md)

---

### Grafana

Ready-made dashboards for device health, test results and KPIs.

<div data-technical>

You do not need to set up Grafana yourself.

</div>

<div data-technical>

Built-in dashboards for KPIs, device health and test analytics. No separate Grafana setup is required.

</div>

**Details:** [Features - Analytics](../features/analytics.md)

---

### Cloud device farms (Sauce Labs, BrowserStack)

Rent a cloud phone and control it like one on your desk. Sauce Labs works fully. BrowserStack needs a build you upload.

<div data-technical>

Same remote panel, navigation trees, scripts and reports as a local device. Sauce Labs is complete. BrowserStack runs sessions against an uploaded build. LambdaTest sits behind the same provider seam but has not been run against a real account.

</div>

**Guide:** [device-farms.md](device-farms.md)

---

### Cloudflare R2 (capture storage)

Screenshots and videos are stored in Cloudflare R2, set up at deploy time.

<div data-technical>

Cloudflare R2 is S3-compatible. It is configured at deploy time.

</div>

**Setup:** [Get Started - Cloud Setup](../get-started/cloud-setup.md)

---

## Planned

These are not built yet. Test management, CI, chat, monitoring and cloud storage tools are on the list.

You can already run VirtualPyTest from any CI system as a plain command.

<div data-technical>

Planned: LambdaTest; TestRail, Zephyr, qTest, PractiTest; Jenkins, GitLab CI, Azure DevOps, CircleCI; Microsoft Teams, Discord, Mattermost; Datadog, New Relic, Prometheus; AWS S3, Google Cloud Storage, Azure Blob Storage. Run VirtualPyTest from a CI system with a shell step, for example `python test_scripts/validation.py`.

</div>

Want one sooner? [Open a feature request](https://github.com/AngelStreetCorp/virtualpytest/issues/new?labels=integration).

---

## Related Documentation

- **[Features - Integrations](../features/integrations.md)**: what integrations can do
- **[API Reference](../api/README.md)**: the REST API
- **[User Guide](../user-guide/README.md)**: using integrations

---

<div data-technical>

**Ready to connect VirtualPyTest?**

- [Cloud Device Farms Guide](device-farms.md)
- [User Provisioning Guide](user-provisioning.md)
- [JIRA Integration Guide](jira-setup.md)
- [Zammad setup (support tickets)](zammad-setup.md)
- [Slack Integration Guide](slack-setup.md)
- [Postman Integration Guide](postman.md)

</div>
