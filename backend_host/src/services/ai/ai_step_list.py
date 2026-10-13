"""
Step-list text <-> testcase graph, for AI graph generation and prompt editing (TASK-36 §3).

The AI builder talks to the LLM in a numbered step list, one block per line:

    Navigate to: <node>
    Action: <command>(param=value, ...) + <command>(...)     # one action container block
    Verify: <command>(param=value, ...)                        # one verification container block
    Wait: <milliseconds>                                       # the sleep block
    ... [on fail: continue]                                    # failure goes on to the next step

Only a "step-list graph" has this form: a single success chain from START of navigation /
action / verification / sleep blocks, each failing to FAILURE (or, with "continue", to the
next block). That is every QuickTest test and every AI-generated graph.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

CONTINUE_SUFFIX = '[on fail: continue]'

_PARAM_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^,]*))')
_ITEM_RE = re.compile(r'^\s*([a-zA-Z0-9_]+)\s*(?:\((.*)\))?\s*$', re.DOTALL)
_NAV_RE = re.compile(r'(?:Navigation:|Navigate to:)\s*(?:Navigate to:)?\s*([a-zA-Z0-9_&\-]+)', re.IGNORECASE)
_SIMPLE_VALUE_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')


class NotAStepList(ValueError):
    """The graph has a shape the step list cannot carry (branching, loop, other blocks)."""


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

def parse_params(text: Optional[str]) -> Dict[str, Any]:
    """'key=OK, text="Live, TV", timeout=5000' -> {'key': 'OK', 'text': 'Live, TV', 'timeout': 5000}"""
    params: Dict[str, Any] = {}
    for m in _PARAM_RE.finditer(text or ''):
        if m.group(2) is not None or m.group(3) is not None:
            params[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
            continue
        raw = m.group(4).strip()
        if not raw or raw.startswith('<'):
            continue  # unfilled placeholder
        try:
            params[m.group(1)] = int(raw)
        except ValueError:
            try:
                params[m.group(1)] = float(raw)
            except ValueError:
                params[m.group(1)] = raw
    return params


def format_item(command: str, params: Optional[Dict[str, Any]]) -> str:
    """'press_key(key=OK)'. Scalar params only: areas, references and other objects are not
    written (an unchanged block keeps them, see reuse in the AI builder)."""
    parts = []
    for name, value in (params or {}).items():
        if isinstance(value, bool):
            parts.append(f"{name}={'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            parts.append(f"{name}={value}")
        elif isinstance(value, str) and value != '':
            parts.append(f"{name}={value}" if _SIMPLE_VALUE_RE.match(value) else f'{name}="{value}"')
    return f"{command}({', '.join(parts)})"


def _split_items(text: str) -> List[str]:
    """Split 'a(x=1) + b(text="a + b")' on ' + ' outside parentheses and quotes."""
    items, depth, quote, start = [], 0, None, 0
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                quote = None
        elif c in '"\'':
            quote = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == '+' and depth == 0:
            items.append(text[start:i])
            start = i + 1
        i += 1
    items.append(text[start:])
    return [it.strip() for it in items if it.strip()]


# ---------------------------------------------------------------------------
# Line <-> step
# ---------------------------------------------------------------------------

def parse_step_line(content: str) -> Optional[Dict[str, Any]]:
    """One step line (without its number) -> a step dict, or None when it is not a step."""
    text = content.strip()
    continue_on_fail = text.endswith(CONTINUE_SUFFIX)
    if continue_on_fail:
        text = text[: -len(CONTINUE_SUFFIX)].strip()
    lower = text.lower()

    if lower.startswith('wait:'):
        ms = re.search(r'\d+', text)
        return {'type': 'wait', 'ms': int(ms.group(0)) if ms else 1000, 'continue_on_fail': continue_on_fail}

    if 'navigate to' in lower or lower.startswith('navigation:'):
        m = _NAV_RE.search(text)
        return {'type': 'navigation', 'target': m.group(1).strip(), 'continue_on_fail': continue_on_fail} if m else None

    for prefix, step_type in (('action:', 'action'), ('verify:', 'verification')):
        idx = lower.find(prefix)
        if idx == -1:
            continue
        items = []
        for part in _split_items(text[idx + len(prefix):]):
            m = _ITEM_RE.match(part)
            if m:
                items.append({'command': m.group(1), 'params': parse_params(m.group(2))})
        return {'type': step_type, 'items': items, 'continue_on_fail': continue_on_fail} if items else None
    return None


_NUMBERED_RE = re.compile(r'^(?:\d+|[a-z])[.)]\s*(.*)$')
_REPEAT_RE = re.compile(r'^(?:loop|repeat)\s+(\d+)\s*(?:times|x)?\b.*?:?\s*$', re.IGNORECASE)


def parse_step_list(text: str) -> List[Dict[str, Any]]:
    """The STEPS section of an AI answer -> step dicts, in run order.

    A "LOOP|Repeat N times:" header with lettered or indented steps under it is written out
    N times (the step list has no loop block). A numbered or lettered line that is not a step
    raises ValueError: a step that is dropped would let the test pass without it.
    """
    steps: List[Dict[str, Any]] = []
    repeat: Optional[Tuple[int, List[Dict[str, Any]]]] = None

    def close_repeat():
        nonlocal repeat
        if repeat:
            count, body = repeat
            if not body:
                raise ValueError(f"'Repeat {count} times' has no steps under it")
            for _ in range(count):
                steps.extend(dict(s) for s in body)
        repeat = None

    for raw in text.split('\n'):
        if not raw.strip():
            continue
        indented = raw[:1] in (' ', '\t')
        m = _NUMBERED_RE.match(raw.strip())
        if not m:
            continue  # prose between steps
        content = m.group(1).strip()
        lettered = raw.strip()[0].isalpha()
        header = _REPEAT_RE.match(content)
        if header:
            close_repeat()
            repeat = (int(header.group(1)), [])
            continue
        step = parse_step_line(content)
        if step is None:
            raise ValueError(f"Not a step: '{raw.strip()}'")
        if repeat and (lettered or indented):
            repeat[1].append(step)
        else:
            close_repeat()
            steps.append(step)
    close_repeat()
    return steps


def step_to_line(step: Dict[str, Any]) -> str:
    """Canonical line for a step dict (also how an unchanged block is recognised)."""
    if step['type'] == 'navigation':
        line = f"Navigate to: {step['target']}"
    elif step['type'] == 'wait':
        line = f"Wait: {step['ms']}"
    else:
        prefix = 'Action' if step['type'] == 'action' else 'Verify'
        line = f"{prefix}: " + ' + '.join(format_item(it['command'], it.get('params')) for it in step['items'])
    return f"{line} {CONTINUE_SUFFIX}" if step.get('continue_on_fail') else line


# ---------------------------------------------------------------------------
# Graph -> steps
# ---------------------------------------------------------------------------

def _node_to_step(node: Dict[str, Any]) -> Dict[str, Any]:
    node_type = node.get('type')
    data = node.get('data') or {}
    if node_type == 'navigation':
        target = data.get('target_node_label') or data.get('target_node_id')
        if not target:
            raise NotAStepList(f"navigation block {node.get('id')} has no target")
        return {'type': 'navigation', 'target': target}
    if node_type == 'sleep' or (node_type not in ('action', 'verification') and data.get('command') == 'sleep'):
        return {'type': 'wait', 'ms': int((data.get('params') or {}).get('duration') or 1000)}
    if node_type in ('action', 'verification'):
        key = 'actions' if node_type == 'action' else 'verifications'
        items = [{'command': it.get('command'), 'params': it.get('params') or {}}
                 for it in (data.get(key) or []) if it.get('command')]
        if not items:
            raise NotAStepList(f"{node_type} block {node.get('id')} is empty")
        return {'type': node_type, 'items': items}
    raise NotAStepList(f"block type '{node_type}' cannot be written as a step")


def graph_to_steps(graph: Dict[str, Any]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Walk START's success chain. Returns [(step, node)] in run order; raises NotAStepList."""
    nodes = {n.get('id'): n for n in (graph or {}).get('nodes', [])}
    edges = (graph or {}).get('edges', [])

    def target(source: str, handle: str) -> Optional[str]:
        return next((e.get('target') for e in edges
                     if e.get('source') == source and (e.get('sourceHandle') or 'success') == handle), None)

    start = next((n for n in nodes.values() if n.get('type') == 'start'), None)
    if not start:
        raise NotAStepList('the graph has no START block')
    for e in edges:
        if e.get('sourceHandle') not in (None, 'success', 'failure'):
            raise NotAStepList(f"edge {e.get('id')} uses a '{e.get('sourceHandle')}' branch")

    out: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    seen = set()
    current = target(start['id'], 'success')
    while current:
        node = nodes.get(current)
        if not node:
            raise NotAStepList(f'edge to missing block {current}')
        if node.get('type') == 'success':
            break
        if node.get('type') in ('failure', 'break_success', 'loop'):
            raise NotAStepList(f"the chain reaches a '{node.get('type')}' block")
        if current in seen:
            raise NotAStepList('the graph has a cycle')
        seen.add(current)

        step = _node_to_step(node)
        next_id = target(current, 'success')
        fail_id = target(current, 'failure')
        fail_node = nodes.get(fail_id) if fail_id else None
        if fail_node and fail_node.get('type') != 'failure':
            if fail_id != next_id:
                raise NotAStepList(f"block {current} fails to a block other than the next one")
            step['continue_on_fail'] = True
        out.append((step, node))
        current = next_id
    if len(seen) != len([n for n in nodes.values()
                         if n.get('type') not in ('start', 'success', 'failure')]):
        raise NotAStepList('some blocks are not on the main chain')
    return out
