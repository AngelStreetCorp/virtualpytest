"""
LocalIO: the executors' stand-in for local game runs (TASK-33). It plays a userinterface tree's
own action dicts (press_key, execute_javascript, navigate_to_url) with Playwright, runs the node
checks like the web controller (a CSS locator with a layout box) and saves viewport screenshots
as frames. action_ms adds a delay per action to mimic the host's executor overhead (~25 ms).
"""

import os
import time

KEYS = {"SPACE": "Space", "UP": "ArrowUp", "DOWN": "ArrowDown", "LEFT": "ArrowLeft", "RIGHT": "ArrowRight",
        "ESCAPE": "Escape", "ESC": "Escape"}


class Context:
    team_id = "local"

    def __init__(self):
        self.step_results, self.screenshot_paths = [], []

    def record_step_immediately(self, step):
        self.step_results.append(step)
        print(f"[step] {'PASS' if step['success'] else 'FAIL'} {step['message']}", flush=True)


class LocalIO:
    def __init__(self, page, action_ms, out_dir, manifest):
        self.page, self.action_ms, self.out = page, action_ms, out_dir
        tree = manifest["trees"][0]
        self.nodes = {n["node_id"]: n for n in tree["nodes"]}
        self.edges = {(e["source_node_id"], e["target_node_id"]): e for e in tree["edges"]}
        self.at = "entry-node"
        self.n = 0

    def edge_actions(self, source, target):
        e = self.edges.get((source, target))
        return list(e["action_sets"][0]["actions"]) if e else []

    def run_actions(self, actions):
        results, ok = [], True
        for a in actions:
            p = a.get("params", {})
            out, success = {}, True
            if a["command"] == "press_key":
                self.page.keyboard.press(KEYS.get(p["key"].upper(), p["key"]))
            elif a["command"] == "execute_javascript":
                out = {"result": self.page.evaluate(p["script"])}
            elif a["command"] == "navigate_to_url":
                self.page.goto(p["url"], wait_until="load")
            elif a["command"] == "open_browser":
                pass
            else:
                success = False
            if self.action_ms:
                time.sleep(self.action_ms / 1000)
            if p.get("wait_time"):
                time.sleep(p["wait_time"] / 1000)
            ok = ok and success
            results.append({"success": success, "output_data": out})
        return {"success": ok, "results": results}

    def _check(self, node_id):
        for v in self.nodes[node_id]["verifications"]:
            deadline = time.time() + v["params"].get("timeout", 5000) / 1000
            while True:
                if self.page.locator(v["params"]["search_term"]).first.bounding_box(timeout=300):
                    break
                if time.time() > deadline:
                    return False
                time.sleep(0.2)
        return True

    def navigate(self, target):
        path = [("entry-node", "game")] if self.at == "entry-node" and target != "game" else []
        path.append(("entry-node" if self.at == "entry-node" else "game", target))
        for src, dst in path:
            self.run_actions(self.edge_actions(src, dst))
            if self.nodes[dst]["node_type"] != "action" and not self._check(dst):
                return {"success": False, "error": f"{dst} check failed"}
            self.at = dst if self.nodes[dst]["node_type"] != "action" else "game"
        return {"success": True}

    def frame(self):
        self.n += 1
        path = os.path.join(self.out, f"frame_{self.n:05d}.png")
        self.page.screenshot(path=path)
        return path

    def evidence(self, name):
        return self.frame()
