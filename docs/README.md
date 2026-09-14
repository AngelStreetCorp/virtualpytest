# VirtualPyTest Documentation

**Complete documentation for VirtualPyTest.**

Your one-stop resource for everything VirtualPyTest - from quick start to advanced topics.

---

## 🚀 Get Started

**[Get started](./get-started/README.md)** is the one entry point for installing: pick
[Docker](./get-started/docker.md) (one machine, one command), [one VM or a Proxmox fleet](./get-started/proxmox.md)
(native services), or the [developer setup](./get-started/local-dev.md). Then
[Supabase and authentication](./get-started/supabase.md), the
[configuration reference](./get-started/configuration.md) and
[branding](./get-started/branding.md).

Installers live under `setup/` (`setup/README.md` maps them); infrastructure configs
(Grafana dashboards, nginx examples) under `infra/`.

---

## 📖 Main Sections

### [Features](./features/README.md)
**Discover what VirtualPyTest can do.**

- [Unified Device Controller](./features/unified-controller.md) - One script, all devices
- [Visual Capture & Monitoring](./features/visual-capture.md) - See everything, miss nothing
- [AI-Powered Validation](./features/ai-validation.md) - Smart verification
- [Real-time Analytics](./features/analytics.md) - Grafana dashboards
- [Test Automation](./features/test-automation.md) - Low-code automation
- [Integrations](./features/integrations.md) - Connect external tools
- [Navigation Tree History](./features/navigation-tree-history.md) - Version control and restore for navigation trees
- [Navbar Visibility](./features/nav-visibility.md) - How navbar item visibility is controlled

---

### [User Guide](./user-guide/README.md)
**Learn how to use VirtualPyTest effectively.**

- Running tests and campaigns
- Device configuration
- Navigation trees
- Monitoring and alerts
- Best practices
- Troubleshooting

---

### [Technical Documentation](./technical/README.md)
**Understand the architecture and internals.**

- System architecture
- Component design
- AI systems
- MCP integration
- Development guides
- Deployment

---

### Security Reports
**Security analysis and vulnerability scanning.**

- Code security (Bandit)
- Dependency vulnerabilities (Safety & npm audit)
- Backend host, server, and frontend coverage
- Admin-only, in-app: **Docs → Security Reports** (`docs/security/README.md` for how to
  generate the reports locally)
- Automated scanning tools

---

### [API Reference](./api/README.md)
**Complete API documentation.**

- REST API endpoints
- OpenAPI specifications
- Authentication
- Python SDK
- Webhooks
- Integration examples

---

### Examples & Demos
**Learn by example.**

- Automation prompts
- Code examples
- Demo scenarios
- Best practices
- CI/CD integration

---

### [FAQ](./faq/README.md)
**Quick answers to common questions.**

- How does one script work for all devices?
- What devices are supported?
- How does AI validation work?
- How is VirtualPyTest different from commercial tools?
- Getting started and prerequisites

---

### [Integrations](./integrations/README.md)
**Connect to external tools.**

- JIRA integration
- Grafana dashboards
- CI/CD pipelines
- Cloud storage
- Custom integrations

---

## 🎯 Quick Links by Role

### For QA Engineers
1. [Get started](./get-started/README.md)
2. [Test Automation Features](./features/test-automation.md)
3. [User Guide](./user-guide/README.md)

### For Developers
1. [Technical Documentation](./technical/README.md)
2. [API Reference](./api/README.md)
3. [Architecture](./technical/architecture/architecture.md)

### For DevOps
1. [Get started](./get-started/README.md) — Docker / VM / Proxmox fleet
2. [Configuration reference](./get-started/configuration.md) and [Supabase & auth](./get-started/supabase.md)
3. Security Reports — admin-only, in-app: **Docs → Security Reports**
4. [Monitoring](./features/analytics.md)
5. [Integrations](./integrations/README.md)

### For Managers
1. [Features Overview](./features/README.md)
2. [Get started](./get-started/README.md)
3. [Analytics](./features/analytics.md)
4. [User Guide](./user-guide/README.md)

---

## 🔍 Search by Topic

### Device Control
- [Unified Controller](./features/unified-controller.md)
- [User Guide - Device Management](./user-guide/README.md#device-management)
- [Controller Creation Guide](./technical/architecture/CONTROLLER_CREATION_GUIDE.md)

### Visual Testing
- [Visual Capture](./features/visual-capture.md)
- [AI Validation](./features/ai-validation.md)
- User Guide - Monitoring

### Test Automation
- [Test Automation Features](./features/test-automation.md)
- Examples
- [User Guide - Running Tests](./user-guide/running-tests.md)

### Analytics & Monitoring
- [Analytics Features](./features/analytics.md)
- Grafana Integration
- User Guide - Monitoring

### Integrations
- [Integration Features](./features/integrations.md)
- JIRA Integration
- [API Reference](./api/README.md)

---

## 📱 Supported Platforms

VirtualPyTest works with:

- **Android** - TV, mobile, tablets
- **iOS** - iPhone, iPad, Apple TV
- **Set-Top Boxes** - IR and network controlled
- **Smart TVs** - Samsung, LG, etc.
- **Web** - Browser automation
- **Desktop** - Windows, macOS, Linux

---

## 💰 Why VirtualPyTest?

| Feature | VirtualPyTest | Commercial Tools |
| :--- | :---: | :---: |
| Cost | **Free** | $50k+/year |
| Platform Support | All | Limited |
| Customization | Full | Vendor Locked |
| Monitoring | Built-in | Extra Cost |
| AI Validation | Included | Extra Cost |

---

## 🆘 Need Help?

### Documentation
- Browse sections above
- Check [FAQ](./faq/README.md) for quick answers
- Check [User Guide](./user-guide/README.md)
- See Examples
- Read [Technical Docs](./technical/README.md)

### Community
- 💬 [Ask Questions](https://github.com/AngelStreetCorp/virtualpytest/discussions)
- 🐛 [Report Bugs](https://github.com/AngelStreetCorp/virtualpytest/issues)
- 🎯 [Request Features](https://github.com/AngelStreetCorp/virtualpytest/issues/new)

### Troubleshooting
- [Troubleshooting Guide](./user-guide/troubleshooting.md)
- [Common Issues](./user-guide/README.md#need-help)
- [GitHub Issues](https://github.com/AngelStreetCorp/virtualpytest/issues)

---

## 🗺️ Documentation Structure

```
docs/
├── README.md (this file) · INDEX.md (every file, one line each)
├── get-started/      README.md (chooser) · docker.md · proxmox.md · local-dev.md
│                     supabase.md · configuration.md · hardware.md · emulators.md
│                     cloud-setup.md · branding.md · ci_cd.md
├── user-guide/       getting-started.md · running-tests.md · writing-scripts.md · troubleshooting.md
├── features/         one page per capability (+ requirements-management.md)
├── faq/              README.md
├── technical/        architecture, testcase model, MCP, dev guides
├── api/              REST reference, OpenAPI specs
├── integrations/     external tools
├── release_note/     what shipped · bugs/ the bug tracker
└── security/         how the security reports are generated
```

---

## 🔄 Recently Updated

- 🚀 [Get started](./get-started/README.md) — one entry point; Docker, one-VM and Proxmox-fleet
  installs rewritten against the scripts (September 2026)
- ⚙️ [Configuration reference](./get-started/configuration.md) — every variable and port
- 🔐 [Supabase and authentication](./get-started/supabase.md) — open mode vs login

---

## 🤝 Contributing to Documentation

Found an error? Want to improve the docs?

1. 📝 Edit on GitHub
2. Submit a pull request
3. Help make the docs better!

---

**Ready to get started?**  
➡️ [Get started](./get-started/README.md)  
➡️ [Features Overview](./features/README.md)  
➡️ [User Guide](./user-guide/README.md)
