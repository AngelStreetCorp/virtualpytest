"""Smoke-walk a web navigation tree: every node, forward and back, N passes in a row.

A showcase tree (`web-<site>`, TASK-161) is only worth showing if a script can walk it
without a human: from the entry point, to every node, and back again — twice, back to back,
on a live browser. `validation.py` walks the *edges* in the planner's optimal order; this
walks the *screens*, so a node whose edge exists but whose verification does not still fails
here. Same navigation executor, same verifications, one screen at a time.

The walker is site-agnostic: the site scripts under `test_scripts/web/` call
`smoke_walk_web_tree(context, ui_name, passes=2)` and turn the returned dict into a report.
"""
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

ENTRY_NODE = "entry-node"
DEFAULT_HOME = "home"
DEFAULT_POOL_MS = 1500


def resolve_tree(context, ui_name: str) -> Tuple[Optional[str], List[dict]]:
    """Return (tree_id, content nodes) for a userinterface, loading the tree on the device."""
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface

    team_id = context.team_id
    ui = get_userinterface_by_name(ui_name, team_id, mode=getattr(context.args, "ui_mode", "dev"))
    if not ui:
        raise RuntimeError(f"user interface '{ui_name}' not found")
    root = get_root_tree_for_interface(ui["id"], team_id)
    if not root:
        raise RuntimeError(f"no root tree for user interface '{ui_name}'")
    tree_id = root["id"]

    device = context.selected_device
    nav_result = device.navigation_executor.load_navigation_tree(ui_name, team_id)
    if not nav_result.get("success"):
        raise RuntimeError(f"navigation tree load failed: {nav_result.get('error')}")

    nodes = nav_result.get("nodes") or []
    content = [n for n in nodes if n.get("node_id") != ENTRY_NODE]
    content.sort(key=lambda n: (0 if n.get("node_id") == DEFAULT_HOME else 1, n.get("node_id") or ""))
    return tree_id, content


def _record(context, message: str, success: bool, from_node: str, to_node: str,
            started: float, error: str = "", screenshot: str = "",
            verifications: Optional[list] = None) -> None:
    now = datetime.now()
    context.record_step_immediately({
        "success": success,
        "message": message,
        "from_node": from_node,
        "to_node": to_node,
        "execution_time_ms": int((now.timestamp() - started) * 1000),
        "start_time": datetime.fromtimestamp(started).strftime("%H:%M:%S"),
        "end_time": now.strftime("%H:%M:%S"),
        "screenshot_path": screenshot or None,
        "step_end_screenshot_path": screenshot or None,
        "action_screenshots": [screenshot] if screenshot else [],
        "actions": [],
        "verifications": verifications or [],
        "verification_results": [],
        "step_category": "web_tree_smoke",
        "error": error or None,
    })


async def _goto(device, tree_id: str, ui_name: str, team_id: str, context, node_id: str,
               start_from_entry: bool = False, timeout_s: float = 180.0) -> dict:
    """Navigate, but never longer than `timeout_s` (same reason as the verification timeout)."""
    try:
        return await asyncio.wait_for(
            device.navigation_executor.execute_navigation(
                tree_id=tree_id,
                target_node_id=node_id,
                userinterface_name=ui_name,
                team_id=team_id,
                context=context,
                start_from_entry=start_from_entry,
            ),
            timeout=timeout_s)
    except asyncio.TimeoutError:
        return {"success": False, "error": f"navigation to {node_id} timed out after {timeout_s:.0f}s"}


def verification_list(node: dict) -> List[dict]:
    """A node's verifications, whichever shape the tree stores them in.

    A tree built today stores a plain list. `youtube-web`, built before that
    convention, stores `{"item": [...]}` — and `{"item": {"item": [...]}}` on one
    node. The verification executor wants a list and reads `verifications[0]`,
    which raises on the object shape, so a walk of that tree would die on a node
    that is perfectly walkable.
    """
    v = node.get("verifications")
    for _ in range(3):                      # {"item": {"item": [...]}} is two deep
        if isinstance(v, list):
            return v
        if not isinstance(v, dict):
            return []
        if "command" in v or "verification_type" in v:
            return [v]                      # a single verification, wrapped once
        v = v.get("item")
    return v if isinstance(v, list) else []


async def _verify(device, tree_id: str, ui_name: str, team_id: str, node: dict,
                  timeout_s: float = 120.0) -> dict:
    """Run a node's verifications, but never longer than `timeout_s`.

    A `waitForUrlToMatch` that never matches must not hang the whole walk: measured on
    `web-wikipedia`, one such verification kept the run alive for 22 minutes with no
    navigation at all, and the next three smokes never started. A timeout turns it into a
    recorded failure, which is what it is.
    """
    verifications = verification_list(node)
    if not verifications:
        return {"success": False, "message": "node has no verification",
                "error": "no verification on this node"}
    try:
        return await asyncio.wait_for(
            device.navigation_executor.execute_single_node_verification(
                tree_id=tree_id,
                node_id=node.get("node_id"),
                verifications=verifications,
                userinterface_name=ui_name,
                team_id=team_id,
            ),
            timeout=timeout_s)
    except asyncio.TimeoutError:
        return {"success": False, "message": f"verification timed out after {timeout_s:.0f}s",
                "error": "verification timeout"}


def smoke_walk_web_tree(context, ui_name: str, passes: int = 2,
                        home_node: str = DEFAULT_HOME) -> Dict[str, Any]:
    """Walk the tree `passes` times in a row: entry → each node → home → next node.

    Returns a summary dict; the caller puts it in `context.execution_summary` and returns
    `summary['success']` from the script's `main`.
    """
    import time

    device = context.selected_device
    if device is None:
        raise RuntimeError("no device selected")
    team_id = context.team_id
    tree_id, content = resolve_tree(context, ui_name)
    if not content:
        raise RuntimeError(f"user interface '{ui_name}' has no content node to walk")

    home = next((n for n in content if n.get("node_id") == home_node), content[0])
    home_id = home.get("node_id")
    targets = [n for n in content if n.get("node_id") != home_id]

    lines = [
        "-" * 60,
        f"🌳 [WEB TREE SMOKE] {ui_name} — {len(content)} screens, {passes} passes",
        "-" * 60,
        f"🌳 Home: {home_id}",
    ]
    failures: List[str] = []
    checked = 0

    for p in range(1, passes + 1):
        # The entry edge is what opens the site, and `start_from_entry` is how you take it:
        # there is no edge INTO entry-node, so asking to navigate to it is not a thing the
        # executor can do (it returns "already at entry-node" and then trips over the missing
        # step list). Starting each pass from the entry actions also means pass N+1 begins
        # where pass 1 did, instead of wherever pass N happened to end.
        started = time.time()
        entry = asyncio.run(_goto(device, tree_id, ui_name, team_id, context, home_id,
                                  start_from_entry=True))
        _record(context, f"pass {p}: entry → {home_id}", bool(entry.get("success")),
                ENTRY_NODE, home_id, started, error=entry.get("error") or "")
        if not entry.get("success"):
            failures.append(f"pass {p}: entry edge failed ({entry.get('error')})")
            lines.append(f"❌ pass {p}: entry edge failed — {entry.get('error')}")
            break

        started = time.time()
        home_ok = asyncio.run(_verify(device, tree_id, ui_name, team_id, home))
        checked += 1
        _record(context, f"pass {p}: verify home", bool(home_ok.get("success")), home_id, home_id,
                started, error=home_ok.get("error") or home_ok.get("message") or "",
                verifications=[{"verification_type": "web", "command": "node_verifications",
                                "label": f"{home_id}: {home.get('label')}", "success": bool(home_ok.get("success"))}])
        if not home_ok.get("success"):
            failures.append(f"pass {p}: home {home_id} failed verification")
        lines.append(f"{'✅' if home_ok.get('success') else '❌'} pass {p}: home {home_id} "
                     f"({home_ok.get('message') or home_ok.get('error') or 'verified'})")

        for node in targets:
            nid = node.get("node_id")
            started = time.time()
            fwd = asyncio.run(_goto(device, tree_id, ui_name, team_id, context, nid))
            ok_fwd = bool(fwd.get("success"))
            ver = {}
            if ok_fwd:
                ver = asyncio.run(_verify(device, tree_id, ui_name, team_id, node))
            ok_ver = bool(ver.get("success"))
            checked += 1
            _record(context, f"pass {p}: → {nid} and verify", ok_fwd and ok_ver, home_id, nid, started,
                    error=(fwd.get("error") or "") or (ver.get("error") or ver.get("message") or ""),
                    verifications=[{"verification_type": "web", "command": "node_verifications",
                                    "label": f"{nid}: {node.get('label')}", "success": ok_ver}])
            if not (ok_fwd and ok_ver):
                failures.append(f"pass {p}: {nid} "
                                + (f"navigation failed ({fwd.get('error')})" if not ok_fwd
                                   else f"verification failed ({ver.get('error') or ver.get('message')})"))

            started = time.time()
            back = asyncio.run(_goto(device, tree_id, ui_name, team_id, context, home_id))
            ok_back = bool(back.get("success"))
            checked += 1
            _record(context, f"pass {p}: {nid} → back to {home_id}", ok_back, nid, home_id, started,
                    error=back.get("error") or "")
            if not ok_back:
                failures.append(f"pass {p}: back from {nid} to {home_id} failed ({back.get('error')})")
            lines.append(
                f"{'✅' if ok_fwd and ok_ver and ok_back else '❌'} pass {p}: {nid} "
                f"(forward {'ok' if ok_fwd else 'FAILED'}, verify {'ok' if ok_ver else 'FAILED'}, "
                f"back {'ok' if ok_back else 'FAILED'})")

    ok = not failures and checked > 0
    lines.append("-" * 60)
    lines.append(f"📊 [WEB TREE SMOKE] {passes} pass(es), {checked} checks, "
                 f"{len(failures)} failure(s)")
    for f in failures:
        lines.append(f"❌ {f}")
    lines.append(f"🎯 Result: {'SUCCESS' if ok else 'FAILED'}")
    lines.append("-" * 60)
    return {"success": ok, "ui": ui_name, "passes": passes, "nodes": len(content),
            "checks": checked, "failures": failures, "summary": "\n".join(lines)}