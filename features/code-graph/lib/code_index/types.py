"""Data shapes of the code reference index."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Definition:
    name: str
    file: str
    line: int
    kind: str                    # function | method | class
    owner: Optional[str] = None  # class name for methods
    signature: str = ""
    nested: bool = False         # def inside a function: callable from its own file only
    returns: str = ""            # type hint of the return value ("class:X" / "call:f"), see python_scan
    fixture: bool = False        # @pytest.fixture: tests receive its return value as a parameter
    bases: tuple = ()            # class names a class derives from (last name of each base)


@dataclass(frozen=True)
class CallSite:
    name: str
    file: str
    line: int
    enclosing: str               # "Class.method", "func" or "<module>"
    receiver: str = ""           # text before ".name(", empty for bare calls
    resolution: str = ""         # one of constants.RES_*
    receiver_hint: str = ""      # what the receiver is, from the file alone ("class:X", "call:f", "param:p", "selfattr:C.a")
    receiver_type: str = ""      # class the receiver resolves to across files, "" when unknown


@dataclass(frozen=True)
class RouteDef:
    path: str                    # full path incl. blueprint url_prefix, Flask params kept
    handler: str
    file: str
    line: int
    methods: str = ""
    bp: str = ""                 # blueprint variable the route is declared on ("" for an app route)
    rest: str = ""               # the path as written in the decorator, without any blueprint prefix


@dataclass(frozen=True)
class UrlRef:
    path: str                    # literal as written, template vars replaced by *
    file: str
    line: int


@dataclass
class FileScan:
    """Raw facts from one file, before cross-file resolution."""
    file: str
    module: str = ""
    definitions: List[Definition] = field(default_factory=list)
    calls: List[CallSite] = field(default_factory=list)
    imported_names: Dict[str, str] = field(default_factory=dict)  # local name -> source module
    attr_hints: Dict[str, str] = field(default_factory=dict)      # "Class.attr" -> hint, from self.attr = ...
    imported_modules: List[str] = field(default_factory=list)
    routes: List[RouteDef] = field(default_factory=list)
    urls: List[UrlRef] = field(default_factory=list)
    blueprints: Dict[str, str] = field(default_factory=dict)      # blueprint variable -> its own url_prefix
    # (parent, child, url_prefix or None) of every `parent.register_blueprint(child[, url_prefix=...])`;
    # parent and child are dotted names ("app", "bp", "mod.bp"), parent "" when it is not a plain name
    registrations: List[Tuple[str, str, Optional[str]]] = field(default_factory=list)


@dataclass
class CodeIndex:
    repo: str = ""               # checkout root the index was built from
    built_at: str = ""
    git_head: str = ""
    files_scanned: int = 0
    defs: Dict[str, List[Definition]] = field(default_factory=dict)
    calls: Dict[str, List[CallSite]] = field(default_factory=dict)
    importers: Dict[str, List[str]] = field(default_factory=dict)   # module -> files
    module_files: Dict[str, str] = field(default_factory=dict)      # module -> file
    imported_names: Dict[str, Dict[str, str]] = field(default_factory=dict)  # file -> local name -> source
    routes: List[RouteDef] = field(default_factory=list)
    urls: List[UrlRef] = field(default_factory=list)
    # Text-only mentions, per defined name (only names with a hit): `name(` lines that are not AST calls/defs.
    text_hits: Dict[str, List[Tuple[str, int]]] = field(default_factory=dict)         # name -> (file, line)
    longer_names: Dict[str, Dict[str, Tuple[str, ...]]] = field(default_factory=dict)  # name -> longer name -> files
