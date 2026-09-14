# Agent Testing Tools

Quick testing utilities to avoid rebuilding the entire server when developing agent skills.

## 🚀 Quick Start

### 1. Reload Skills (No Rebuild Required)

Instead of rebuilding everything, just reload skills from YAML:

```bash
# Using Python script
python scripts/test_agent.py --reload-skills

# Using shell script
./scripts/test_agent.sh reload

# Or via HTTP API
curl -X POST http://localhost:3000/server/skills/reload
```

### 2. Test Skill Changes

```bash
# Test if your skill YAML is valid
python scripts/test_agent.py --test-skill device-control

# Test skill matching
python scripts/test_agent.py --match-skill "swipe down on device1"

# List all skills
python scripts/test_agent.py --list-skills
```

### 3. Development Workflow

1. **Edit skill YAML** (e.g., `src/agent/skills/definitions/device-control.yaml`)
2. **Reload skills**: `python scripts/test_agent.py --reload-skills`
3. **Test immediately**: `python scripts/test_agent.py --test-skill device-control`
4. **Test matching**: `python scripts/test_agent.py --match-skill "your test message"`

## 📋 Available Commands

### Python Script (`test_agent.py`)

```bash
# Reload all skills from YAML
python scripts/test_agent.py --reload-skills

# List all skills with details
python scripts/test_agent.py --list-skills

# Test specific skill validity
python scripts/test_agent.py --test-skill <skill-name>

# Test skill matching against message
python scripts/test_agent.py --match-skill "<user message>"
```

### Shell Script (`test_agent.sh`)

Same commands but works without Python:

```bash
# Reload skills
./scripts/test_agent.sh reload

# List skills
./scripts/test_agent.sh list

# Test skill
./scripts/test_agent.sh test device-control

# Test matching
./scripts/test_agent.sh match "swipe down on device1"
```

### HTTP API Endpoints

All testing functionality is also available via REST API:

```bash
# Reload skills
curl -X POST http://localhost:3000/server/skills/reload

# List skills
curl http://localhost:3000/server/skills

# Get specific skill details
curl http://localhost:3000/server/skills/device-control

# Test skill validity
curl -X POST http://localhost:3000/server/skills/test/device-control

# Test skill matching
curl -X POST http://localhost:3000/server/skills/match \
  -H "Content-Type: application/json" \
  -d '{"message": "swipe down on device1"}'
```

## 🔧 Environment Variables

- `SERVER_URL`: Server URL (default: `http://localhost:3000`)

```bash
# Test against different server
SERVER_URL=http://localhost:8080 python scripts/test_agent.py --list-skills
```

## 🎯 What This Solves

**Before:** Edit skill → Rebuild entire server → Test → Repeat
**After:** Edit skill → Reload skills → Test immediately → Repeat

**Time savings:** From 2-5 minutes per test cycle to ~5 seconds!

## 🚨 Troubleshooting

### Server Not Running
```bash
# Start the server first
cd backend_server
python src/app.py
```

### Skills Not Loading
```bash
# Check skill YAML syntax
python -c "import yaml; yaml.safe_load(open('src/agent/skills/definitions/device-control.yaml'))"

# Check server logs for errors
tail -f logs/agent_conversations.log
```

### Network Issues
```bash
# Test basic connectivity
curl http://localhost:3000/server/skills

# Check server is running on correct port
netstat -tlnp | grep :3000
```

## 📚 Advanced Usage

### Integration with Development Workflow

Add to your shell aliases:

```bash
# ~/.bashrc or ~/.zshrc
alias reload-skills='python backend_server/scripts/test_agent.py --reload-skills'
alias test-skill='python backend_server/scripts/test_agent.py --test-skill'
alias match-skill='python backend_server/scripts/test_agent.py --match-skill'
```

Then use:
```bash
reload-skills
test-skill device-control
match-skill "your test message"
```

### CI/CD Integration

These endpoints can be used in automated testing:

```yaml
# Example GitHub Actions step
- name: Test Agent Skills
  run: |
    python backend_server/scripts/test_agent.py --reload-skills
    python backend_server/scripts/test_agent.py --test-skill device-control
    python backend_server/scripts/test_agent.py --match-skill "swipe down on device1"
```
