# Real-time Analytics & Monitoring

**Know what is happening, as it happens.**

Live dashboards show how your tests, devices and systems are doing. They are built with Grafana.

<div data-technical>

Grafana dashboards, backed by the same Supabase database VirtualPyTest writes to, give real-time insight into test execution, device health and system performance.

</div>

---

## Why it matters

Without numbers, testing is guesswork.

<div data-technical>

- You cannot see test trends.
- Device problems are found too late.
- Slow performance stays hidden.
- It is hard to show management what testing is worth.

</div>

---

## Two places to look

Each place answers a different kind of question.

| | **Monitoring → Analytics** (in the app) | **Grafana** |
|---|---|---|
| For | The basics, at a glance | Anything more |
| Shape | 7 tabs of charts | ~30 dashboards |
| Filters | None in v1 | Full |
| Drill-down | No, it links out to Grafana | Yes |
| Cost to open | One cached section, < 150 ms | A separate login and warm-up |

The in-app page answers simple questions, such as:

- How many robots and devices there are, and how many are up, down or having service issues
- Incidents and alerts over time
- The test pass rate and the busiest scripts
- Disk, memory and CPU for each machine
- Lines of code, bugs by severity, and releases, read from the code repository

It does not replace Grafana. Each tab has a "Grafana ↗" link to a deeper dashboard. Design notes and deploy steps are in [TASK-20](../tasks/TASK-20-monitoring-analytics.md).

---

## How it works

<div data-technical>

- Test executions land in the `test_executions` table (`setup/db/schema/003_test_execution_tables.sql`).
- Navigation and system metrics are tracked via `shared/src/lib/database/navigation_metrics_db.py` and `system_metrics_db.py`.
- Grafana runs as its own Docker Compose service (`setup/docker/grafana/` / the `grafana` service in `setup/docker/`), with a PostgreSQL datasource pointed at that same Supabase database. It queries the data directly. It does not receive it via a push or webhook.
- About 30 pre-built dashboards ship under `infra/monitoring/grafana/dashboards/` (for example `campaign-results.json`, `device-occupancy.json`, `navigation-metrics.json`, `system-server-monitoring.json`, `vpt-fleet-health.json`).
- The in-app **Monitoring → Analytics** page reads six aggregate views created by `setup/db/schema/048_analytics_views.sql` through `GET /server/analytics/<section>`, one route per tab. Two of those views are materialized and refreshed every 15 minutes by `pg_cron`, because the capture-availability rollup costs 1382 ms computed live. The Project tab reads no database at all: it reads `frontend/public/analytics/project.json`, written by frontend prebuild step 6.

</div>

---

## Accessing dashboards

There are two ways to view the dashboards.

#### 1. VirtualPyTest web interface

Go to **Plugins → Grafana**. The dashboard appears inside the page. You log in to Grafana as usual.

<div data-technical>

The dashboard renders in an `<iframe>` (`frontend/src/pages/GrafanaDashboard.tsx`) pointed at your Grafana instance. This is a plain embed, not single sign-on. Log into Grafana normally, or run it with anonymous-viewer mode enabled (`GF_AUTH_ANONYMOUS_ENABLED`, off by default).

</div>

#### 2. Direct Grafana access

Open Grafana in your browser at its local address. Change the default login before you use this in production.

<div data-technical>

Local address: `http://localhost:3001`. Default credentials from the standalone launch script: `admin` / `admin123` — **change this in production**.

</div>

---

## Custom metrics

To track your own number, write it to a table that Grafana can read. Then add a Grafana panel that reads from it.

<div data-technical>

There is no dedicated `MetricsCollector` or `AnalyticsExporter` SDK. Add rows to an existing table via the relevant `shared/src/lib/database/*.py` module, or create your own table (see `setup/db/schema/*.sql` for the pattern) and add a Grafana panel with a raw SQL query against it.

</div>

---

## Alerting

Set up alerts in Grafana itself, using its contact points and notification policies.

<div data-technical>

Grafana's own alerting (contact points, notification policies) works once you point VirtualPyTest at a live Grafana instance. VirtualPyTest does not add a separate alerting layer, a YAML alert-rule format, or a PagerDuty or SMS integration on top of it.

</div>

---

## Data export

To export a Grafana panel, use its built-in export to CSV or PNG. For anything bigger, query the database directly.

<div data-technical>

Use Grafana's built-in panel export (CSV, PNG), or query the Supabase database directly (REST API or `psql`) for anything more involved. There is no built-in `AnalyticsExporter` class for CSV, Excel or JSON export.

</div>

---

## Integration with CI/CD

The [CI/CD feature](./cicd.md) keeps its own results and has a Grafana dashboard for them.

<div data-technical>

CI/CD stores its results in a dedicated `cicd` schema and ships a Grafana dashboard (`features/cicd/grafana/cicd-quality.json`) for it. There is no generic Jenkins or webhook mechanism.

</div>

---

## Next Steps

- [Test Automation](./test-automation.md): generate the metrics
- [CI/CD](./cicd.md)
- [Integrations](../integrations/README.md): connect other tools

---

**Ready to see your testing metrics?**
[Get Started](../get-started/README.md)
