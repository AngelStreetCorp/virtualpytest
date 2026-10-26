# User Guide

**Learn how to use VirtualPyTest effectively.**

New here? Start with "Getting Started". Each link below opens one topic.

---

## Quick Navigation

### Getting Started
- **[Install](../get-started/README.md)** - Docker, one VM, Proxmox fleet or developer setup
- **[Getting Started](./getting-started.md)** - Your first test once the UI is up

### Core Features
- **[Platform update](./platform-update.md)** - Update an install in seven steps
- **[Running Tests](./running-tests.md)** - Execute tests and campaigns
- **[Sharing a test report](./sharing-reports.md)** - An expiring link for someone without an account
- **[App languages](./app-languages.md)** - Use the app in English, French or German
- **[Report languages](./report-languages.md)** - Read reports in three languages
- **[Caption playback](./caption-playback.md)** - Watch a device 150 s behind live, with captions
- **Monitoring** - 24/7 device monitoring and alerts
- **[Grafana alerting](./grafana-alerting.md)** - Alerts on host health and incidents
- **[Requirements management](../features/requirements-management.md)** - Link requirements to tests
- **[Nintendo Switch](./nintendo-switch.md)** - Pair a Switch and drive it from the remote panel
- **[Support tickets](./support-tickets.md)** - Open a ticket from Settings
- **[Subtitle QA](./subtitle-qa.md)** - Check subtitles on a film
- **[Atlas Companion](./atlas-companion.md)** - See the real page next to Atlas's answer
- **[Custom pages](./custom-pages.md)** - Build a page from blocks, or ask Atlas to build it, and share it

<div data-technical>

Full descriptions, in order:

- **Platform update** - Update an install in seven guided steps (prerequisites, backup, bundle, deploy, migrations, testing, close) with a maintenance banner for users
- **Sharing a test report** - An expiring link (optional password) to one report, for someone without a VPT account
- **App languages** - Use the web app in English, French or German; change language and theme from Settings
- **Report languages** - Read a report in English, French or German; translate your own script's strings
- **Caption playback** - Watch a device 150 s behind live with machine captions; per-device profile, language picker, minutes that already have subtitles
- **Grafana alerting** - Email / Slack alerts on host health, incidents and test regressions
- **Requirements management** - Link requirements to tests, coverage
- **Nintendo Switch** - Pair a stock Switch as a Bluetooth Pro Controller and drive it from the remote panel
- **Support tickets** - Open a ticket from Settings, what each field means, the statuses you see
- **Subtitle QA** - Check subtitles on a film (missing, wrong, late, stuck, wrong language) from an .mkv or a live device

</div>

### Configuration
- **[Configuration reference](../get-started/configuration.md)** - Every variable and port
- **[Supabase and authentication](../get-started/supabase.md)** - Open mode vs login
- **[Free cloud starter](./free-cloud-starter.md)** - A showcase setup
- **[Who can do what](../agent/platform/ACCESS_MODEL.md)** - Users, roles and workspaces

<div data-technical>

Full descriptions, in order:

- **Configuration reference** - Every variable and port
- **Supabase and authentication** - Open mode vs login, cloud vs self-hosted
- **Free cloud starter** - Render, Supabase, Redis, and a Linux host for a showcase
- **Who can do what** - Tenants → teams → users → roles → workspaces → projects + AI config / provider / model / quota. Single source of truth.

</div>

### Best Practices
- **[Test Case Naming](../technical/testcase/testcase-naming.md)** - Naming conventions
- **[Test Case Templates](../technical/testcase/testcase-template.md)** - Reusable templates
- **[Navigation Graphs](../technical/testcase/testcase-graph.md)** - Build navigation trees

### Help
- **[Troubleshooting](./troubleshooting.md)** - Common issues and solutions

---

## Documentation by Topic

The topics below are listed in the technical details.

<div data-technical>

**Test Management.** Creating Tests: define test steps, add verifications, capture screenshots, handle errors. Running Tests: single test execution, campaign execution, parallel execution, scheduled execution. Test Results: view test reports, screenshot galleries, video playback, failure analysis.

**Device Management.** Device Configuration: add new devices, configure controllers (ADB, IR, Appium), set up video capture, power management. Device Monitoring: real-time status, connection monitoring, performance metrics, alert configuration.

**Navigation Trees.** Building Navigation Maps: define nodes (screens), set navigation paths, add verifications, connect nodes. Using Navigation: navigate to any node, automatic pathfinding, breadcrumb navigation, custom navigation logic.

**Monitoring & Alerts.** Setting Up Monitoring: video quality monitoring, black screen detection, freeze detection, subtitle validation. Alert Configuration: configure alert rules, set up notification channels (Slack, Email), define severity levels, alert escalation.

**Campaigns.** Campaign Creation: select test cases, choose devices, set execution order, configure retries. Campaign Scheduling: cron-based scheduling, recurring campaigns, one-time executions, campaign dependencies.

**Integrations.** JIRA Integration: sync test cases, create defects automatically, link requirements, update test status. Grafana Dashboards: access dashboards, create custom panels, set up alerts, export data.

</div>

---

## Learning Path

### For QA Engineers

1. **Start Here**: [Getting Started](./getting-started.md)
2. **Learn Navigation**: [Navigation Graphs](../technical/testcase/testcase-graph.md)
3. **Create Tests**: [Test Case Templates](../technical/testcase/testcase-template.md)
4. **Run Tests**: [Running Tests](./running-tests.md)
5. **Analyze Results**: Check test reports in web interface

### For DevOps Engineers

1. **Deploy**: [Installation Guide](../get-started/README.md)
2. **Configure**: [Configuration reference](../get-started/configuration.md)
3. **Monitor**: Monitoring
4. **Integrate**: [Integrations](../features/integrations.md)

### For Test Managers

1. **Overview**: [Features](../features/README.md)
2. **Plan**: [Requirements management](../features/requirements-management.md)
3. **Execute**: [Running Tests](./running-tests.md)
4. **Report**: Grafana Dashboards

---

## Tips & Tricks

### Productivity Tips

- Use **navigation trees** to avoid repeating navigation code
- Use **campaigns** for regression testing

<div data-technical>

- Create **reusable fixtures** for common setup and teardown
- Enable **automatic retries** for flaky tests
- Leverage **parallel execution** for faster results

</div>

### Best Practices

- Name test cases consistently ([naming guide](../technical/testcase/testcase-naming.md))
- Verify after every navigation

<div data-technical>

- Take screenshots at key points
- Use meaningful verification messages
- Keep tests independent and isolated

</div>

---

## Need Help?

### Common Issues

Check [Troubleshooting](./troubleshooting.md) for solutions to connection problems, test failures, performance issues and configuration errors.

### Get Support

- [Report a Bug](https://github.com/AngelStreetCorp/virtualpytest/issues)
- [Ask a Question](https://github.com/AngelStreetCorp/virtualpytest/discussions)
- [Technical Docs](../technical/README.md)
- [Feature Requests](https://github.com/AngelStreetCorp/virtualpytest/issues/new)

---

## Related Documentation

- **[Features](../features/README.md)** - What VirtualPyTest can do
- **[Get Started](../get-started/README.md)** - Installation and setup
- **[Technical Docs](../technical/README.md)** - Architecture and internals
- **[API Reference](../api/README.md)** - API documentation

---

**Ready to start testing?**  
[Getting Started Guide](./getting-started.md)
