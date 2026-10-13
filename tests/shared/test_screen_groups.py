"""TASK-27 step 4k: screen groups derived from the navigation tree (core, pure).

Nodes joined only by purely directional edges (LEFT/RIGHT/UP/DOWN + waits) are one screen;
OK, BACK, HOME, digits, clicks start a new screen; empty edges are unknown. The group is
named after the node entered from outside by a non-directional edge, else the shortest
label. The row adapter (DB rows) and the graph adapter (the executor's unified graph) must
give the same groups.
"""
import os
import sys

import networkx as nx
import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.src.lib.ai import screen_groups as sg  # noqa: E402
from shared.src.lib.ai import training_samples  # noqa: E402

pytestmark = pytest.mark.unit


def key(k):
    return {'command': 'press_key', 'params': {'key': k}}


WAIT = {'command': 'wait', 'params': {'duration': 1}}


def node(nid, label=None, node_type='screen', text=None, **extra):
    row = {'node_id': nid, 'label': label or nid, 'node_type': node_type, 'data': {},
           'verifications': []}
    if text:
        row['verifications'] = [{'command': 'waitForTextToAppear', 'verification_type': 'text',
                                 'params': {'text': text}}]
    row.update(extra)
    return row


def edge(src, tgt, forward, reverse=None, set_id=None, **extra):
    set_id = set_id or f'{src}_{tgt}'
    sets = [{'id': set_id, 'actions': forward}]
    if reverse is not None:
        sets.append({'id': f'{tgt}_{src}', 'actions': reverse})
    row = {'edge_id': f'e-{src}-{tgt}', 'source_node_id': src, 'target_node_id': tgt,
           'action_sets': sets, 'default_action_set_id': set_id}
    row.update(extra)
    return row


TABS = ['home_tvguide', 'home_apps', 'home_replay', 'home_movies', 'home_recodings',
        'home_tvshop', 'home_settings', 'home_profile']


def stb_tree():
    """The live stb_tv shape (TASK-27 step 4k): Home tabs chained by RIGHT, OK into screens."""
    nodes = [node('entry-node', 'ENTRY', node_type='entry'), node('home'), node('live'),
             node('apps'), node('replay'), node('settings'),
             node('apps_netflix'), node('apps_disney'), node('apps_youtube')]
    nodes += [node(t) for t in TABS]
    edges = [edge('entry-node', 'home', [key('BACK'), key('TVGUIDE'), key('TVGUIDE'), key('HOME')]),
             edge('home', 'home_tvguide', [key('RIGHT')], [key('LEFT')])]
    chain = TABS
    for a, b in zip(chain, chain[1:]):
        if (a, b) == ('home_apps', 'home_replay'):
            edges.append(edge(a, b, [key('RIGHT'), WAIT], [key('LEFT')]))
        elif (a, b) == ('home_replay', 'home_movies'):
            edges.append(edge(a, b, [key('RIGHT')]))
        elif (a, b) == ('home_movies', 'home_recodings'):
            edges.append(edge(a, b, [key('RIGHT')]))
        else:
            edges.append(edge(a, b, [key('RIGHT')], [key('LEFT')]))
    edges += [edge('home_apps', 'apps', [key('OK')], [key('BACK')]),
              edge('home_replay', 'replay', [key('OK')], [key('BACK')]),
              edge('home_settings', 'settings', [key('OK')], [key('BACK')]),
              edge('home', 'live', [key('BACK')]),
              edge('apps', 'apps_netflix', [key('DOWN')], [key('UP')]),
              edge('apps_netflix', 'apps_disney', [key('RIGHT')], [key('LEFT')]),
              edge('apps_disney', 'apps_youtube', [key('KEYCODE_DPAD_RIGHT')])]
    return nodes, edges


def labels_of(groups, gid):
    return [m['label'] for m in groups.groups[gid]['members']]


def test_directional_edges_join_and_ok_splits():
    groups = sg.from_rows(*stb_tree())
    assert labels_of(groups, 'home') == ['home'] + sorted(TABS)
    assert labels_of(groups, 'apps') == ['apps', 'apps_disney', 'apps_netflix', 'apps_youtube']
    for alone in ('live', 'replay', 'settings'):
        assert labels_of(groups, alone) == [alone]
    assert groups.group_of('home_settings')['label'] == 'home'
    assert 'entry-node' not in groups          # the entry node is never a screen


def test_action_kinds():
    assert sg.action_kind([key('RIGHT')]) == sg.DIRECTIONAL
    assert sg.action_kind([WAIT, key('dpad_left'), WAIT]) == sg.DIRECTIONAL
    assert sg.action_kind([key('ArrowDown')]) == sg.DIRECTIONAL
    assert sg.action_kind([key('RIGHT'), key('OK')]) == sg.OTHER
    assert sg.action_kind([key('BACK')]) == sg.OTHER
    assert sg.action_kind([key('1')]) == sg.OTHER
    assert sg.action_kind([{'command': 'click_element', 'params': {'text': 'Apps'}}]) == sg.OTHER
    assert sg.action_kind([]) == sg.UNKNOWN
    assert sg.action_kind([WAIT]) == sg.UNKNOWN


def test_empty_action_edges_never_group():
    nodes = [node('home'), node('home_apps'), node('home_recodings')]
    edges = [edge('home', 'home_apps', [key('RIGHT')]),
             edge('home_apps', 'home_recodings', [], [])]
    groups = sg.from_rows(nodes, edges)
    assert labels_of(groups, 'home') == ['home', 'home_apps']
    assert labels_of(groups, 'home_recodings') == ['home_recodings']


def test_reverse_set_joins_like_the_graph():
    nodes = [node('menu'), node('menu_b')]
    edges = [edge('menu', 'menu_b', [], [key('UP')])]   # forward unknown, reverse directional
    assert labels_of(sg.from_rows(nodes, edges), 'menu') == ['menu', 'menu_b']


def test_hidden_in_base_rows_are_ignored():
    nodes = [node('home'), node('home_apps'), node('ghost', hidden_in_base=True)]
    edges = [edge('home', 'home_apps', [key('RIGHT')], hidden_in_base=True),
             edge('home', 'ghost', [key('RIGHT')])]
    groups = sg.from_rows(nodes, edges)
    assert labels_of(groups, 'home') == ['home']
    assert 'ghost' not in groups


def test_nested_trees_share_node_ids():
    """A nested subtree repeats its parent node (same node_id): one node, one group."""
    root = [node('home'), node('apps')]
    nested = [node('apps', data={'isParentReference': True}), node('apps_netflix')]
    edges = [edge('home', 'apps', [key('OK')]), edge('apps', 'apps_netflix', [key('DOWN')])]
    groups = sg.from_rows(root + nested, edges)
    assert labels_of(groups, 'apps') == ['apps', 'apps_netflix']


def test_representative_is_the_node_entered_from_outside():
    nodes = [node('a_long_name'), node('b'), node('c')]
    edges = [edge('c', 'a_long_name', [key('OK')]),
             edge('a_long_name', 'b', [key('RIGHT')])]
    groups = sg.from_rows(nodes, edges)
    assert groups.group_of('b')['label'] == 'a_long_name'   # entered from c by OK


def test_representative_tie_is_the_shortest_label():
    # home entered by ENTRY, home_apps entered back from apps (BACK): shortest wins.
    groups = sg.from_rows(*stb_tree())
    assert groups.group_of('home_apps')['node_id'] == 'home'
    nodes = [node('xx'), node('yy_long'), node('zz')]
    edges = [edge('xx', 'yy_long', [key('LEFT')])]           # nobody entered: shortest, then a-z
    assert sg.from_rows(nodes, edges).group_of('yy_long')['label'] == 'xx'


def test_focus_from_text_verification_else_suffix_and_none_for_the_group():
    nodes, edges = stb_tree()
    for n in nodes:
        if n['node_id'] == 'home_apps':
            n['verifications'] = [
                {'command': 'waitForTextToDisappear', 'params': {'text': 'Loading'}},
                {'command': 'waitForTextToAppear', 'verification_type': 'text', 'params': {'text': ' Apps '}}]
    groups = sg.from_rows(nodes, edges)
    assert groups.focus_of('home') is None
    assert groups.focus_of('home_apps') == 'Apps'
    assert groups.focus_of('home_settings') == 'settings'
    assert groups.focus_of('apps_netflix') == 'netflix'


def test_overrides_split_and_merge():
    nodes, edges = stb_tree()
    groups = sg.from_rows(nodes, edges, {'home_profile': 'home_profile', 'live': 'home',
                                         'apps_youtube': 'nowhere'})
    assert labels_of(groups, 'home_profile') == ['home_profile']
    assert groups.group_of('live')['label'] == 'home'
    assert groups.focus_of('live') == 'live'                  # no home_ prefix: the full label
    assert groups.group_of('apps_youtube')['label'] == 'apps'  # bad override ignored...
    assert any('nowhere' in w for w in groups.warnings)        # ...and reported


def test_a_text_check_shared_across_the_group_is_not_a_focus():
    """Live stb_tv: Home and several tabs check "Home|Startseite", home_apps checks "Home":
    those prove the screen, not the tab, so the label suffix is the focus."""
    nodes, edges = stb_tree()
    texts = {'home': 'Home|Startseite', 'home_movies': 'Home|Startseite', 'home_apps': 'Home',
             'home_replay': 'Replay'}
    for n in nodes:
        if n['node_id'] in texts:
            n['verifications'] = [{'command': 'waitForTextToAppear', 'verification_type': 'text',
                                   'params': {'text': texts[n['node_id']]}}]
    groups = sg.from_rows(nodes, edges)
    assert groups.focus_of('home_movies') == 'movies'
    assert groups.focus_of('home_apps') == 'apps'
    assert groups.focus_of('home_replay') == 'Replay'      # unique in the group: a focus text


def test_override_merges_a_node_into_the_group_of_any_member_and_renames():
    """Live stb_tv: apps -> apps_netflix is DOWN, HOME, DOWN (not directional), so the tiles
    form their own group; one override puts the Apps screen with its tiles, named apps."""
    nodes, edges = stb_tree()
    for e in edges:
        if (e['source_node_id'], e['target_node_id']) == ('apps', 'apps_netflix'):
            e['action_sets'][0]['actions'] = [key('DOWN'), key('HOME'), key('DOWN')]
            e['action_sets'][1]['actions'] = [key('DOWN'), key('HOME'), key('DOWN')]
    derived = sg.from_rows(nodes, edges)
    assert 'apps_netflix' not in [m['node_id'] for m in derived.groups['apps']['members']]
    groups = sg.from_rows(nodes, edges, {'apps': 'apps_netflix'})
    assert labels_of(groups, 'apps') == ['apps', 'apps_disney', 'apps_netflix', 'apps_youtube']
    assert groups.focus_of('apps_netflix') == 'netflix'


def test_override_moving_the_representative_repicks():
    nodes, edges = stb_tree()
    groups = sg.from_rows(nodes, edges, {'home': 'apps'})
    assert groups.group_of('home')['label'] == 'apps'
    assert groups.group_of('home_apps')['label'] == 'home_apps'   # home_apps entered back from apps (BACK)


def test_graph_and_rows_give_the_same_groups():
    nodes, edges = stb_tree()
    g = nx.DiGraph()
    for n in nodes:
        g.add_node(n['node_id'], label=n['label'], node_type=n['node_type'],
                   verifications=n['verifications'])
    for e in edges:
        sets = e['action_sets']
        if sets[0]['actions']:
            g.add_edge(e['source_node_id'], e['target_node_id'], action_sets=sets,
                       default_action_set_id=e['default_action_set_id'])
        if len(sets) > 1 and sets[1]['actions']:
            g.add_edge(e['target_node_id'], e['source_node_id'], action_sets=[sets[1]],
                       default_action_set_id=sets[1]['id'], is_reverse_edge=True)
    # a sibling shortcut (synthetic, copies a click edge) never joins
    g.add_node('x', label='x', node_type='screen', verifications=[])
    g.add_edge('live', 'x', action_sets=[{'id': 's', 'actions': [key('RIGHT')]}],
               default_action_set_id='s', is_sibling_shortcut=True)
    from_graph = sg.from_graph(g).to_list()
    from_rows = sg.from_rows(nodes, edges).to_list()
    assert [x for x in from_graph if x['node_id'] != 'x'] == from_rows
    assert sg.from_graph(g).group_of('x')['label'] == 'x'


def test_conditional_edge_borrows_its_sibling_actions():
    nodes = [node('a'), node('b'), node('c')]
    main = edge('a', 'b', [key('RIGHT')], set_id='shared')
    sibling = edge('a', 'c', [], set_id='shared')
    groups = sg.from_rows(nodes, [main, sibling])
    assert labels_of(groups, 'a') == ['a', 'b', 'c']


def test_label_for_and_entries():
    groups = sg.from_rows(*stb_tree())
    assert groups.label_for('home_apps') == {'node_id': 'home', 'label': 'home', 'node': 'home_apps',
                                             'node_label': 'home_apps', 'focus': 'apps'}
    assert groups.label_for('home') == {'node_id': 'home', 'label': 'home', 'node': 'home',
                                        'node_label': 'home', 'focus': None}
    assert groups.label_for('nope') is None
    names = [e['label'] for e in groups.entries()]
    assert names == ['apps', 'home', 'live', 'replay', 'settings']


def test_regroup_label_converts_old_labels_and_is_idempotent():
    groups = sg.from_rows(*stb_tree())
    old = {'node_id': 'home_apps', 'label': 'home_apps'}
    new = sg.regroup_label(old, groups)
    assert new == groups.label_for('home_apps')
    assert sg.regroup_label(new, groups) == new
    # a human-corrected focus stays while the group is unchanged
    human = dict(new, focus='Apps store')
    assert sg.regroup_label(human, groups)['focus'] == 'Apps store'
    # off-tree, stale and non-dict labels are left alone
    assert sg.regroup_label({'node_id': None, 'label': 'popup'}, groups) == {'node_id': None, 'label': 'popup'}
    assert sg.regroup_label({'node_id': 'gone', 'label': 'gone'}, groups) == {'node_id': 'gone', 'label': 'gone'}
    assert sg.regroup_label(None, groups) is None
    assert sg.regroup_label(old, None) == old


def test_grouped_labels_compare_by_group_in_core():
    """is_failure and the conflict key see the group only (node / focus are annotations)."""
    groups = sg.from_rows(*stb_tree())
    a, b = groups.label_for('home_apps'), groups.label_for('home_settings')
    assert training_samples._label_key('screen-id', a) == training_samples._label_key('screen-id', b)
    assert not training_samples._differs({'node_id': 'home', 'label': 'home'}, a)
    assert training_samples._differs({'node_id': 'apps', 'label': 'apps'}, a)
    # two near-identical frames of Home with different tabs: not a conflict
    h = 'f' * 64
    rows = [{'id': '1', 'family': 'screen-id', 'device_model': 'stb', 'dhash': h, 'ground_truth': a,
             'label_conflict': True},
            {'id': '2', 'family': 'screen-id', 'device_model': 'stb', 'dhash': h, 'ground_truth': b,
             'label_conflict': True}]
    assert training_samples.recompute_conflict_flags(rows) == ([], ['1', '2'])


def test_core_overrides_stb_tv_profile_picker_and_apps():
    """Step 4k data in core: ge joins en in profile; apps joins its tiles."""
    ov = sg.overrides_for('stb_tv')
    assert ov == {'apps': 'apps_netflix', 'ge': 'en'} and sg.overrides_for('web_tv') == {}
    ov['x'] = 'y'                                                   # a copy
    assert 'x' not in sg.SCREEN_GROUP_OVERRIDES['stb_tv']
    nodes = [node('profile'), node('en', text='En'), node('ge', text='Geteilt'), node('home_profile')]
    edges = [edge('home_profile', 'profile', [key('OK')], [key('BACK')]),
             edge('profile', 'en', [key('DOWN')], [key('UP')]),
             edge('profile', 'ge', [key('OK')])]
    groups = sg.from_rows(nodes, edges, sg.overrides_for('stb_tv'))
    assert labels_of(groups, 'profile') == ['profile', 'en', 'ge']
    assert (groups.focus_of('en'), groups.focus_of('ge')) == ('En', 'Geteilt')
    plain = sg.from_rows([dict(n, verifications=[]) for n in nodes], edges, sg.overrides_for('stb_tv'))
    assert (plain.focus_of('en'), plain.focus_of('ge')) == ('en', 'ge')   # no text check: the label


def test_feature_reads_the_overrides_from_core():
    import importlib
    scope = importlib.import_module('features.ai-dataset.lib.screen_group_scope')
    assert scope.SCREEN_GROUP_OVERRIDES is sg.SCREEN_GROUP_OVERRIDES
    assert scope.overrides_for('stb_tv') == sg.overrides_for('stb_tv')
