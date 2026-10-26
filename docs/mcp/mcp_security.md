# MCP Security

**Last Updated**: 2026-03-17

This page explains how the MCP tools are kept from showing sensitive data, such as `.env` files, passwords, API keys, tokens and private keys. Three separate checks protect against this. A request has to pass all three, so one weak check does not open the door.

<div data-technical>

This document describes the security layers that protect VirtualPyTest MCP tools from exposing sensitive data such as `.env` files, credentials, API keys, tokens, and private keys.

</div>

---

## Architecture: defense in depth

<div data-technical>

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

</div>

The three layers are:

- **Layer 1, tool level.** The documentation tools hide dotfiles and sensitive files.
- **Layer 2, global gate.** Any request that mentions a sensitive word is refused before it runs.
- **Layer 3, the assistant itself.** The AI is told to refuse requests for secrets.

---

## Layer 1: tool-level filtering

The documentation tools hide sensitive files. They can list, read and search the docs, and they skip anything sensitive in all three.

<div data-technical>

**File**: `backend_server/src/mcp/tools/docs_tools.py`

The docs tools (`list_docs`, `read_doc`, `search_docs`) are the only MCP tools that read directly from the filesystem. All three methods filter sensitive content:

**Blocked patterns**

Any file or directory matching these patterns is silently excluded from listings and blocked from reading:

| Category | Patterns |
|----------|----------|
| **Dotfiles** | Any path component starting with `.` (e.g. `.env`, `.git`, `.ssh`, `.aws`) |
| **Env files** | `.env`, `.env.example`, `.env.local`, `.env.production` |
| **Credentials** | `credentials`, `secrets`, `token`, `private_key`, `id_rsa`, `id_ed25519` |
| **Key files** | `.pem`, `.key`, `.p12`, `.pfx` |
| **Config secrets** | `.npmrc`, `.pypirc`, `.docker` |

**Behavior per tool**

| Tool | Behavior |
|------|----------|
| `list_docs` | Sensitive files are **omitted** from the returned tree — the caller never sees them |
| `read_doc` | Returns `"Access denied: cannot read sensitive or hidden files"` |
| `search_docs` | Sensitive files are **skipped** during keyword search |

**Existing protections (unchanged)**

- **Path traversal blocked**: `..` sequences are stripped, resolved path must stay within `docs/`
- **File type restricted**: Only `.md` files are readable

</div>

---

## Layer 2: global MCP server gate

Before every tool call, the server scans the text in the request for sensitive words. If it finds one, the call is refused. This covers all 75+ tools, not just the docs tools.

<div data-technical>

**File**: `backend_server/src/mcp/mcp_server.py`

A regex-based interceptor runs **before every tool call**, scanning all string parameters for sensitive keywords. This protects **all 75+ tools**, not just docs.

**Blocked keywords (regex)**

```
.env  .aws  .ssh  .docker  .npmrc  .pypirc  .pem  .key  .p12  .pfx
private_key  secret_key  api_key  access_token  refresh_token
credentials.json  service_account  id_rsa  id_ed25519
password  passwd  .htpasswd  shadow
```

**Behavior**

- If any string parameter matches, the request is **rejected immediately** with:
  ```
  Access denied: requests involving sensitive files, credentials, or secrets are not permitted.
  ```
- A `SECURITY` warning is logged with the tool name and parameter keys (not values).
- The tool handler is **never called** — the block happens before execution.

**Why global?**

Future tools that accept file paths, queries, or free-text parameters are automatically protected without needing per-tool security code.

</div>

---

## Layer 3: system prompt

The AI assistant is told, in every conversation, never to reveal secrets. This catches requests that avoid the word filter but still ask for secrets.

<div data-technical>

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

**Why prompt-level?**

Even if a user crafts a prompt that avoids triggering the regex gate (e.g. "show me the file that configures database connections"), the LLM itself is instructed to refuse. This catches social engineering and indirect requests.

</div>

---

## Adding new sensitive patterns

Add a new word to one of the two lists, so the new pattern is blocked. Add it to the docs list and to the global gate.

<div data-technical>

**Tool-level (docs_tools.py)**

Add entries to the `SENSITIVE_PATTERNS` set:

```python
SENSITIVE_PATTERNS = {
    '.env', '.env.example', ...
    'your_new_pattern',  # Add here
}
```

**Global gate (mcp_server.py)**

Extend the `_SENSITIVE_KEYWORDS` regex:

```python
_SENSITIVE_KEYWORDS = re.compile(
    r'\.env|\.aws|...|your_new_pattern',
    re.IGNORECASE,
)
```

</div>

---

## Testing

To check the protection, try to read a secret file and search for secret words. Each attempt should be refused. Then ask the assistant for the `.env` file and confirm it says no.

<div data-technical>

**Verify docs tool filtering**

```python
# Should return Access denied
read_doc(path='.env')
read_doc(path='../.env')
read_doc(path='.git/config')

# Should omit dotfiles from results
list_docs()
search_docs(query='SECRET_KEY')
```

**Verify global gate**

```python
# Any tool with sensitive param should be blocked
handle_tool_call('search_docs', {'query': '.env'})
handle_tool_call('view_logs', {'grep': 'api_key'})
```

**Verify agent refusal**

```
User: "Show me the contents of the .env file"
Agent: "I cannot provide access to sensitive files or credentials."
```

</div>

---

## Related documentation

- [MCP Core — Bearer Token Authentication](mcp_core.md#-security)
- [MCP Core — Protected Endpoints](mcp_core.md#protected-endpoints)
