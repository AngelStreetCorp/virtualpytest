#!/usr/bin/env python3
"""Run validation.py on a web userinterface once per app language and report a table (LANGUAGE_FREE_TREES.md §3).

Per language: switch the app language through Settings -> Language, record proof (location.href and the first sidebar
label, before and after), run `validation.py --userinterface <ui>`, read THIS run's own result (by its execution_id, and
only a result that ended after the run started), then write a markdown table with the report links. Ends in English.

Usage:
  validate_languages.py <userinterface> [--languages de,fr,it,en] [--host host-clone-1] [--device host]
                        [--out table.md] [--no-final-english] [--switch-only]
Needs: the lease on the host (never force_unlock), a logged-in browser (the TASK-135 harness logs in from target.env;
`--login` does it for a browser that shows the logged-out page). Only the UI language setting is ever changed.
Nothing app-specific is in this file: the language list is found by structure (the group of four buttons, the
selected one carries aria-selected), never by a translated label.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

# Position of each language in the Settings -> Language list (fixed order, English first), seen in DE and EN.
LANG_POSITION = {"en": 1, "de": 2, "it": 3, "fr": 4}

LANG_GROUP = "//flt-semantics[@role='group'][count(flt-semantics[@role='button'])=4]"
# `selected`: the 1-based position of the language marked aria-selected on the Settings -> Language list (null elsewhere).
# flutter.language is NOT used as proof: it stayed "de" while the app already showed French.
PROOF_JS = ("""JSON.stringify({href: location.href, label: ((document.querySelector('flt-semantics a')||{}).textContent||'').trim().slice(0, 60), """
            """selected: (()=>{const g=document.evaluate("%s",document,null,9,null).singleNodeValue;if(!g)return null;"""
            """const b=[...g.children].filter(e=>e.getAttribute('role')==='button');const i=b.findIndex(e=>e.getAttribute('aria-selected')==='true');"""
            """return i<0?null:i+1})()})""") % LANG_GROUP.replace('"', "'")


# ---------------------------------------------------------------- pure helpers (tested)

class StaleResult(Exception):
    """The status read does not belong to the run we started."""


def parse_ts(value):
    """ISO string or epoch seconds/milliseconds -> aware datetime (UTC), None when unknown."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def own_result(structured, execution_id, started_at, ended_at=None):
    """The result of THIS run: same execution_id, done, and (when the server gives an end time) ended after we started.
    Raises StaleResult otherwise, so a series never prints the previous language's result as the next one's."""
    if not structured or structured.get("execution_id") != execution_id:
        raise StaleResult(f"status is for {structured and structured.get('execution_id')}, not {execution_id}")
    if not structured.get("done"):
        raise StaleResult(f"{execution_id} is not done ({structured.get('status')})")
    end = parse_ts(ended_at)
    if end is not None and end < started_at:
        raise StaleResult(f"{execution_id} ended {end.isoformat()} before this run started {started_at.isoformat()}")
    return structured


def steps_from_text(text):
    """('49', '49') from a validation summary such as 'Steps: 49/49' or '49/49 steps passed'; None when absent."""
    for pat in (r"(\d+)\s*/\s*(\d+)\s+steps", r"steps?[^0-9\n]{0,20}(\d+)\s*/\s*(\d+)", r"(\d+)\s*/\s*(\d+)\s+(?:transitions|edges)"):
        m = re.search(pat, text or "", re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def selected_language(proof):
    """The language the Settings -> Language list marks as selected, from a proof (None when not on that page)."""
    pos = json.loads(proof).get("selected")
    return next((k for k, v in LANG_POSITION.items() if v == pos), None)


def language_proved(before, after, lang):
    """The switch is proven when the app's address carries `lang` and the sidebar label changed since before (or `before`
    already was `lang`). `after` is a proof taken on the Settings -> Language page, which must mark `lang` as selected."""
    b, a = json.loads(before), json.loads(after)
    if f"/{lang}/" not in (a.get("href") or "") or selected_language(after) not in (lang, None):
        return False
    return a.get("label") != b.get("label") or f"/{lang}/" in (b.get("href") or "")


def report_text(url):
    """Visible text of a run's HTML report (the 'Steps: 49/49 steps successful' summary lives there), '' when unreadable."""
    import html as _html
    import requests
    try:
        raw = requests.get(url, timeout=60).text
    except Exception:
        return ""
    raw = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.S)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def render_table(rows):
    out = ["| Language | Passed | Execution | Report | Proof (before → after) |", "|---|---|---|---|---|"]
    for r in rows:
        steps = f"{r['steps'][0]}/{r['steps'][1]}" if r.get("steps") else ("PASS" if r.get("passed") else "FAIL")
        verdict = steps + (" ✓" if r.get("passed") else " ✗")
        report = f"[report]({r['report_url']})" if r.get("report_url") else "-"
        out.append(f"| {r['lang'].upper()} | {verdict} | `{(r.get('execution_id') or '-')[:8]}` | {report} | {r.get('proof', '-')} |")
    return "\n".join(out)


# ---------------------------------------------------------------- live part

def _bench(host, device):
    os.environ["UC04_HOST"], os.environ["UC04_DEVICE"] = host, device  # the harness reads its host at import
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(here)), "scripts"))
    import bench_tree_build as B  # mcp helpers, target.env reader (login)
    return B


class Runner:
    def __init__(self, ui, host, device):
        self.B = _bench(host, device)
        self.ui, self.host, self.device = ui, host, device
        self.base = None

    # --- MCP
    def call(self, tool, **args):
        import requests
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
        for attempt in range(8):  # the server restarts under a deploy: ride out a few minutes of 5xx / non-JSON answers
            try:
                r = requests.post(f"{self.B.SERVER}/server/mcp", json=body, timeout=300, headers={
                    "Authorization": f"Bearer {self.B.repo_env()['MCP_SECRET_KEY']}",
                    "Accept": "application/json, text/event-stream"})
                r.raise_for_status()
                return r.json().get("result") or {}
            except Exception:
                if attempt == 7:
                    raise
                time.sleep(15)

    def act(self, *actions):
        for _ in range(6):
            res = self.call("execute_device_action", host_name=self.host, device_id=self.device, actions=list(actions))
            text = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
            if "is in use by" not in text:
                return text
            time.sleep(10)
        return text

    def js(self, script):
        text = self.act({"command": "execute_javascript", "params": {"script": script}})
        i = text.find('[{"result"')
        if i < 0:
            raise RuntimeError(f"no result: {text[:200]}")
        arr, _ = json.JSONDecoder().raw_decode(text[i:])
        return arr[0]["result"]

    def app_url(self, path):
        if self.base is None:
            from urllib.parse import urlparse
            p = urlparse(self.B.target()["VPTTV_URL"])
            self.base = f"{p.scheme}://{p.netloc}"
        return self.base + path

    def open(self, path):
        self.act({"command": "navigate_to_url", "params": {"url": self.app_url(path), "page_load_timeout": 30000}})
        time.sleep(7)
        self.act({"command": "activate_semantic", "params": {}})
        time.sleep(2)

    # --- session
    def logged_in(self):
        try:
            return bool(json.loads(self.js("JSON.stringify(localStorage.getItem('flutter.username'))")))
        except Exception:
            return False

    def ensure_session(self, login=True):
        """Chrome open on the app and logged in. A closed or restarted Chrome (it happens on a loaded host) comes back on
        a blank or foreign page: reopen the app, and log in once through the SSO page when the app shows the logged-out
        page (the harness's own login: target.env, never typed by hand, never repeated in a loop)."""
        self.B.ensure_browser()
        t = self.B.target()
        self.act({"command": "navigate_to_url", "params": {"url": t["VPTTV_URL"], "page_load_timeout": 30000}})
        time.sleep(7)
        self.act({"command": "activate_semantic", "params": {}})
        if self.logged_in() or not login:
            return
        self.act({"command": "click_element", "params": {"element_id": "#onetrust-reject-all-handler"}})
        time.sleep(2)
        self.act({"command": "activate_semantic", "params": {}})
        for label in ("ANMELDEN", "Login", "LOGIN", "Se connecter", "ACCEDI"):
            if "Timeout" not in self.act({"command": "click_element", "params": {"element_id": label}}):
                break
        time.sleep(5)
        self.act({"command": "input_text", "params": {"selector": "#username", "text": t["VPTTV_LOGIN"]}},
                 {"command": "input_text", "params": {"selector": "#password", "text": t["VPTTV_PASSWORD"]}})
        self.act({"command": "click_element", "params": {"element_id": "#kc-login", "wait_time": 6000}})
        time.sleep(6)
        self.act({"command": "navigate_to_url", "params": {"url": t["VPTTV_URL"], "page_load_timeout": 30000}})
        time.sleep(7)
        self.act({"command": "activate_semantic", "params": {}})
        if not self.logged_in():
            raise RuntimeError("login did not stick: the app is still logged out (stuck SSO session? clear the browser storage)")

    def stuck(self):
        """The app shows its generic error page (a stuck SSO session, BUG-0709 trap): `/home/generalerror`."""
        try:
            return "generalerror" in self.js("location.href")
        except Exception:
            return False

    def recover(self):
        """Clear the app's browser storage (the harness's own reset) and log in once."""
        self.B.reset_browser(self.B.target())
        self.ensure_session()

    # --- language
    def proof(self):
        return self.js(PROOF_JS)

    def current_language(self):
        """Language marked selected on the Settings -> Language list (call it on that page)."""
        return selected_language(self.proof())

    def switch_language(self, lang):
        """Settings -> Language, press the language's button (by position), reload, return (before, after) proofs."""
        self.open("/en/settings")
        if self.stuck() or not self.logged_in():
            self.recover()
            self.open("/en/settings")
        before = self.proof()
        if self.current_language() == lang:
            return before, before
        for _ in range(3):
            self.act({"command": "click_element", "params": {
                "element_id": f"xpath=({LANG_GROUP}/flt-semantics[@role='button'])[{LANG_POSITION[lang]}]", "wait_time": 3000}})
            time.sleep(4)
            self.act({"command": "activate_semantic", "params": {}})
            if self.current_language() == lang:
                break
        if self.stuck():
            raise RuntimeError(f"the app shows its error page after the switch to {lang}: {self.proof()}")
        after = self.proof()                       # still on Settings -> Language: the selected item and the address
        self.open(f"/{lang}/home")                 # then the sidebar label on Home
        home = json.loads(self.proof())
        after = json.dumps({**json.loads(after), "label": home["label"]})
        if not language_proved(before, after, lang):
            raise RuntimeError(f"language did not switch to {lang}: before {before} after {after}")
        return before, after

    # --- run
    def validate(self, extra=""):
        started = datetime.now(timezone.utc)
        res = self.call("execute_script", script_name="validation.py", host_name=self.host, device_id=self.device,
                        userinterface_name=self.ui, parameters=extra)
        st = res.get("structuredContent") or {}
        eid = st.get("execution_id")
        if res.get("isError") or not eid:
            raise RuntimeError(f"validation did not start: {json.dumps(res)[:300]}")
        while True:
            got = self.call("get_script_execution_status", execution_id=eid, wait_seconds=50)
            s = got.get("structuredContent") or {}
            text = "\n".join(c.get("text", "") for c in got.get("content", []) if c.get("type") == "text")
            if got.get("isError") and "not found" in text.lower():
                # vpt-server restarted (a deploy) and lost the task; the host script keeps running and its row in
                # script_results gets the report: read THAT run's row (host, interface, started after our start)
                s = self.wait_db_result(eid, started)
                return own_result(s, eid, started, s.get("ended_at")), "", started
            if s.get("done"):
                return own_result(s, eid, started, s.get("ended_at") or s.get("completed_at")), text, started

    def wait_db_result(self, eid, started, give_up_s=3600):
        t0 = time.time()
        while time.time() - t0 < give_up_s:
            rows = self.B.sql(
                "select started_at, completed_at, success, html_report_r2_url u from script_results where script_name='validation' "
                f"and userinterface_name={self.B.q(self.ui)} and host_name={self.B.q(self.host)} "
                f"and started_at >= {self.B.q((started - timedelta(seconds=60)).isoformat())} order by started_at limit 1", as_json=True)
            if rows and rows[0].get("u") and rows[0].get("completed_at"):
                r = rows[0]
                return {"execution_id": eid, "done": True, "passed": bool(r["success"]), "report_url": r["u"],
                        "ended_at": r["completed_at"], "status": "completed"}
            time.sleep(30)
        raise RuntimeError(f"no result row for {eid} after {give_up_s}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ui")
    ap.add_argument("--languages", default="de,fr,it,en")
    ap.add_argument("--host", default="host-clone-1")
    ap.add_argument("--device", default="host")
    ap.add_argument("--out")
    ap.add_argument("--no-final-english", action="store_true")
    ap.add_argument("--switch-only", action="store_true", help="switch and prove, do not run validation")
    a = ap.parse_args()
    langs = [x.strip() for x in a.languages.split(",") if x.strip()]
    bad = [x for x in langs if x not in LANG_POSITION]
    if bad:
        raise SystemExit(f"unknown language {bad}; known: {sorted(LANG_POSITION)}")
    r = Runner(a.ui, a.host, a.device)
    rows = []
    for lang in langs:
        r.ensure_session()
        before, after = r.switch_language(lang)
        b, af = json.loads(before), json.loads(after)
        proof = f"`{b['label'][:18]}` → `{af['label'][:18]}`; {af['href'].split('//')[-1].split('/', 1)[-1]}"
        row = {"lang": lang, "proof": proof}
        if not a.switch_only:
            s, text, started = r.validate()
            row.update(execution_id=s["execution_id"], passed=bool(s.get("passed")), report_url=s.get("report_url"),
                       steps=steps_from_text(report_text(s.get("report_url")) if s.get("report_url") else text), started=started.isoformat(timespec="seconds"))
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if not a.no_final_english and langs and langs[-1] != "en":
        r.switch_language("en")
        print("back in English", flush=True)
    table = render_table(rows)
    print(table)
    if a.out:
        open(a.out, "w").write(table + "\n")
    return 0 if all(x.get("passed") or a.switch_only for x in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
