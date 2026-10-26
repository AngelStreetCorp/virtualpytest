"""Block catalogue and page-definition rules for custom pages (TASK-139).

A page definition is plain data:

    {"schema_version": 1,
     "blocks": [{"id": "b1", "type": "device_picker", "x": 0, "w": 2, "settings": {"model_filter": "stb"}},
                {"id": "b2", "type": "node_goto", "x": 2, "w": 4, "settings": {"device_from": "b1"}}]}

The catalogue below is the ONLY thing a page can contain. It is validated on save, on load and by the
Atlas tools; an unknown block type, an unknown setting or a bad value is refused with the reason, never
silently fixed. Every block lists ``requires``: the permission(s) of the page that offers the same feature
by hand. A page can therefore never reach more than its viewer could already open: a block the caller lacks
is refused when it is added, and shows as locked when a viewer lacks it.

The frontend renders the same block types (frontend/src/components/customPages/blocks.tsx); a type added
here needs a renderer there.
"""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any, Callable, Dict, List, Optional

SCHEMA_VERSION = 1
GRID_COLUMNS = 6
MAX_BLOCKS = 24
TITLE_MAX = 120
TEXT_MAX = 2000

Holds = Callable[[str], bool]

# type -> definition. settings[name] = {'type': enum|string|int|bool|ref|uuid, ...}
BLOCKS: Dict[str, Dict[str, Any]] = {
    'device_picker': {
        'title': 'Device picker',
        'description': 'Dropdown of the devices you may use. Other blocks read the chosen device. '
                       'model_filter limits the list (stb, mobile, tv, web).',
        'requires': ['device_control:view'],
        'w': 2,
        'settings': {
            'model_filter': {'type': 'enum', 'values': ['any', 'stb', 'mobile', 'tv', 'web'], 'default': 'any'},
        },
    },
    'node_goto': {
        'title': 'Go to node',
        'description': 'Pick a navigation node and go there on the chosen device (takes control of the device).',
        'requires': ['device_control:execute'],
        'w': 3,
        'needs_device': True,
        'settings': {
            'device_from': {'type': 'ref', 'ref_type': 'device_picker'},
        },
    },
    'localize_result': {
        'title': 'Localize result',
        'description': 'Which navigation node the live screen of the chosen device matches, with the ranked candidates.',
        'requires': ['device_control:execute'],
        'w': 3,
        'needs_device': True,
        'settings': {
            'device_from': {'type': 'ref', 'ref_type': 'device_picker'},
            'userinterface': {'type': 'string', 'max': 120, 'default': ''},
        },
    },
    'stream': {
        'title': 'Live stream',
        'description': 'Live view of the chosen device.',
        'requires': ['device_control:view'],
        'w': 3,
        'needs_device': True,
        'settings': {
            'device_from': {'type': 'ref', 'ref_type': 'device_picker'},
        },
    },
    'recent_runs': {
        'title': 'Recent runs',
        'description': 'The latest script runs on the chosen device (or every device when none is chosen).',
        'requires': ['reports.tests:view'],
        'w': 3,
        'settings': {
            'device_from': {'type': 'ref', 'ref_type': 'device_picker', 'optional': True},
            'limit': {'type': 'int', 'min': 1, 'max': 20, 'default': 5},
        },
    },
    'report': {
        'title': 'Saved report',
        'description': 'Runs a saved custom report (Test Reports > Custom reports) and shows its table.',
        'requires': ['reports.tests:view'],
        'w': 6,
        'settings': {
            'report_id': {'type': 'uuid', 'required': True},
        },
    },
    'text': {
        'title': 'Text',
        'description': 'A heading or a short note. Plain text only.',
        'requires': [],
        'w': 3,
        'settings': {
            'text': {'type': 'string', 'max': TEXT_MAX, 'default': ''},
            'heading': {'type': 'bool', 'default': False},
        },
    },
}


class DefinitionError(ValueError):
    """A page definition (or an edit of one) the catalogue refuses; the message names the block and why."""

    def __init__(self, message: str, status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra

    def to_dict(self) -> Dict[str, Any]:
        return {'error': self.message, **self.extra}


def empty_definition() -> Dict[str, Any]:
    return {'schema_version': SCHEMA_VERSION, 'blocks': []}


def missing_permissions(block_type: str, holds: Holds) -> List[str]:
    return [p for p in BLOCKS[block_type]['requires'] if not holds(p)]


def catalogue_for(holds: Holds) -> Dict[str, List[Dict[str, Any]]]:
    """The catalogue as the caller may use it: `available` blocks and `unavailable` ones with the reason."""
    available: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    for block_type, spec in BLOCKS.items():
        entry = {
            'type': block_type,
            'title': spec['title'],
            'description': spec['description'],
            'requires': list(spec['requires']),
            'default_width': spec['w'],
            'settings': copy.deepcopy(spec['settings']),
        }
        missing = missing_permissions(block_type, holds)
        if missing:
            entry['missing'] = missing
            entry['reason'] = f"needs {', '.join(missing)}; ask a team admin"
            unavailable.append(entry)
        else:
            available.append(entry)
    return {'available': available, 'unavailable': unavailable}


def block_states(definition: Dict[str, Any], holds: Holds) -> Dict[str, Dict[str, Any]]:
    """Per block id: whether the caller may use it, and the permissions missing (viewer-side locked state)."""
    states: Dict[str, Dict[str, Any]] = {}
    for block in definition.get('blocks') or []:
        spec = BLOCKS.get(block.get('type'))
        missing = missing_permissions(block['type'], holds) if spec else []
        states[block['id']] = {'available': bool(spec) and not missing, 'missing': missing}
    return states


def locked_count(definition: Dict[str, Any], holds: Holds) -> int:
    return sum(1 for s in block_states(definition, holds).values() if not s['available'])


def _check_setting(block_id: str, name: str, spec: Dict[str, Any], value: Any) -> Any:
    kind = spec['type']
    where = f"block {block_id} setting '{name}'"
    if kind == 'enum':
        if value not in spec['values']:
            raise DefinitionError(f"{where} must be one of {', '.join(spec['values'])}")
        return value
    if kind == 'string':
        if not isinstance(value, str):
            raise DefinitionError(f'{where} must be text')
        if len(value) > spec['max']:
            raise DefinitionError(f"{where} is longer than {spec['max']} characters")
        return value
    if kind == 'int':
        if isinstance(value, bool) or not isinstance(value, int) or not spec['min'] <= value <= spec['max']:
            raise DefinitionError(f"{where} must be a whole number from {spec['min']} to {spec['max']}")
        return value
    if kind == 'bool':
        if not isinstance(value, bool):
            raise DefinitionError(f'{where} must be true or false')
        return value
    if kind == 'uuid':
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            raise DefinitionError(f'{where} must be an id (UUID)')
    if kind == 'ref':
        if not isinstance(value, str) or not value:
            raise DefinitionError(f'{where} must be the id of a {spec["ref_type"]} block')
        return value
    raise DefinitionError(f'{where}: unsupported setting type')  # pragma: no cover - catalogue bug


_ID = re.compile(r'^[A-Za-z0-9_-]{1,40}$')


def _next_id(taken: set) -> str:
    n = 1
    while f'b{n}' in taken:
        n += 1
    return f'b{n}'


def normalize_definition(raw: Any, *, previous: Optional[Dict[str, Any]] = None,
                         holds: Optional[Holds] = None) -> Dict[str, Any]:
    """Validate `raw` and return the canonical definition (defaults filled in, x/w placed, ids assigned).

    `holds` (the caller's permission test) is applied only to blocks that are new or changed compared with
    `previous`, so a collaborator can still edit a page that contains a block they may not use themselves.
    """
    if not isinstance(raw, dict):
        raise DefinitionError('definition must be an object')
    version = raw.get('schema_version', SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise DefinitionError(f'unsupported schema_version {version!r} (this server reads {SCHEMA_VERSION})')
    blocks_in = raw.get('blocks', [])
    if not isinstance(blocks_in, list):
        raise DefinitionError('blocks must be a list')
    if len(blocks_in) > MAX_BLOCKS:
        raise DefinitionError(f'a page holds at most {MAX_BLOCKS} blocks')

    previous_by_id = {b.get('id'): b for b in (previous or {}).get('blocks', []) if isinstance(b, dict)}
    taken = {b.get('id') for b in blocks_in if isinstance(b, dict) and isinstance(b.get('id'), str)}
    out: List[Dict[str, Any]] = []
    seen: set = set()
    cursor = 0  # next free column when x is not given
    for index, block in enumerate(blocks_in):
        if not isinstance(block, dict):
            raise DefinitionError(f'block {index + 1} must be an object')
        block_type = block.get('type')
        spec = BLOCKS.get(block_type)
        if spec is None:
            raise DefinitionError(f"block {index + 1}: unknown block type {block_type!r}; known types: {', '.join(BLOCKS)}")
        block_id = block.get('id') or _next_id(taken | seen)
        if not isinstance(block_id, str) or not _ID.match(block_id):
            raise DefinitionError(f'block {index + 1}: id must be letters, digits, - or _ (max 40)')
        if block_id in seen:
            raise DefinitionError(f'block id {block_id} is used twice')
        seen.add(block_id)

        width = block.get('w', spec['w'])
        if isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= GRID_COLUMNS:
            raise DefinitionError(f'block {block_id}: w must be a whole number from 1 to {GRID_COLUMNS}')
        x = block.get('x')
        if x is None:
            x = cursor if cursor + width <= GRID_COLUMNS else 0
        if isinstance(x, bool) or not isinstance(x, int) or x < 0 or x + width > GRID_COLUMNS:
            raise DefinitionError(f'block {block_id}: x + w must fit in {GRID_COLUMNS} columns')
        cursor = x + width if x + width < GRID_COLUMNS else 0

        given = block.get('settings') or {}
        if not isinstance(given, dict):
            raise DefinitionError(f'block {block_id}: settings must be an object')
        unknown = set(given) - set(spec['settings'])
        if unknown:
            raise DefinitionError(f"block {block_id} ({block_type}): unknown setting {', '.join(sorted(unknown))}; "
                                  f"known: {', '.join(spec['settings']) or 'none'}")
        settings: Dict[str, Any] = {}
        for name, sspec in spec['settings'].items():
            if name in given and given[name] is not None:
                settings[name] = _check_setting(block_id, name, sspec, given[name])
            elif 'default' in sspec:
                settings[name] = sspec['default']
        out.append({'id': block_id, 'type': block_type, 'x': x, 'w': width, 'settings': settings})

    # Wire blocks to the device picker they read (auto-wire when exactly one picker exists).
    ids_by_type: Dict[str, List[str]] = {}
    for b in out:
        ids_by_type.setdefault(b['type'], []).append(b['id'])
    for b in out:
        for name, sspec in BLOCKS[b['type']]['settings'].items():
            if sspec['type'] != 'ref':
                continue
            candidates = ids_by_type.get(sspec['ref_type'], [])
            current = b['settings'].get(name)
            if current is None:
                if len(candidates) == 1:
                    b['settings'][name] = candidates[0]
                elif sspec.get('optional'):
                    continue
                elif not candidates:
                    raise DefinitionError(f"block {b['id']} ({b['type']}) needs a {sspec['ref_type']} block on the page; add one first")
                else:
                    raise DefinitionError(f"block {b['id']} ({b['type']}): set '{name}' to one of {', '.join(candidates)}")
            elif current not in candidates:
                raise DefinitionError(f"block {b['id']}: '{name}' must be the id of a {sspec['ref_type']} block, got {current!r}")

    if holds is not None:
        for b in out:
            before = previous_by_id.get(b['id'])
            if before and before.get('type') == b['type'] and before.get('settings') == b['settings']:
                continue
            missing = missing_permissions(b['type'], holds)
            if missing:
                raise DefinitionError(
                    f"block {b['id']} ({b['type']}) needs {', '.join(missing)}, which you do not hold; ask a team admin",
                    status=403, block=b['id'], block_type=b['type'], missing=missing)
    return {'schema_version': SCHEMA_VERSION, 'blocks': out}


def apply_ops(definition: Dict[str, Any], ops: Any) -> Dict[str, Any]:
    """Apply small edits (what Atlas sends) to a definition; the caller re-validates the result.

    add_block {type, settings?, x?, w?, id?}   remove_block {id}
    set_setting {id, key, value}               move_block {id, x?, w?, to_index?}
    """
    if not isinstance(ops, list) or not ops:
        raise DefinitionError('ops must be a non-empty list')
    result = copy.deepcopy(definition)
    blocks: List[Dict[str, Any]] = result.setdefault('blocks', [])

    def find(block_id: Any) -> Dict[str, Any]:
        for b in blocks:
            if b['id'] == block_id:
                return b
        raise DefinitionError(f'no block with id {block_id!r} on this page; ids: {", ".join(b["id"] for b in blocks) or "none"}')

    for number, op in enumerate(ops, 1):
        kind = op.get('op') if isinstance(op, dict) else None
        if kind == 'add_block':
            if op.get('type') not in BLOCKS:
                raise DefinitionError(f"op {number}: unknown block type {op.get('type')!r}; known types: {', '.join(BLOCKS)}")
            block = {k: op[k] for k in ('id', 'type', 'x', 'w', 'settings') if k in op}
            blocks.append(block)
        elif kind == 'remove_block':
            blocks.remove(find(op.get('id')))
            # a removed picker leaves its readers unwired: validation reports it
            for b in blocks:
                for name, value in list(b.get('settings', {}).items()):
                    if value == op.get('id'):
                        del b['settings'][name]
        elif kind == 'set_setting':
            find(op.get('id')).setdefault('settings', {})[op.get('key')] = op.get('value')
        elif kind == 'move_block':
            block = find(op.get('id'))
            for key in ('x', 'w'):
                if key in op:
                    block[key] = op[key]
            if 'to_index' in op:
                blocks.remove(block)
                blocks.insert(max(0, min(int(op['to_index']), len(blocks))), block)
        else:
            raise DefinitionError(f"op {number}: unknown op {kind!r}; use add_block, remove_block, set_setting or move_block")
    return result
