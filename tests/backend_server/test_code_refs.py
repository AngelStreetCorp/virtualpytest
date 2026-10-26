"""code_refs index + query on a tiny fixture repo (features/code-graph, docs/agent/Graphify.md)."""
import importlib
import textwrap

import pytest

pytestmark = pytest.mark.unit  # no live server needed

build = importlib.import_module('features.code-graph.lib.code_index.build')
query = importlib.import_module('features.code-graph.lib.code_index.query')
store = importlib.import_module('features.code-graph.lib.code_index.store')
tools = importlib.import_module('features.code-graph.backend_server.mcp_tools.code_refs_tools')

FILES = {
    'pkg/__init__.py': '',
    'pkg/util.py': '''
        def call_host(host, endpoint):
            return helper(endpoint)

        def helper(x):
            return x
        ''',
    'pkg/executor.py': '''
        class NavigationExecutor:
            def execute_navigation(self, node):
                return self.prepare(node)

            def prepare(self, node):
                return node
        ''',
    'pkg/other.py': '''
        class Other:
            def execute_navigation(self):
                return 1
        ''',
    'pkg/routes.py': '''
        from flask import Blueprint
        from pkg.util import call_host

        bp = Blueprint('ctl', __name__, url_prefix='/server/control')

        @bp.route('/navigate/<tree_id>', methods=['POST'])
        def navigate(tree_id):
            # call_host() in a comment is not a call
            text = "call_host() in a string is not a call"
            return call_host('h', '/host/navigation/execute')
        ''',
    'pkg/service.py': '''
        from pkg import util

        def run_job(device):
            device.navigation_executor.execute_navigation('home')
            return util.call_host('h', '/x')

        def outer():
            return run_job(None)
        ''',
    'pkg/nested.py': '''
        from pkg.util import call_host

        class Mgr:
            def poll(self):
                def _check(h):
                    return call_host(h, '/e')
                return _check('a')
        ''',
    'pkg/elsewhere.py': '''
        def _check(x):
            return x

        def caller():
            return _check(1)
        ''',
    'pkg/store.py': '''
        class RunStore:
            def start(self, who):
                return who

        class SubStore(RunStore):
            pass

        class Thread:
            def start(self):
                return None

        def default_store() -> RunStore:
            return RunStore()

        def make_store():
            return RunStore()

        class Holder:
            def __init__(self):
                self.store = RunStore()

            def go(self):
                return self.store.start('h')
        ''',
    'pkg/use_store.py': '''
        from pkg.store import RunStore, SubStore, Thread, default_store, make_store

        def by_assignment():
            s = RunStore()
            s.start('a')

        def by_return_annotation():
            default_store().start('b')

        def by_param(st: RunStore):
            st.start('c')

        def other_class():
            t = Thread()
            t.start()

        def by_inferred_return():
            x = make_store()
            x.start('e')

        def by_subclass():
            sub = SubStore()
            sub.start('f')
        ''',
    'tests/test_store.py': '''
        import pytest
        from pkg.store import RunStore

        @pytest.fixture
        def store():
            return RunStore()

        def test_one(store):
            store.start('t')
        ''',
    'tests/test_util.py': '''
        from pkg.util import call_host

        def test_it():
            call_host('h', 'e')
        ''',
    'frontend/src/api.ts': '''
        // fetch('/server/control/navigate/old') is a comment
        export const go = (id: string) => fetch(`/server/control/navigate/${id}`, { method: 'POST' });
        ''',
}


def _write(root, files):
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body).lstrip('\n'), encoding='utf-8')


def _git(root, sha):
    (root / '.git' / 'refs' / 'heads').mkdir(parents=True, exist_ok=True)
    (root / '.git' / 'HEAD').write_text('ref: refs/heads/main\n')
    (root / '.git' / 'refs' / 'heads' / 'main').write_text(sha + '\n')


@pytest.fixture()
def repo(tmp_path):
    _write(tmp_path, FILES)
    _git(tmp_path, 'a' * 40)
    return tmp_path


@pytest.fixture()
def index(repo):
    return build.build_index(str(repo))


def _tags(index, name):
    return {(c.file, c.enclosing, c.receiver, c.resolution) for c in index.calls[name]}


def test_resolution_tags_enclosing_and_receiver(index):
    tags = _tags(index, 'call_host')
    assert ('pkg/routes.py', 'navigate', '', 'import-resolved') in tags
    assert ('pkg/service.py', 'run_job', 'util', 'import-resolved') in tags
    assert ('pkg/util.py', 'call_host', '', 'local') not in tags  # a def is not a call
    assert ('pkg/util.py', 'call_host', '', 'local') in _tags(index, 'helper')
    assert ('pkg/executor.py', 'NavigationExecutor.execute_navigation', 'self', 'self') in _tags(index, 'prepare')
    nav = _tags(index, 'execute_navigation')
    assert ('pkg/service.py', 'run_job', 'device.navigation_executor', 'name-match-ambiguous') in nav


def test_comments_and_strings_are_not_calls(index):
    lines = {c.line for c in index.calls['call_host'] if c.file == 'pkg/routes.py'}
    assert len(lines) == 1


def test_query_groups_by_file_and_flags_tests(index):
    out = query.code_refs(index, 'call_host')
    assert 'callers: 4 files, 4 calls' in out
    assert 'tests/test_util.py [import-resolved] (test): L4 test_it' in out
    assert 'pkg/service.py [import-resolved]: L5 run_job via util' in out
    no_tests = query.code_refs(index, 'call_host', include_tests=False)
    assert 'tests/test_util.py [' not in no_tests  # hidden, only named in the 'tests hidden' line


def test_class_method_keeps_plausible_receivers(index):
    out = query.code_refs(index, 'NavigationExecutor.execute_navigation')
    assert 'pkg/service.py' in out and 'via device.navigation_executor' in out
    assert 'pkg/other.py' not in out
    out = query.code_refs(index, 'Other.execute_navigation')
    assert 'callers: 0 files' in out and 'dropped 1 calls' in out


def test_route_links_handler_and_url(index):
    out = query.code_refs(index, 'navigate')
    assert 'route /server/control/navigate/<tree_id> [POST]' in out
    assert 'frontend/src/api.ts: L2  /server/control/navigate/*' in out
    by_url = query.code_refs(index, '/server/control/navigate/123')
    assert 'pkg/routes.py:7 navigate' in by_url and 'frontend/src/api.ts' in by_url


def test_text_only_mentions_and_hints(index, repo):
    out = query.code_refs(index, 'call_host')
    assert "text-only mentions (a grep for 'call_host(' also hits these" in out
    assert '+ 2 comment/docstring lines inside caller files' in out  # comment + string in routes.py
    nav = query.code_refs(index, 'execute_navigation')
    hint = next(line for line in nav.splitlines() if line.startswith('narrower queries: '))
    assert set(hint.split(': ', 1)[1].split(' | ')) == {'NavigationExecutor.execute_navigation', 'Other.execute_navigation'}


def test_test_fakes_folded_and_hidden_tests_listed(index):
    out = query.code_refs(index, 'call_host', include_tests=False)
    assert 'tests hidden (include_tests=false): 1 files with callers: tests/test_util.py' in out


def test_class_method_uses_receiver_types(index):
    out = query.code_refs(index, 'RunStore.start')
    assert 'callers: 3 files, 7 calls [type-resolved 7]' in out
    assert 'L5 by_assignment via s' in out and 'L8 by_return_annotation via default_store()' in out
    assert 'L11 by_param via st' in out and 'L19 by_inferred_return via x' in out
    assert 'L23 by_subclass via sub' in out  # a subclass instance reaches RunStore.start
    assert 'L23 Holder.go via self.store' in out  # self.store = RunStore() in __init__
    assert 'tests/test_store.py [type-resolved] (test): L9 test_one via store' in out  # pytest fixture
    assert 'other_class' not in out.split('dropped')[0] and 'dropped 1 calls' in out  # t = Thread()


def test_build_yields_to_the_caller_while_scanning(repo):
    pauses = []
    build.build_index(str(repo), pause=lambda: pauses.append(1))
    assert pauses  # a cooperative server (gevent) gets the loop back during the build


def test_version_falls_back_to_version_txt(tmp_path):
    _write(tmp_path, {'a.py': 'x = 1\n', 'VERSION.txt': 'current:main-2026.10.19-1\nprevious:x\n'})
    assert build.git_head(str(tmp_path)) == 'main-2026.10.19-1'
    assert '@main-2026.10.19-1' in query.code_refs(build.build_index(str(tmp_path)), 'x')  # not cut like a hash


def test_module_importers(index):
    out = query.code_refs(index, 'pkg.util')
    assert 'importers (4):' in out
    assert 'pkg/service.py' in out  # `from pkg import util`


def test_depth_two(index):
    out = query.code_refs(index, 'call_host', depth=2)
    d2 = out.split('depth 2:', 1)[1]
    assert 'pkg/service.py <- run_job L8' in d2
    assert 'route handlers, reached over HTTP (query their URL): 1: navigate' in d2
    assert 'no repo callers: ' in d2 and 'test_it' in d2
    # a def nested in a method is called from its own file only, not by every `_check(...)`
    assert 'pkg/nested.py <- Mgr._check L7' in d2
    assert 'pkg/elsewhere.py' not in d2


def test_store_rebuilds_on_git_head_change(repo):
    first = store.get_index(str(repo))
    assert store.get_index(str(repo)) is first
    _write(repo, {'pkg/extra.py': 'from pkg.util import call_host\ncall_host(1, 2)\n'})
    assert store.get_index(str(repo)) is first  # same HEAD: cached
    _git(repo, 'b' * 40)
    second = store.get_index(str(repo))
    assert second is not first and second.git_head == 'b' * 40
    assert 'pkg/extra.py' in {c.file for c in second.calls['call_host']}


def test_mcp_tool_returns_same_text(repo, monkeypatch):
    monkeypatch.setattr(store, 'repo_root', lambda: str(repo))
    res = tools.CodeRefsTools().code_refs({'name': 'call_host', 'depth': 2})
    assert not res['isError']
    assert res['content'][0]['text'] == query.code_refs(store.get_index(str(repo)), 'call_host', depth=2)
    assert tools.CodeRefsTools().code_refs({})['isError']


TYPING_FILES = {
    'pkg/__init__.py': '',
    'pkg/jobs.py': '''
        class Job:
            def fire(self):
                return 1

            def stop(self):
                return 0

        class Other:
            def fire(self):
                return 2

        class Box:
            def __init__(self):
                self.job = Job()
                self.jobs = {"a": Job(), "b": Job()}

        class SubBox(Box):
            pass
        ''',
    'pkg/use_jobs.py': '''
        from pkg.jobs import Box, Job, Other, SubBox

        def dict_literal():
            d = {"a": Job(), "b": Job()}
            d["a"].fire()
            d.get("b").stop()
            for j in d.values():
                j.fire()
            for _, v in d.items():
                v.stop()

        def mixed_dict_stays_untyped():
            d = {"a": Job(), "b": Other()}
            d["a"].fire()

        def list_loop():
            for j in [Job(), Job()]:
                j.fire()
            jobs = [Job(), Job()]
            jobs[0].stop()

        def getattr_typed(box: Box):
            getattr(box, "job").fire()

        def getattr_self_in_method():
            pass

        class Runner:
            def __init__(self):
                self.job = Job()
                self.table = {"x": Job()}

            def a(self):
                getattr(self, "job").fire()
                self.table["x"].stop()
                for t in self.table.values():
                    t.fire()

        def attr_copy(box: Box):
            j = box.job
            j.fire()
            box.job.stop()
            box.jobs["a"].stop()

        def inherited_attr():
            sb = SubBox()
            sb.job.fire()

        def narrowed(x):
            if isinstance(x, Job):
                x.fire()
            x.stop()

        def narrowing_does_not_leak(x: Other):
            if isinstance(x, Job):
                pass
            x.fire()
        ''',
}


@pytest.fixture()
def typing_index(tmp_path):
    _write(tmp_path, TYPING_FILES)
    _git(tmp_path, 'c' * 40)
    return build.build_index(str(tmp_path))


def _typed_lines(index, name, cls, file='pkg/use_jobs.py'):
    return sorted(c.line for c in index.calls[name] if c.file == file and c.receiver_type == cls)


def test_dict_and_list_of_one_class_type_the_items(typing_index):
    fire, stop = _typed_lines(typing_index, 'fire', 'Job'), _typed_lines(typing_index, 'stop', 'Job')
    assert {5, 8} <= set(fire) and {6, 10} <= set(stop)  # d["a"], d.values() loop; d.get("b"), d.items() loop
    assert 14 not in fire  # {"a": Job(), "b": Other()}: two classes stay untyped
    assert 18 in fire and 20 in stop  # for j in [Job(), Job()]; jobs = [Job(), Job()]; jobs[0]


def test_getattr_and_attribute_copies_follow_the_attribute_type(typing_index):
    fire, stop = _typed_lines(typing_index, 'fire', 'Job'), _typed_lines(typing_index, 'stop', 'Job')
    assert 23 in fire  # getattr(box, "job") with Box.job = Job()
    assert 34 in fire  # getattr(self, "job")
    assert 35 in stop and 37 in fire  # self.table["x"], for t in self.table.values()
    assert 41 in fire and 42 in stop  # j = box.job; box.job.stop()
    assert 43 in stop  # box.jobs["a"] (container stored on Box)
    assert 47 in fire  # SubBox inherits Box.job


def test_isinstance_narrows_inside_the_if_only(typing_index):
    assert 51 in _typed_lines(typing_index, 'fire', 'Job')  # inside `if isinstance(x, Job)`
    assert 52 not in _typed_lines(typing_index, 'stop', 'Job')  # after the if: x is unknown again
    assert 57 not in _typed_lines(typing_index, 'fire', 'Job')  # x: Other is not a Job outside the narrowing


def test_typed_receivers_filter_class_method_queries(typing_index):
    out = query.code_refs(typing_index, 'Job.fire')
    assert "L5 dict_literal via d['a']" in out and "getattr_typed via getattr(box, 'job')" in out
    assert 'L51 narrowed via x' in out and 'L57' not in out.split('dropped')[0]


BLUEPRINT_FILES = {
    'backend/__init__.py': '',
    'backend/src/__init__.py': '',
    'backend/src/routes/__init__.py': '',
    'backend/src/routes/bps.py': '''
        from flask import Blueprint

        plain_bp = Blueprint('plain', __name__)
        own_bp = Blueprint('own', __name__, url_prefix='/own')
        parent_bp = Blueprint('parent', __name__, url_prefix='/parent')
        child_bp = Blueprint('child', __name__, url_prefix='/child')
        mod_bp = Blueprint('mod', __name__)
        again_bp = Blueprint('again', __name__, url_prefix='/again')

        @plain_bp.route('/list')
        def plain_list():
            return 1

        @own_bp.route('/x')
        def own_x():
            return 1

        @parent_bp.route('/q')
        def parent_q():
            return 1

        @child_bp.route('/c')
        def child_c():
            return 1

        @mod_bp.route('/m')
        def mod_m():
            return 1

        @again_bp.route('/y')
        def again_y():
            return 1
        ''',
    # the routes package is imported without its leading 'backend.src.' (path-relative imports)
    'backend/src/app.py': '''
        import routes.bps as bps
        from routes.bps import plain_bp, own_bp, parent_bp, child_bp, again_bp

        def register(app):
            app.register_blueprint(plain_bp, url_prefix='/server/plain')
            app.register_blueprint(own_bp)
            parent_bp.register_blueprint(child_bp, url_prefix='/kids')
            app.register_blueprint(parent_bp, url_prefix='/server/parent')
            app.register_blueprint(bps.mod_bp, url_prefix='/server/' + 'dyn')
            app.register_blueprint(again_bp)
            app.register_blueprint(again_bp, url_prefix='/second')
        ''',
}


def test_register_blueprint_url_prefix_prefixes_the_routes(tmp_path):
    _write(tmp_path, BLUEPRINT_FILES)
    _git(tmp_path, 'd' * 40)
    index = build.build_index(str(tmp_path))
    paths = {r.handler: sorted(x.path for x in index.routes if x.handler == r.handler) for r in index.routes}
    assert paths['plain_list'] == ['/server/plain/list']  # imported blueprint, prefix given at registration
    assert paths['own_x'] == ['/own/x']  # registered without a prefix: its own url_prefix stays
    assert paths['parent_q'] == ['/server/parent/q']  # the registration prefix replaces the blueprint's own
    assert paths['child_c'] == ['/server/parent/kids/c']  # nested: parent prefix + the child's registration prefix
    assert paths['mod_m'] == ['/m']  # a non-literal prefix is not guessed
    assert paths['again_y'] == ['/again/y', '/second/y']  # mounted twice: one route per mount
    out = query.code_refs(index, '/server/parent/kids/c')
    assert 'routes (1):' in out and 'child_c' in out
