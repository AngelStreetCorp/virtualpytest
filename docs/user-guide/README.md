# User Guide

**Learn how to use VirtualPyTest effectively.**

This guide covers everything you need to know to get the most out of VirtualPyTest, from basic operations to advanced features.

---

## 🎯 Quick Navigation

### Getting Started
- **[Install](../get-started/README.md)** - Docker, one VM, Proxmox fleet or developer setup
- **[Getting Started](./getting-started.md)** - Your first test once the UI is up

### Core Features
- **[Running Tests](./running-tests.md)** - Execute tests and campaigns
- **Monitoring** - 24/7 device monitoring and alerts
- **[Requirements management](../features/requirements-management.md)** - Link requirements to tests, coverage

### Configuration
- **[Configuration reference](../get-started/configuration.md)** - Every variable and port
- **[Supabase and authentication](../get-started/supabase.md)** - Open mode vs login, cloud vs self-hosted

### Best Practices
- **[Test Case Naming](../technical/testcase/testcase-naming.md)** - Naming conventions
- **[Test Case Templates](../technical/testcase/testcase-template.md)** - Reusable templates
- **[Navigation Graphs](../technical/testcase/testcase-graph.md)** - Build navigation trees

### Help
- **[Troubleshooting](./troubleshooting.md)** - Common issues and solutions

---

## 📚 Documentation by Topic

### Test Management

#### Creating Tests
Learn how to create effective test cases:
- Define test steps
- Add verifications
- Capture screenshots
- Handle errors

#### Running Tests
Execute tests on your devices:
- Single test execution
- Campaign execution
- Parallel execution
- Scheduled execution

#### Test Results
Understand and analyze results:
- View test reports
- Screenshot galleries
- Video playback
- Failure analysis

---

### Device Management

#### Device Configuration
Set up and configure your devices:
- Add new devices
- Configure controllers (ADB, IR, Appium)
- Set up video capture
- Power management

#### Device Monitoring
Keep track of device health:
- Real-time status
- Connection monitoring
- Performance metrics
- Alert configuration

---

### Navigation Trees

#### Building Navigation Maps
Create reusable navigation structures:
- Define nodes (screens)
- Set navigation paths
- Add verifications
- Connect nodes

#### Using Navigation
Navigate efficiently in tests:
- Navigate to any node
- Automatic pathfinding
- Breadcrumb navigation
- Custom navigation logic

---

### Monitoring & Alerts

#### Setting Up Monitoring
Configure continuous monitoring:
- Video quality monitoring
- Black screen detection
- Freeze detection
- Subtitle validation

#### Alert Configuration
Get notified when issues occur:
- Configure alert rules
- Set up notification channels (Slack, Email)
- Define severity levels
- Alert escalation

---

### Campaigns

#### Campaign Creation
Organize tests into campaigns:
- Select test cases
- Choose devices
- Set execution order
- Configure retries

#### Campaign Scheduling
Automate test execution:
- Cron-based scheduling
- Recurring campaigns
- One-time executions
- Campaign dependencies

---

### Integrations

#### JIRA Integration
Connect to JIRA for issue tracking:
- Sync test cases
- Create defects automatically
- Link requirements
- Update test status

#### Grafana Dashboards
View analytics and metrics:
- Access dashboards
- Create custom panels
- Set up alerts
- Export data

---

## 🎓 Learning Path

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

## 💡 Tips & Tricks

### Productivity Tips

- Use **navigation trees** to avoid repeating navigation code
- Create **reusable fixtures** for common setup and teardown
- Use **campaigns** for regression testing
- Enable **automatic retries** for flaky tests
- Leverage **parallel execution** for faster results

### Best Practices

- Name test cases consistently ([naming guide](../technical/testcase/testcase-naming.md))
- Verify after every navigation
- Take screenshots at key points
- Use meaningful verification messages
- Keep tests independent and isolated

---

## 🆘 Need Help?

### Common Issues

Check [Troubleshooting](./troubleshooting.md) for solutions to:
- Connection problems
- Test failures
- Performance issues
- Configuration errors

### Get Support

- 🐛 [Report a Bug](https://github.com/AngelStreetCorp/virtualpytest/issues)
- 💬 [Ask a Question](https://github.com/AngelStreetCorp/virtualpytest/discussions)
- 📖 [Technical Docs](../technical/README.md)
- 🎯 [Feature Requests](https://github.com/AngelStreetCorp/virtualpytest/issues/new)

---

## 📖 Related Documentation

- **[Features](../features/README.md)** - What VirtualPyTest can do
- **[Get Started](../get-started/README.md)** - Installation and setup
- **[Technical Docs](../technical/README.md)** - Architecture and internals
- **[API Reference](../api/README.md)** - API documentation

---

**Ready to start testing?**  
➡️ [Getting Started Guide](./getting-started.md)



