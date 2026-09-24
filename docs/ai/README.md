# AI agent workflow

This guide is for an external AI agent operating a running VirtualPyTest
deployment. The agent-facing interfaces are:

- MCP over JSON-RPC at `/server/mcp`.
- The documented REST API under `/server/*`, including script execution.

The MCP server requires the deployment's `MCP_SECRET_KEY` as a bearer token.
The standard REST endpoints use the deployment's configured authentication
mode; in protected deployments send the configured JWT bearer token.

## MCP: connect, act, and verify

An agent should discover available tools from the connected server rather than
assuming every device supports the same actions. `take_control` is required
before device operations and `release_control` should be called when complete.

The following example uses the HTTP JSON-RPC transport directly:

```bash
set -euo pipefail

: "${VPT_BASE_URL:?Set VPT_BASE_URL}"
: "${MCP_SECRET_KEY:?Set MCP_SECRET_KEY}"
: "${VPT_HOST_NAME:?Set VPT_HOST_NAME}"
: "${VPT_DEVICE_ID:?Set VPT_DEVICE_ID}"

mcp_call() {
  curl --fail-with-body --silent --show-error \
    --request POST "$VPT_BASE_URL/server/mcp" \
    --header "Authorization: Bearer $MCP_SECRET_KEY" \
    --header 'Content-Type: application/json' \
    --data "$1"
}

# Initialize, then discover tools and their input schemas.
mcp_call '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | jq .
mcp_call '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' > tools.json
jq '.result.tools[] | {name, inputSchema}' tools.json

# Take exclusive control before device operations.
mcp_call "$(jq -n --arg host "$VPT_HOST_NAME" --arg device "$VPT_DEVICE_ID" \
  '{jsonrpc:"2.0",id:3,method:"tools/call",params:{name:"take_control",arguments:{host_name:$host,device_id:$device}}}')" | jq .

# Inspect supported actions, perform one action, and request a screenshot.
mcp_call "$(jq -n --arg host "$VPT_HOST_NAME" --arg device "$VPT_DEVICE_ID" \
  '{jsonrpc:"2.0",id:4,method:"tools/call",params:{name:"list_actions",arguments:{host_name:$host,device_id:$device}}}')" | jq .
mcp_call "$(jq -n --arg host "$VPT_HOST_NAME" --arg device "$VPT_DEVICE_ID" \
  '{jsonrpc:"2.0",id:5,method:"tools/call",params:{name:"execute_device_action",arguments:{host_name:$host,device_id:$device,actions:[{command:"KEY_HOME"}],include_screenshot:true}}}')" | jq .
mcp_call "$(jq -n --arg host "$VPT_HOST_NAME" --arg device "$VPT_DEVICE_ID" \
  '{jsonrpc:"2.0",id:6,method:"tools/call",params:{name:"capture_screenshot",arguments:{host_name:$host,device_id:$device,include_ui_dump:true}}}')" > screen.json
jq . screen.json

# Evaluate the screenshot/UI dump against the expected state, then release.
mcp_call "$(jq -n --arg host "$VPT_HOST_NAME" --arg device "$VPT_DEVICE_ID" \
  '{jsonrpc:"2.0",id:7,method:"tools/call",params:{name:"release_control",arguments:{host_name:$host,device_id:$device}}}')" | jq .
```

For a navigation-tree assertion, use `verify_node` with `node_label` and
`userinterface_name`; set `include_screenshot` when evidence should be
returned. For a lower-level visual check, retain the result of
`capture_screenshot` and evaluate its screenshot URL or UI dump.

Operational rules:

- Confirm host and device identity before taking control.
- Use `list_actions` and tool schemas to select supported actions.
- Verify after every state-changing action.
- Preserve request IDs, tool responses, screenshots, and verification results.
- Release control on success, failure, timeout, or cancellation.
- Keep `MCP_SECRET_KEY` out of prompts, logs, screenshots, and CI output.

The complete generated reference is in [`docs/mcp/README.md`](../mcp/README.md).

For operators reviewing visitor questions, AI conversations, or website
traffic, see the [AI logs and review runbook](logs.md).

## REST: CI/CD script execution

The REST API executes a script asynchronously. The `POST` response returns a
`task_id`; poll `GET /server/script/status/{task_id}` until the task reaches
`completed` or `failed`.

```bash
set -euo pipefail
: "${VPT_BASE_URL:?Set VPT_BASE_URL}"
: "${VPT_TOKEN:?Set VPT_TOKEN}"
: "${VPT_HOST_NAME:?Set VPT_HOST_NAME}"
: "${VPT_DEVICE_ID:?Set VPT_DEVICE_ID}"
: "${VPT_SCRIPT_NAME:?Set VPT_SCRIPT_NAME}"

run_json="$(curl --fail-with-body --silent --show-error \
  --request POST "$VPT_BASE_URL/server/script/execute" \
  --header "Authorization: Bearer $VPT_TOKEN" \
  --header 'Content-Type: application/json' \
  --data "$(jq -n --arg host "$VPT_HOST_NAME" --arg device "$VPT_DEVICE_ID" \
    --arg script "$VPT_SCRIPT_NAME" --arg parameters "${VPT_SCRIPT_PARAMETERS:-}" \
    '{host_name:$host,device_id:$device,script_name:$script,parameters:$parameters}')")"

task_id="$(jq -r '.task_id' <<<"$run_json")"
test -n "$task_id" -a "$task_id" != null

while :; do
  status_json="$(curl --fail-with-body --silent --show-error \
    "$VPT_BASE_URL/server/script/status/$task_id" \
    --header "Authorization: Bearer $VPT_TOKEN")"
  status="$(jq -r '.task.status' <<<"$status_json")"
  case "$status" in
    completed) jq . <<<"$status_json"; exit 0 ;;
    failed) jq . <<<"$status_json"; exit 1 ;;
    pending|running) sleep "${VPT_POLL_SECONDS:-5}" ;;
    *) echo "Unexpected status: $status" >&2; jq . <<<"$status_json"; exit 2 ;;
  esac
done
```

Use [`docs/api/README.md`](../api/README.md) and the
[`server-script-management.yaml`](../api/specs/server-script-management.yaml)
contract when adding campaign or other API operations. Persist the task ID,
final response, screenshots, and report/evidence URLs as CI artifacts.
