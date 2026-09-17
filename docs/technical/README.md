# Technical Documentation

**Deep dive into VirtualPyTest architecture and internals.**

Comprehensive technical documentation for developers, architects, and advanced users.

---

## 📐 Architecture

### System Architecture

**[Architecture Overview](./architecture/architecture.md)**

High-level system design and component interaction.

**Components:**
- **[Backend Server](./architecture/components/backend-server.md)** - API server, test orchestration
- **[Backend Host](./architecture/components/backend-host.md)** - Device control, hardware interface
- **[Frontend](./architecture/components/frontend.md)** - React web interface
- **[Shared](./architecture/components/shared.md)** - Common libraries and utilities

---

### Core Systems

**Navigation & Pathfinding:**
- **[Navigation System](./architecture/navigation.md)** - Navigation tree architecture
- **[Navigation Metrics](./architecture/navigation_metrics.md)** - Performance tracking
- **[Node & Edges Metrics](./architecture/node_edges_metrics.md)** - Graph analytics

**Controllers:**
- **[Controller Creation Guide](./architecture/CONTROLLER_CREATION_GUIDE.md)** - Build custom controllers
- **[Direct Python Controller Usage](./architecture/DIRECT_PYTHON_CONTROLLER_USAGE.md)** - Use controllers in scripts

**Workflows:**
- **[Orchestrator Workflow](./architecture/ORCHESTRATOR_WORKFLOW.md)** - Test execution orchestration

---

### Infrastructure

**Deployment:**
- **[Deployment Guide](./architecture/deployment.md)** - Production deployment

**Storage:**
- **[Storage - Audio](./architecture/storage-audio.md)** - Audio file management
- **[Storage - Hot RAM](./architecture/storage-hot-ram.md)** - In-memory caching

**Integrations:**
- **[Appium Remote Implementation](./architecture/APPIUM_REMOTE_IMPLEMENTATION.md)** - Mobile automation

**Optional features:**
- **[Features](./FEATURES.md)** - How optional features are packaged, enabled, disabled and tested (`features/<name>/`)
- **[Mobile App & Phone as a Device](./MOBILE_APP.md)** - Slot provisioning, pairing, permissions, reachability, troubleshooting for `phone_agent`

**Monitoring:**
- **[Incidents](./architecture/incidents.md)** - Incident management system

---

## 🤖 AI Systems

### AI Services

**AI-Powered Tools:**
- **[Tree Creation](./ai/tree-creation.md)** - AI-generated navigation trees
- **[Exploration](./ai/exploration.md)** - AI-driven app exploration
- **[Builder](./ai/builder.md)** - AI test generation
- **[Detector](./ai/detector.md)** - AI content detection

---

## 🔌 MCP (Model Context Protocol)

**[MCP Overview](../mcp/README.md)**

VirtualPyTest's MCP integration provides AI-powered tools for test automation.

### MCP Tools

**Core:**
- **[MCP Core](../mcp/mcp_core.md)** - Core MCP functionality
- **[MCP Playground](../mcp/mcp_playground.md)** - Interactive MCP testing

**Test Management:**
- **[Test Case Tools](../mcp/mcp_tools_testcase.md)** - Test case operations
- **[Script Tools](../mcp/mcp_tools_script.md)** - Script management
- **[Requirements Tools](../mcp/mcp_tools_requirements.md)** - Requirements management

**Navigation:**
- **[Navigation Tools](../mcp/mcp_tools_navigation.md)** - Navigation tree operations
- **[Tree Tools](../mcp/mcp_tools_tree.md)** - Tree manipulation
- **[UI Tools](../mcp/mcp_tools_userinterface.md)** - UI interface management

**Execution:**
- **[Action Tools](../mcp/mcp_tools_action.md)** - Test actions
- **[Control Tools](../mcp/mcp_tools_control.md)** - Device control
- **[Verification Tools](../mcp/mcp_tools_verification.md)** - Result verification

**AI Services:**
- **[AI Tools](../mcp/mcp_tools_ai.md)** - AI-powered analysis
- **[Exploration Tools](../mcp/mcp_tools_exploration.md)** - AI exploration
- **[Screenshot Tools](../mcp/mcp_tools_screenshot.md)** - Screenshot analysis

---

## 🗺️ Documentation Map

### By Role

**For Architects:**
- System architecture
- Component design
- Integration patterns
- Deployment architecture

**For Backend Developers:**
- Backend Server architecture
- Backend Host architecture
- API design
- Database schema

**For Frontend Developers:**
- Frontend architecture
- Component structure
- State management
- UI/UX patterns

**For DevOps:**
- Deployment guide
- Infrastructure setup
- Monitoring integration
- Performance optimization

**For AI/ML Engineers:**
- AI systems overview
- MCP integration
- Model integration
- AI service architecture

---

## 🔍 Quick Reference

### Common Tasks

**Adding a new device controller:**
→ [Controller Creation Guide](./architecture/CONTROLLER_CREATION_GUIDE.md)

**Understanding navigation:**
→ [Navigation System](./architecture/navigation.md)

**Deploying to production:**
→ [Deployment Guide](./architecture/deployment.md)

**Using MCP tools:**
→ [MCP README](../mcp/README.md)

---

## 📚 Related Documentation

- **[Features](../features/README.md)** - What VirtualPyTest can do
- **[User Guide](../user-guide/README.md)** - How to use VirtualPyTest
- **[API Reference](../api/README.md)** - API documentation
- **[Get Started](../get-started/README.md)** - Installation

---

## 🤝 Contributing

Want to contribute to VirtualPyTest?

1. Read the architecture docs
2. Follow the patterns in existing code
3. Submit a pull request!

Contributor-only notes (naming conventions, z-index registry, undo/redo internals,
detection design) live in `docs/technical/dev/` in the repository — they are
deliberately not published to the documentation site.

---

## 🆘 Support

- 💬 [Technical Discussions](https://github.com/AngelStreetCorp/virtualpytest/discussions)
- 🐛 [Report Issues](https://github.com/AngelStreetCorp/virtualpytest/issues)
- 📖 [Architecture Questions](https://github.com/AngelStreetCorp/virtualpytest/discussions/categories/architecture)

---

**Ready to dive deep?**  
➡️ [System Architecture](./architecture/architecture.md)  
➡️ [MCP Overview](../mcp/README.md)  
➡️ [AI Systems](./ai/builder.md)

