"""Atlas tools for custom pages (TASK-139): build, change and share pages from catalogue blocks.

A page is data, never code: ``create_custom_page`` and ``update_custom_page`` accept only the blocks of
``services/custom_pages/catalogue.py``. The caller is the signed-in user (ToolBridge injects the private
``_context_*`` keys, the model cannot set them); a block the user lacks the permission for is refused with
the reason, and ``list_custom_blocks`` shows what they may use. A page Atlas creates is a DRAFT that only the
owner sees until they press Save page in the app.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from backend_server.src.services.custom_pages import catalogue, service
from backend_server.src.services.custom_pages.catalogue import DefinitionError
from shared.src.lib.database import custom_pages_db, teams_db

logger = logging.getLogger(__name__)

# ToolBridge injects the trusted caller context into exactly these tools.
CUSTOM_PAGE_TOOL_NAMES = frozenset({
    "list_custom_blocks", "list_custom_pages", "get_custom_page",
    "create_custom_page", "update_custom_page", "share_custom_page",
})


def _ok(payload: Dict[str, Any], message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": False, **payload}


def _fail(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


class _Caller:
    """Who is asking, and whether they hold a permission (their role, grants, denials and team ceiling)."""

    def __init__(self, params: Dict[str, Any]) -> None:
        self.team_id = str(params.get("_context_team_id") or "")
        self.user_id = str(params.get("_context_user_id") or "")
        self.holds = service.holds_for_user(self.user_id) if self.user_id else None
        # A shared principal (auto-sign, open mode) has no profile row; the server resolved its role, and an
        # admin holds every permission, exactly as @require_permission treats it on the HTTP routes.
        if self.holds is None and self.user_id and str(params.get("_context_user_role") or "") == "admin":
            self.holds = lambda permission: True

    def check(self) -> Optional[Dict[str, Any]]:
        if not self.team_id or not self.user_id:
            return _fail("Custom pages need a signed-in user in a team.")
        if self.holds is None:
            return _fail("Your account could not be resolved, so no custom-page permission can be granted.")
        if not self.holds("pages.custom:view"):
            return _fail("You do not have access to custom pages (needs pages.custom:view). Ask a team admin.")
        return None

    def check_edit(self) -> Optional[Dict[str, Any]]:
        problem = self.check()
        if problem:
            return problem
        if not self.holds("pages.custom:edit"):
            return _fail("You cannot create or change custom pages (needs pages.custom:edit). Ask a team admin.")
        return None


def _summary(page: Dict[str, Any]) -> str:
    return f"'{page['title']}' ({page['id']}, {page['status']}, {page['block_count']} blocks, you are {page['access']})"


def _layout(page: Dict[str, Any]) -> str:
    lines = []
    for block in page["definition"]["blocks"]:
        settings = ", ".join(f"{k}={v}" for k, v in block["settings"].items() if v != "")
        state = page["block_states"].get(block["id"], {})
        lock = f" [LOCKED for you: needs {', '.join(state.get('missing', []))}]" if not state.get("available", True) else ""
        lines.append(f"  {block['id']}: {block['type']} (columns {block['x'] + 1}-{block['x'] + block['w']}) {settings}{lock}")
    return "\n".join(lines) or "  (no blocks)"


class CustomPageTools:
    """Build, change and share custom pages made of catalogue blocks."""

    def __init__(self, api_client=None):
        self.api_client = api_client

    def list_custom_blocks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List the blocks a custom page can contain, split into the blocks THIS user may use and the blocks
        they may not (with the missing permission). Call it before building a page, and to answer "which
        blocks can I use?". Only blocks from `available` can be added.

        Example: list_custom_blocks()

        Args:
            params: {}
        """
        caller = _Caller(params)
        problem = caller.check()
        if problem:
            return problem
        cat = catalogue.catalogue_for(caller.holds)
        lines = ["Blocks you can use:"]
        for b in cat["available"]:
            settings = ", ".join(b["settings"]) or "no settings"
            lines.append(f"- {b['type']}: {b['description']} Settings: {settings}.")
        if cat["unavailable"]:
            lines.append("Blocks you can NOT use:")
            lines += [f"- {b['type']}: {b['reason']}" for b in cat["unavailable"]]
        return _ok({"catalogue": cat}, "\n".join(lines))

    def list_custom_pages(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List the custom pages the user can open: their own, drafts, and pages shared with them.

        Example: list_custom_pages()

        Args:
            params: {}
        """
        caller = _Caller(params)
        problem = caller.check()
        if problem:
            return problem
        pages = service.list_pages(caller.team_id, caller.user_id, caller.holds)
        text = "\n".join(f"- {_summary(p)}" for p in pages) or "No custom pages yet."
        return _ok({"pages": pages}, text)

    def get_custom_page(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read one custom page: its blocks, their settings and which are locked for the user.

        Example: get_custom_page(page_id='...')

        Args:
            params: {
                'page_id': str (REQUIRED - id from list_custom_pages or create_custom_page)
            }
        """
        caller = _Caller(params)
        problem = caller.check()
        if problem:
            return problem
        page = service.get_page(caller.team_id, caller.user_id, str(params.get("page_id") or ""), caller.holds)
        if not page:
            return _fail("No such page, or it is not visible to you.")
        return _ok({"page": page}, f"{_summary(page)}\n{_layout(page)}")

    def create_custom_page(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a custom page from catalogue blocks. The page is a DRAFT that only the user sees; tell them to
        open it, check it and press "Save page". Use only block types from list_custom_blocks `available`. A
        block that reads a device (node_goto, localize_result, stream) needs a device_picker block on the page;
        with exactly one picker it is wired automatically. Never invent block types or settings.

        Example: create_custom_page(title='STB navigator', blocks=[{'type':'device_picker','settings':{'model_filter':'stb'}},{'type':'node_goto'},{'type':'localize_result'}])

        Args:
            params: {
                'title': str (REQUIRED - the page name, max 120 characters),
                'blocks': list (REQUIRED - block objects in reading order, each with type, optional settings object and optional w columns 1-6)
            }
        """
        caller = _Caller(params)
        problem = caller.check_edit()
        if problem:
            return problem
        try:
            page = service.create_page(caller.team_id, caller.user_id, caller.holds, title=params.get("title"),
                                       definition={"blocks": params.get("blocks") or []}, status="draft")
        except DefinitionError as exc:
            return _fail(exc.message)
        return _ok({"page": page, "url": f"/pages/{page['id']}"},
                   f"Created the draft {_summary(page)}:\n{_layout(page)}\n"
                   f"Open it at /pages/{page['id']} (Pages menu > Drafts), check it and press Save page to keep it. "
                   "Nobody else can see it until it is saved and shared.")

    def update_custom_page(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Change a custom page with small edits: add_block {type, settings?, w?}, remove_block {id},
        set_setting {id, key, value}, move_block {id, to_index?, w?}. Read the page first (get_custom_page) to
        know the block ids. A change to a saved page is applied immediately: say what you changed. Needs edit
        access to the page and the permission of every block you add or change.

        Example: update_custom_page(page_id='...', ops=[{'op':'remove_block','id':'b4'},{'op':'add_block','type':'recent_runs'}])

        Args:
            params: {
                'page_id': str (REQUIRED - id of the page to change),
                'ops': list (REQUIRED - the edits, applied in order),
                'title': str (OPTIONAL - rename the page)
            }
        """
        caller = _Caller(params)
        problem = caller.check_edit()
        if problem:
            return problem
        try:
            page = service.update_page(caller.team_id, caller.user_id, str(params.get("page_id") or ""), caller.holds,
                                       title=params.get("title"), ops=params.get("ops"))
        except DefinitionError as exc:
            return _fail(exc.message)
        if not page:
            return _fail("No such page, or it is not visible to you.")
        return _ok({"page": page}, f"Updated {_summary(page)}:\n{_layout(page)}")

    def share_custom_page(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Share a SAVED page you own with named team members (by name or email) and/or the whole team. Sharing
        grants no right: each person sees a block with their own permissions, a block they may not use is
        locked for them. The result says how many blocks each person would see locked. ASK THE USER TO CONFIRM
        who to share with before calling this. Only adds people; it never removes an existing share.

        Example: share_custom_page(page_id='...', users=['marie@example.com'], can_edit=false)

        Args:
            params: {
                'page_id': str (REQUIRED - id of a saved page you own),
                'users': list (OPTIONAL - names or emails of team members to add),
                'whole_team': bool (OPTIONAL - make the page viewable by the whole team),
                'can_edit': bool (OPTIONAL - let the named users edit it too, default false)
            }
        """
        caller = _Caller(params)
        problem = caller.check_edit()
        if problem:
            return problem
        page = custom_pages_db.get_page(caller.team_id, str(params.get("page_id") or ""))
        if not page or page.get("owner_id") != caller.user_id:
            return _fail("No such page, or you are not its owner (only the owner shares a page).")
        wanted = [str(u).strip().lower() for u in (params.get("users") or []) if str(u).strip()]
        members = teams_db.get_team_members(caller.team_id)
        shares: Dict[str, Dict[str, Any]] = {s["user_id"]: s for s in custom_pages_db.list_shares(caller.team_id, page["id"])}
        unmatched: List[str] = []
        for name in wanted:
            match = next((m for m in members if name in (str(m.get("email") or "").lower(), str(m.get("full_name") or "").lower())), None)
            if not match:
                unmatched.append(name)
                continue
            shares[str(match["user_id"])] = {"user_id": str(match["user_id"]), "can_edit": bool(params.get("can_edit"))}
        if unmatched:
            return _fail("Not team members, nothing shared: " + ", ".join(unmatched)
                         + ". Team members: " + ", ".join(str(m.get("full_name") or m.get("email")) for m in members))
        visibility = "team" if params.get("whole_team") else page["visibility"]
        try:
            view = service.set_sharing(caller.team_id, caller.user_id, page["id"], visibility=visibility,
                                       shares=[{"user_id": s["user_id"], "can_edit": s["can_edit"]} for s in shares.values()])
        except DefinitionError as exc:
            return _fail(exc.message)
        lines = [f"Shared '{page['title']}'. Visibility: {view['visibility']}."]
        for m in view["members"]:
            if m["shared"]:
                lock = "" if not m["locked_blocks"] else f", would see {m['locked_blocks']} block(s) locked"
                lines.append(f"- {m['name']}: {'can edit' if m['can_edit'] else 'can view'}{lock}")
        return _ok({"sharing": view}, "\n".join(lines))
