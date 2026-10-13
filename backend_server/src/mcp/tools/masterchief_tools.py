"""Masterchief propose tool (TASK-71 Part 7.4).

The only Atlas-facing masterchief entry point. It does NOT call the HTTP
routes (those reject the service API key by design — see
backend_server/src/routes/server_masterchief_routes.py::_refuse_service_key).
Instead it writes a `masterchief_audit` row directly with state='proposed',
and returns a card-shaped dict the front end renders as a confirm card.

The browser then calls `POST /server/masterchief/execute` with the user's
own JWT to confirm. The privilege holder is always a human browser, never
the model.

Trusted caller identity is injected by the bridge as private `_context_*`
keys (see backend_server/src/agent/core/tool_bridge.py). The tool reads
those, not model-supplied identity claims.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


# The bridge injects `_context_*` keys for tools in this set, exactly the
# same pattern as ANALYTICS_TOOL_NAMES.
MASTERCHIEF_PROPOSE_TOOL_NAMES = frozenset({
    "propose_masterchief_op",
})


class MasterchiefTools:
    """Atlas-facing propose tool. No api_client: writes the audit row
    directly via the server-side lib.
    """

    def __init__(self, api_client=None):
        # No api_client needed; we write to the DB directly.
        self._api = api_client

    def propose_masterchief_op(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Propose a masterchief op for the user to confirm. Does NOT execute.

        Atlas calls this when the user's request maps to a masterchief op
        (restart a service, read a journal, explain a rollout, ...). The
        result is a confirmation card the user clicks; the browser then
        calls `POST /server/masterchief/execute` with their own JWT.

        This is the only masterchief entry point the model can reach. The
        service API key is rejected at the route layer; the propose tool
        is in-process and writes the audit row with the caller's session
        context (injected as private `_context_*` keys by ToolBridge).

        Example: propose_masterchief_op(op='logs.view', service='vpt-server', lines=200)
        Example: propose_masterchief_op(op='service.restart', host='host-clone-1',
                                         service='vpt-stream',
                                         reason='user asked in chat')
        Example: propose_masterchief_op(op='infra.summary')

        Args:
            params: {
                'op': str (REQUIRED) — one of MASTERCHIEF_OPS.op names,
                ...op-specific params (service, host, lines, ...),
                'reason': str (OPTIONAL) — free-text reason recorded in the audit row.
            }

        Returns:
            MCP-formatted response with the proposal card: audit_id, op,
            summary, blast_radius, required_permission, mutates. The
            front end renders this as a confirm card.
        """
        # Pull trusted identity from the bridge. The model cannot spoof
        # these: ToolBridge injects them from session.context only.
        team_id = str(params.get("_context_team_id") or "").strip()
        user_id = str(params.get("_context_user_id") or "").strip()
        user_email = str(params.get("_context_user_email") or "").strip()
        user_role = str(params.get("_context_user_role") or "viewer").strip()
        if not team_id or not user_id:
            return self._error("masterchief propose requires a session with team_id and user_id")

        op_name = (params.get("op") or "").strip()
        if not op_name:
            return self._error("'op' is required")

        # Strip private keys before the params dict is redacted and stored.
        clean_params = {k: v for k, v in params.items() if not k.startswith("_context_")}

        # Validate the op is in the registry. Everything else is decided at
        # execute time, when the user's JWT is on the wire and the route
        # enforces permission + admin gate + rate limit.
        from backend_server.src.lib.masterchief import get_op
        op = get_op(op_name)
        if op is None:
            return self._error(f"unknown op: {op_name!r}")

        try:
            from backend_server.src.lib.masterchief import audit_db
            row = audit_db.insert_audit_row(
                team_id=team_id,
                requester_user_id=user_id,
                requester_email=user_email,
                requester_role=user_role,
                op=op_name,
                params=clean_params,
                host=clean_params.get("host") if isinstance(clean_params, dict) else None,
                state="proposed",
                trace_id=None,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("masterchief propose: audit insert failed")
            return self._error(f"audit insert failed: {type(e).__name__}")

        # The card shape the front end renders.
        card = {
            "audit_id": row["id"],
            "op": op_name,
            "summary": op.summary,
            "mutates": op.mutates,
            "required_permission": op.required_permission,
            "platform_admin_only": op.platform_admin_only,
            "blast_radius": op.blast_radius,
            "params": clean_params,
            "requester_email": user_email,
        }
        return self._ok(card)

    @staticmethod
    def _ok(data: Any) -> Dict[str, Any]:
        return {"success": True, "data": data}

    @staticmethod
    def _error(message: str) -> Dict[str, Any]:
        return {"success": False, "error": message}
