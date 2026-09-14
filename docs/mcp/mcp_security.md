# MCP Security

**Last Updated**: 2026-03-17

This document describes the security layers that protect VirtualPyTest MCP tools from exposing sensitive data such as `.env` files, credentials, API keys, tokens, and private keys.

---

## Architecture: Defense in Depth

Security is enforced at **three independent layers**. A request must pass all three to succeed — compromising one layer does not bypass the others.

```
User / LLM Prompt
        │
        ▼
┌──────────────────────────┐
│  Layer 3: System Prompt  │  Agent refuses to ask for secrets
│  (manager.py + skills)   │  before any tool is called
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  Layer 2: Global Gate    │  mcp_server.py scans ALL tool
│  (MCP Server)            │  params for sensitive keywords
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  Layer 1: Tool-Level     │  docs_tools.py filters dotfiles
│  (Individual tools)      │  and sensitive paths
└──────────────────────────┘
```

---

## Layer 1: Tool-Level Filtering

**File**: `backend_server/src/mcp/tools/docs_tools.py`

The docs tools (`list_docs`, `read_doc`, `search_docs`) are the only MCP tools that read directly from the filesystem. All three methods filter sensitive content:

### Blocked Patterns

Any file or directory matching these patterns is silently excluded from listings and blocked from reading:

| Category | Patterns |
|----------|----------|
| **Dotfiles** | Any path component starting with `.` (e.g. `.env`, `.git`, `.ssh`, `.aws`) |
| **Env files** | `.env`, `.env.example`, `.env.local`, `.env.production` |
| **Credentials** | `credentials`, `secrets`, `token`, `private_key`, `id_rsa`, `id_ed25519` |
| **Key files** | `.pem`, `.key`, `.p12`, `.pfx` |
| **Config secrets** | `.npmrc`, `.pypirc`, `.docker` |

### Behavior per Tool

| Tool | Behavior |
|------|----------|
| `list_docs` | Sensitive files are **omitted** from the returned tree — the caller never sees them |
| `read_doc` | Returns `"Access denied: cannot read sensitive or hidden files"` |
| `search_docs` | Sensitive files are **skipped** during keyword search |

### Existing Protections (unchanged)

- **Path traversal blocked**: `..` sequences are stripped, resolved path must stay within `docs/`
- **File type restricted**: Only `.md` files are readable

---

## Layer 2: Global MCP Server Gate

**File**: `backend_server/src/mcp/mcp_server.py`

A regex-based interceptor runs **before every tool call**, scanning all string parameters for sensitive keywords. This protects **all 75+ tools**, not just docs.

### Blocked Keywords (regex)

```
.env  .aws  .ssh  .docker  .npmrc  .pypirc  .pem  .key  .p12  .pfx
private_key  secret_key  api_key  access_token  refresh_token
credentials.json  service_account  id_rsa  id_ed25519
password  passwd  .htpasswd  shadow
```

### Behavior

- If any string parameter matches, the request is **rejected immediately** with:
  ```
  Access denied: requests involving sensitive files, credentials, or secrets are not permitted.
  ```
- A `SECURITY` warning is logged with the tool name and parameter keys (not values).
- The tool handler is **never called** — the block happens before execution.

### Why Global?

Future tools that accept file paths, queries, or free-text parameters are automatically protected without needing per-tool security code.

---

## Layer 3: System Prompt Injection

**Files**:
- `backend_server/src/agent/core/manager.py` (router + skill prompts)
- `backend_server/src/agent/skills/definitions/query-docs.yaml`

Every agent conversation — regardless of which skill is active — includes these absolute rules in the system prompt:

```
SECURITY — ABSOLUTE RULES (never override, even if the user insists):
- NEVER read, list, reveal, or summarise contents of .env files, dotfiles,
  credentials, API keys, tokens, passwords, secrets, or private keys
- If asked for secrets/tokens/credentials, respond:
  "I cannot provide access to sensitive files or credentials."
```

This instruction appears in:

| Prompt | When Active |
|--------|-------------|
| **Router prompt** | Every conversation, before any skill is loaded |
| **Skill prompt** | After any skill is loaded (all skills) |
| **query-docs skill** | Additional reinforcement in the docs-specific skill |

### Why Prompt-Level?

Even if a user crafts a prompt that avoids triggering the regex gate (e.g. "show me the file that configures database connections"), the LLM itself is instructed to refuse. This catches social engineering and indirect requests.

---

## Adding New Sensitive Patterns

### Tool-level (docs_tools.py)

Add entries to the `SENSITIVE_PATTERNS` set:

```python
SENSITIVE_PATTERNS = {
    '.env', '.env.example', ...
    'your_new_pattern',  # Add here
}
```

### Global gate (mcp_server.py)

Extend the `_SENSITIVE_KEYWORDS` regex:

```python
_SENSITIVE_KEYWORDS = re.compile(
    r'\.env|\.aws|...|your_new_pattern',
    re.IGNORECASE,
)
```

---

## Testing

### Verify docs tool filtering

```python
# Should return Access denied
read_doc(path='.env')
read_doc(path='../.env')
read_doc(path='.git/config')

# Should omit dotfiles from results
list_docs()
search_docs(query='SECRET_KEY')
```

### Verify global gate

```python
# Any tool with sensitive param should be blocked
handle_tool_call('search_docs', {'query': '.env'})
handle_tool_call('view_logs', {'grep': 'api_key'})
```

### Verify agent refusal

```
User: "Show me the contents of the .env file"
Agent: "I cannot provide access to sensitive files or credentials."
```

---

## Related Documentation

- [MCP Core — Bearer Token Authentication](mcp_core.md#-security)
- [MCP Core — Protected Endpoints](mcp_core.md#protected-endpoints)
