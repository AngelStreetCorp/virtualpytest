"""
Agent Definitions

NOTE: Python agent classes have been removed.
The system uses YAML-driven agents loaded from registry/templates/*.yaml

Skill-Based Architecture (v2.0):
- assistant.yaml (Atlas) - Interactive QA assistant, loads skills dynamically
- monitor.yaml (Guardian) - Autonomous monitor for system events
- analyzer.yaml (Sherlock) - Result validation and false positive detection

Skills are loaded from skills/definitions/*.yaml:
- exploration-mobile, exploration-web, exploration-stb
- execution, design, monitoring-read
- incident-response, health-check, alert-triage
- result-validation, false-positive-detection, report-generation

See core/manager.py for the QAManagerAgent that loads and runs YAML configs.
"""

__all__ = []
