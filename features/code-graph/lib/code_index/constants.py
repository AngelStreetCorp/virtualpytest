"""Constants for the code reference index."""
import re

# Directories never scanned (vendored, generated, caches, VCS).
SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build",
    "graphify-out", ".pytest_cache", ".mypy_cache", "coverage", ".next",
})

PY_SUFFIX = ".py"
TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")

# Path prefixes flagged as test code in results (not excluded).
TEST_PREFIXES = ("tests/", "test_agents/", "test_campaign/")

# URL literals that address our own services.
URL_PREFIXES = ("/server/", "/host/")
URL_LITERAL_RE = re.compile(r"""['"`](/(?:server|host)/[^'"`\s?#]*)""")
TS_TEMPLATE_VAR_RE = re.compile(r"\$\{[^}]*\}")
FLASK_PARAM_RE = re.compile(r"<[^>]+>")
WILDCARD = "*"

# Flask route decorator method names.
ROUTE_DECORATORS = frozenset({"route", "get", "post", "put", "patch", "delete"})

# Resolution tags returned to the agent, most to least certain.
RES_LOCAL = "local"                  # defined in the same file
RES_SELF = "self"                    # self./cls. call to a method of the same class
RES_IMPORT = "import-resolved"       # name imported from the defining module
RES_TYPED = "type-resolved"          # receiver's class known (assignment, annotation, return type, fixture)
RES_UNIQUE = "name-match-unique"     # attribute call, only one def with that name
RES_AMBIGUOUS = "name-match-ambiguous"  # attribute call, several defs share the name
RES_EXTERNAL = "no-repo-def"         # name not defined in the repo (stdlib/3rd party)

# Query limits keep tool output small.
DEFAULT_MAX_FILES = 60
MAX_DEPTH = 2
RECEIVER_MAX_CHARS = 60

# Order used to sort callers, most certain first.
RES_ORDER = (RES_LOCAL, RES_SELF, RES_IMPORT, RES_TYPED, RES_UNIQUE, RES_AMBIGUOUS, RES_EXTERNAL)

# How many hops a receiver hint may follow (f() -> g() -> Class) before giving up.
HINT_MAX_HOPS = 4

# A cooperative build yields to the server's event loop every this many files (~5 ms of work per file).
PAUSE_EVERY_FILES = 20
PAUSE_S = 0.001          # how long each yield sleeps (a real timer, so the loop polls sockets in between)
# The background warm-up starts this long after the server boots, once start-up work is done.
WARM_DELAY_S = 30

# Path prefix flagged as optional-feature code in results.
FEATURE_PREFIX = "features/"
SIGNATURE_MAX_CHARS = 120

# Text-only mentions: a grep hit within this many lines after an AST call/def start is that call/def.
MENTION_CALL_SLACK = 3
MENTION_MAX_LISTED = 12
NARROW_MAX = 8

# A text-only mention is an identifier followed by "(" (what `rg 'name\('` shows); recorded at build time.
MENTION_TOKEN_RE = re.compile(r"(\w+)\s*\(")
DEF_LINE_PREFIXES = ("def ", "async def ")
