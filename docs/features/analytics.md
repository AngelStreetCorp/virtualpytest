# 📊 Real-time Analytics & Monitoring

**Know what's happening. Every second.**

Grafana dashboards, backed by the same Supabase database VirtualPyTest writes to, give you
real-time insight into test execution, device health, and system performance.

---

## The Problem

Testing without metrics is flying blind:
- ❌ No visibility into test trends
- ❌ Device issues discovered too late
- ❌ Performance problems hidden
- ❌ Can't prove ROI to management

---

## How It Works

- Test executions land in the `test_executions` table (`setup/db/schema/003_test_execution_tables.sql`).
- Navigation and system metrics are tracked via `shared/src/lib/database/navigation_metrics_db.py`
  and `system_metrics_db.py`.
- Grafana runs as its own Docker Compose service (`setup/docker/grafana/` / the `grafana` service
  in `setup/docker/`), with a PostgreSQL datasource pointed at that same
  Supabase database — it queries the data directly, it does not receive it via a push/webhook.
- ~30 pre-built dashboards ship under `infra/monitoring/grafana/dashboards/` (e.g.
  `campaign-results.json`, `device-occupancy.json`, `navigation-metrics.json`,
  `system-server-monitoring.json`, `vpt-fleet-health.json`).

---

## Accessing Dashboards

Two ways to view dashboards:

#### 1. VirtualPyTest Web Interface
Navigate to **Plugins → Grafana** — the dashboard renders in an `<iframe>`
(`frontend/src/pages/GrafanaDashboard.tsx`) pointed at your Grafana instance. This is a plain
embed, not single sign-on — you either log into Grafana normally or run it with anonymous-viewer
mode enabled (`GF_AUTH_ANONYMOUS_ENABLED`, off by default).

#### 2. Direct Grafana Access
Open `http://localhost:3001`. Default credentials from the standalone launch script:
`admin` / `admin123` — **change this in production**.

---

## Custom Metrics

There is no dedicated `MetricsCollector`/`AnalyticsExporter` SDK. To track a custom metric, write
it to a table Grafana can query — either add rows to an existing metrics table via the relevant
`shared/src/lib/database/*.py` module, or create your own table (see
`setup/db/schema/*.sql` for the pattern) and add a Grafana panel with a raw SQL query against it.

---

## Alerting

Grafana's own alerting (contact points, notification policies) is available once you're pointed
at a live Grafana instance — VirtualPyTest doesn't add a separate alerting layer, YAML alert-rule
format, or PagerDuty/SMS integration on top of it. Configure alerts directly in Grafana against
the dashboards/queries above.

---

## Data Export

Use Grafana's built-in panel export (CSV, PNG) or query the Supabase database directly (REST API
or `psql`) for anything more involved — there is no built-in `AnalyticsExporter` class for
CSV/Excel/JSON export.

---

## Integration with CI/CD

The [CI/CD feature](./cicd.md) stores its own results in a
dedicated `cicd` schema and ships a Grafana dashboard (`features/cicd/grafana/cicd-quality.json`)
for it — that's the real CI/metrics integration path, not a generic Jenkins/webhook mechanism.

---

## Next Steps

- 📖 [Test Automation](./test-automation.md) - Generate the metrics
- 🔁 [CI/CD](./cicd.md)
- 🔌 [Integrations](../integrations/README.md) - Connect other tools

---

**Ready to see your testing metrics?**
➡️ [Get Started](../get-started/README.md)
