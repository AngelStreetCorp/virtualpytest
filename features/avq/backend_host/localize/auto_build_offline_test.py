#!/usr/bin/env python3
"""
OFFLINE autonomous-builder test — no device, no DB, no OpenAI.

Drives the REAL builder logic (AutoUIBuilder) against a ReplayAdapter (a simulated STB
built from an exported fixture) + a MemorySink, then diffs the rebuilt graph against the
fixture ground truth. Deterministic and free.

Usage:
    python3 features/avq/backend_host/localize/auto_build_offline_test.py [FIXTURE_DIR] [MAX_DEPTH]
    # default FIXTURE_DIR = features/avq/backend_host/localize/fixtures/example_tv
    # MAX_DEPTH = semantic screen depth (omit = unlimited): D-pad focus moves stay at the
    #             same depth and OK enters the next depth. A bare integer works.
"""
import os
import sys

# Load the pure builder modules WITHOUT the heavy backend_host package __init__ chain
# (which pulls appium/selenium/cv2). Same trick as localize_offline_test.py.
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, '..', '..', 'lib', 'auto_builder')
sys.path.insert(0, os.path.abspath(PKG))

from device_adapter import ReplayAdapter            # noqa: E402
from graph_sink import MemorySink                    # noqa: E402
from auto_ui_builder import AutoUIBuilder            # noqa: E402
from graph_diff import diff_graphs, print_diff       # noqa: E402
from graph_report import text_tree, html_report, discovery_list, steps_text, walk_text  # noqa: E402

# coverage gates (offline must meet these or the test fails)
MIN_NODE_COVERAGE = 0.60
MIN_EDGE_COVERAGE = 0.50


def main():
    # Positional args in any order: a bare integer = MAX_DEPTH, anything else = FIXTURE_DIR.
    fixture = os.path.join(HERE, 'fixtures', 'example_tv')
    max_depth = None
    for a in sys.argv[1:]:
        if a.isdigit():
            max_depth = int(a)
        else:
            fixture = a
    if not os.path.exists(os.path.join(fixture, 'graph.json')):
        print(f"❌ no fixture at {fixture} — run export_ui_fixture.py first")
        sys.exit(2)

    print(f"=== OFFLINE auto-build over {fixture} "
          f"(depth={'∞' if max_depth is None else max_depth}) ===")
    adapter = ReplayAdapter(fixture, start_label='home')
    sink = MemorySink('example_tv_autobuild')
    # One key at a time, each (node,key) once. D-pad stays at the current semantic depth;
    # OK enters the next depth.
    builder = AutoUIBuilder(adapter, sink, start_label='home', max_depth=max_depth)
    res = builder.build()
    print(f"\nbuild: {res['nodes']} nodes, {res['edges']} edges, "
          f"{res['iterations']} steps, {res['presses']} presses, {res['duration_ms']} ms")

    truth_nodes = set(adapter.ground_truth_nodes())
    truth_edges = adapter.ground_truth_edges()
    # only score edges whose endpoints are both real (drop dup/cruft labels)
    truth_edges = {(s, t) for (s, t) in truth_edges
                   if s in truth_nodes and t in truth_nodes}

    d = diff_graphs(sink.node_labels(), sink.edge_label_pairs(),
                    truth_nodes, truth_edges)
    print()
    print_diff(d)

    # --- report: key-by-key walk + per-node steps + discovery list + tree ------
    walk = walk_text(res)
    steps = steps_text(res)
    disco = discovery_list(sink.nodes)
    tree = text_tree(sink.nodes, sink.edges, root='home')
    print("\n=== WALK (one key per step) ===")
    print(walk)
    print("\n=== STEPS (per node) ===")
    print(steps)
    print("\n=== REBUILT TREE ===")
    print(tree)

    out_txt = os.path.join(fixture, 'auto_build_report.txt')
    out_html = os.path.join(fixture, 'auto_build_report.html')
    with open(out_txt, 'w') as f:
        f.write("WALK (one key per step)\n" + walk + "\n\nSTEPS (per node)\n" + steps
                + "\n\nDISCOVERY ORDER\n" + disco + "\n\nTREE\n" + tree + "\n")
    with open(out_html, 'w') as f:
        f.write(html_report(sink.nodes, sink.edges,
                            os.path.join(fixture, 'screenshots'),
                            title='example_tv_autobuild (offline)',
                            diff=d, tree_text=tree, result=res,
                            dom_dir=os.path.join(fixture, 'dom')))
    print(f"\nreport: {out_txt}\n        {out_html}")

    ok = (d['nodes']['coverage'] >= MIN_NODE_COVERAGE and
          d['edges']['coverage'] >= MIN_EDGE_COVERAGE)
    print(f"\n{'✅ PASS' if ok else '❌ FAIL'}  "
          f"(node>={MIN_NODE_COVERAGE}, edge>={MIN_EDGE_COVERAGE})")
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
