#!/usr/bin/env python3
"""Offline guard: FlowSubmissionTable has ONE completion writer, `flow_completion.claim_completion`.

WHY THIS EXISTS
---------------
`amplify/functions/shared/lambda_utils/flow_completion.py` records what was measured: separate
writers in two Lambdas put two row shapes into the one flow-response table, only some of them
guarded, and one duplicated paid completion produced two invoices and two payment links. A single
conditional writer fixed that, but nothing stopped the next handler from adding its own
`put_item`. This script is that stop. Individual workflows stay separate; persistence does not.

WHAT COUNTS AS AN INSERT
------------------------
Every `amplify/functions/**/*.py` is parsed with `ast`. Nothing is imported or executed, so no
AWS, boto3 or credentials are involved. An insert into the FlowSubmission table is:

* `<table>.put_item(...)`, including the writer from `<table>.batch_writer()`;
* a client-level `put_item(TableName=<name>, ...)`, a `batch_write_item` PutRequest under
  `<name>`, or a `transact_write_items` item `{'Put': {'TableName': <name>, ...}}`;

where `<name>` is an expression naming the table (`FLOW_SUBMISSIONS_TABLE`,
`FLOW_SUBMISSION_TABLE`, `flow_submissions_table_name()`, `shared_tables.FLOW_SUBMISSIONS` or a
literal containing `FlowSubmissionTable`) and `<table>` is `<anything>.Table(<name>)`. Both are
followed through assignments in the same function or module, through helpers (same-module or
imported) that return one, and into the parameters of repo functions called with one, so a
writer cannot hide behind a variable, a `_table()` helper or a `save(table, row)` signature.
`update_item` and `delete_item` change an existing row; they are not completions and pass.

Not followed, deliberately: attributes on objects (`self.table`), `getattr`, `**kwargs`
forwarding and tables built from runtime strings. A guard that guessed there would be noisy;
the self-test below pins exactly what is seen.

AUTHORITY
---------
Only `amplify/functions/shared/lambda_utils/flow_completion.py` may insert. Every other insert
fails, except an explicit KNOWN_PENDING entry, printed as PENDING on every run so it stays
visible. An entry that no longer matches any insert also fails, so the list can only shrink.

READ-ONLY. Usage:  python3 scripts/check_flow_submission_writers.py [--verbose]
Exit: 0 passed, 1 an unexpected writer or a stale KNOWN_PENDING entry, 2 the guard could not run.
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / 'amplify' / 'functions'
SANCTIONED = 'amplify/functions/shared/lambda_utils/flow_completion.py'
SANCTIONED_FUNCTION = 'claim_completion'

#: Inserts that bypass the one writer, are known, and are owned by a named piece of work.
#: Keyed `<path>::<function qualname>`. Never add an entry to make a new writer pass: route the
#: insert through `flow_completion.claim_completion` instead.
KNOWN_PENDING: Dict[str, str] = {}
# This gate inspects amplify/functions; standalone operator scripts are out of scope.

NAME_IDENTIFIERS = frozenset({'FLOW_SUBMISSIONS_TABLE', 'FLOW_SUBMISSION_TABLE', 'FLOW_SUBMISSIONS'})
NAME_FUNCTIONS = frozenset({'flow_submissions_table_name'})
PHYSICAL_NAME = 'FlowSubmissionTable'
SKIP_DIRS = frozenset({'__pycache__', 'node_modules'})

NAME, TABLE, WRITER = 'name', 'table', 'batch writer'
#: Calls that pass a table name through: `os.environ.get('FLOW_SUBMISSIONS_TABLE', ...)`,
#: `FLOW_SUBMISSIONS.name()`, `.strip()`. Any other call (a hash, a log line) yields a new
#: value, not the name, so a name cannot leak into every string helper it is handed to.
NAME_METHODS = frozenset({'get', 'getenv', 'name', 'strip', 'format', 'str'})


@dataclass
class Scope:
    qualname: str
    name: str                      # the def's own name; '' for module scope
    parent: Optional['Scope']
    nodes: List[ast.AST]           # every node evaluated in this scope, nested defs excluded
    params: Tuple[str, ...] = ()   # positional parameters, in order


@dataclass
class Module:
    rel: str
    root: str                      # deploy root that absolute imports resolve against
    dotted: str
    is_package: bool
    tree: ast.Module
    imports: Dict[str, List[Tuple[str, Optional[str]]]] = field(default_factory=dict)
    defs: Dict[str, List[Scope]] = field(default_factory=dict)
    scopes: List[Scope] = field(default_factory=list)


@dataclass
class Env:
    names: Set[str] = field(default_factory=set)
    tables: Set[str] = field(default_factory=set)
    writers: Set[str] = field(default_factory=set)

    def copy(self) -> 'Env':
        return Env(set(self.names), set(self.tables), set(self.writers))

    def add(self, name: str, kind: str) -> bool:
        bucket = {NAME: self.names, TABLE: self.tables, WRITER: self.writers}[kind]
        if name in bucket:
            return False
        bucket.add(name)
        return True


@dataclass(frozen=True)
class Hit:
    rel: str
    line: int
    function: str
    kind: str

    @property
    def key(self) -> str:
        return f'{self.rel}::{self.function}'


def _scope_nodes(body: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Every node evaluated in this scope. A nested def or class is yielded, not entered."""
    stack = list(reversed(list(body)))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _pairs(target: ast.AST, value: ast.AST) -> Iterator[Tuple[str, ast.AST]]:
    if isinstance(target, ast.Name):
        yield target.id, value
    elif (isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List))
          and len(target.elts) == len(value.elts)):
        for sub_target, sub_value in zip(target.elts, value.elts):
            yield from _pairs(sub_target, sub_value)


def _assignments(nodes: Iterable[ast.AST]) -> Iterator[Tuple[str, ast.AST]]:
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                yield from _pairs(target, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            yield from _pairs(node.target, node.value)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    yield from _pairs(item.optional_vars, item.context_expr)


def _call_values(call: ast.Call) -> List[ast.AST]:
    return [a.value if isinstance(a, ast.Starred) else a for a in call.args] + \
        [kw.value for kw in call.keywords]


def _strongest(kinds: Iterable[Optional[str]]) -> Optional[str]:
    found = set(kinds)
    for kind in (TABLE, WRITER, NAME):
        if kind in found:
            return kind
    return None


class Analysis:
    """Name, table and parameter facts for a set of modules, solved to a fixpoint."""

    def __init__(self, modules: List[Module]):
        self.modules = modules
        self.by_rel = {m.rel: m for m in modules}
        self.index = {(m.root, m.dotted): m for m in modules}
        self.module_kinds: Dict[str, Env] = {m.rel: Env() for m in modules}
        self.returns: Dict[Tuple[str, str], Set[str]] = {}
        self.param_kinds: Dict[Tuple[str, str], Dict[str, Set[str]]] = {}
        for mod in modules:
            self._index(mod)
        self._solve()

    # ── indexing ────────────────────────────────────────────────────────────────────────

    def find(self, mod: Module, dotted: str) -> Optional[Module]:
        return self.index.get((mod.root, dotted)) or self.index.get(('shared', dotted))

    def _absolute(self, mod: Module, module: Optional[str], level: int) -> str:
        if not level:
            return module or ''
        parts = mod.dotted.split('.') if mod.dotted else []
        if not mod.is_package:
            parts = parts[:-1]
        if level > 1:
            parts = parts[:max(0, len(parts) - (level - 1))]
        return '.'.join(parts + ([module] if module else []))

    def _index(self, mod: Module) -> None:
        # Imports anywhere in the file count: the Lambdas here import lazily inside functions.
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split('.')[0]
                    target = alias.name if alias.asname else local
                    mod.imports.setdefault(local, []).append((target, None))
            elif isinstance(node, ast.ImportFrom):
                base = self._absolute(mod, node.module, node.level)
                for alias in node.names:
                    if alias.name == '*':
                        continue
                    sub = f'{base}.{alias.name}' if base else alias.name
                    entry = (sub, None) if self.find(mod, sub) else (base, alias.name)
                    mod.imports.setdefault(alias.asname or alias.name, []).append(entry)
        top = Scope('<module>', '', None, list(_scope_nodes(mod.tree.body)))
        mod.scopes = [top]
        self._nest(mod, top, top.nodes, '')

    def _nest(self, mod: Module, parent: Scope, nodes: List[ast.AST], prefix: str) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                scope = Scope(prefix + node.name, node.name, parent, list(_scope_nodes(node.body)),
                              tuple(a.arg for a in args.posonlyargs + args.args))
                mod.scopes.append(scope)
                mod.defs.setdefault(node.name, []).append(scope)
                self._nest(mod, scope, scope.nodes, scope.qualname + '.')
            elif isinstance(node, ast.ClassDef):
                # Methods do not see class-level names, so they inherit the enclosing scope.
                self._nest(mod, parent, list(_scope_nodes(node.body)), f'{prefix}{node.name}.')

    # ── resolution ──────────────────────────────────────────────────────────────────────

    def _module_names(self, mod: Module, node: ast.AST) -> List[str]:
        """Dotted module names `node` may refer to (an imported module or a submodule of one)."""
        if isinstance(node, ast.Name):
            return [dotted for dotted, attr in mod.imports.get(node.id, []) if attr is None]
        if isinstance(node, ast.Attribute):
            return [f'{parent}.{node.attr}' for parent in self._module_names(mod, node.value)]
        return []

    def _resolve(self, mod: Module, func: ast.AST) -> List[Tuple[str, str]]:
        """(module rel, def name) for every repo function a call to `func` may reach."""
        keys: List[Tuple[str, str]] = []
        if isinstance(func, ast.Name):
            if func.id in mod.defs:
                keys.append((mod.rel, func.id))
            for dotted, attr in mod.imports.get(func.id, []):
                target = self.find(mod, dotted) if attr else None
                if target and attr in target.defs:
                    keys.append((target.rel, attr))
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in ('self', 'cls') \
                    and func.attr in mod.defs:
                keys.append((mod.rel, func.attr))
            for dotted in self._module_names(mod, func.value):
                target = self.find(mod, dotted)
                if target and func.attr in target.defs:
                    keys.append((target.rel, func.attr))
        return keys

    def _module_level(self, mod: Module, dotted: str, attr: str) -> Optional[str]:
        target = self.find(mod, dotted)
        if not target:
            return None
        facts = self.module_kinds[target.rel]
        return TABLE if attr in facts.tables else NAME if attr in facts.names else None

    # ── classification ──────────────────────────────────────────────────────────────────

    def kind(self, mod: Module, node: ast.AST, env: Env) -> Optional[str]:
        """TABLE, WRITER or NAME when `node` evaluates to the FlowSubmission table (or None)."""
        if isinstance(node, ast.Name):
            if node.id in env.writers:
                return WRITER
            if node.id in env.tables:
                return TABLE
            if node.id in env.names or node.id in NAME_IDENTIFIERS:
                return NAME
            return _strongest(self._module_level(mod, dotted, attr)
                              for dotted, attr in mod.imports.get(node.id, []) if attr)
        if isinstance(node, ast.Attribute):
            if node.attr in NAME_IDENTIFIERS:
                return NAME
            return _strongest(self._module_level(mod, dotted, node.attr)
                              for dotted in self._module_names(mod, node.value))
        if isinstance(node, ast.Call):
            func = node.func
            receiver = func.value if isinstance(func, ast.Attribute) else None
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
            if name in NAME_FUNCTIONS:
                return NAME
            if name == 'Table' and receiver is not None and any(
                    self.refs_name(mod, value, env) for value in _call_values(node)):
                return TABLE
            if name == 'batch_writer' and receiver is not None \
                    and self.kind(mod, receiver, env) == TABLE:
                return WRITER
            if name in NAME_METHODS and any(self.kind(mod, value, env) == NAME for value in
                                            ([receiver] if receiver is not None else [])
                                            + _call_values(node)):
                return NAME
            return _strongest(kind for key in self._resolve(mod, func)
                              for kind in self.returns.get(key, ()))
        if isinstance(node, ast.Constant):
            text = node.value if isinstance(node.value, str) else ''
            return NAME if text and (PHYSICAL_NAME in text or text in NAME_IDENTIFIERS) else None
        if isinstance(node, ast.JoinedStr):
            parts = (part.value if isinstance(part, ast.FormattedValue) else part
                     for part in node.values)
            return NAME if any(self.kind(mod, part, env) == NAME for part in parts) else None
        if isinstance(node, ast.BinOp):
            sides = (self.kind(mod, node.left, env), self.kind(mod, node.right, env))
            return NAME if NAME in sides else None
        if isinstance(node, ast.Subscript):
            return NAME if self.kind(mod, node.slice, env) == NAME else None
        if isinstance(node, ast.IfExp):
            return _strongest((self.kind(mod, node.body, env), self.kind(mod, node.orelse, env)))
        if isinstance(node, ast.BoolOp):
            return _strongest(self.kind(mod, value, env) for value in node.values)
        return None

    def refs_name(self, mod: Module, node: ast.AST, env: Env) -> bool:
        """Whether the name appears anywhere in a boundary expression: the argument of
        `.Table(...)`, a `TableName=` value or a `RequestItems` key. Deliberately wider than
        `kind`, because at a boundary a miss is a hidden writer and a hit costs one review."""
        return any(self.kind(mod, sub, env) == NAME for sub in ast.walk(node))

    # ── solving ─────────────────────────────────────────────────────────────────────────

    def env(self, mod: Module, scope: Scope, envs: Dict[int, Env]) -> Env:
        if scope.parent is None:
            env = self.module_kinds[mod.rel].copy()
        else:
            env = envs[id(scope.parent)].copy()
            for param, kinds in self.param_kinds.get((mod.rel, scope.name), {}).items():
                for kind in kinds:
                    env.add(param, kind)
        changed = True
        while changed:
            changed = False
            for target, value in _assignments(scope.nodes):
                kind = self.kind(mod, value, env)
                if kind and env.add(target, kind):
                    changed = True
        envs[id(scope)] = env
        return env

    def _bind(self, mod: Module, call: ast.Call, env: Env) -> None:
        """Carry a table or name passed as an argument into the callee's parameter."""
        for rel, name in self._resolve(mod, call.func):
            via_module = isinstance(call.func, ast.Attribute) and \
                bool(self._module_names(mod, call.func.value))
            for scope in self.by_rel[rel].defs.get(name, []):
                params = scope.params
                offset = 1 if (params and params[0] in ('self', 'cls')
                               and isinstance(call.func, ast.Attribute) and not via_module) else 0
                bound: List[Tuple[str, ast.AST]] = []
                for i, arg in enumerate(call.args):
                    if isinstance(arg, ast.Starred):
                        break
                    if i + offset < len(params):
                        bound.append((params[i + offset], arg))
                bound.extend((kw.arg, kw.value) for kw in call.keywords if kw.arg)
                for param, value in bound:
                    kind = self.kind(mod, value, env)
                    if kind:
                        self.param_kinds.setdefault((rel, name), {}).setdefault(param, set()).add(kind)

    def _size(self) -> int:
        return (sum(len(e.names) + len(e.tables) + len(e.writers) for e in self.module_kinds.values())
                + sum(len(k) for k in self.returns.values())
                + sum(len(k) for p in self.param_kinds.values() for k in p.values()))

    def _solve(self) -> None:
        # Facts only ever grow, so an unchanged total means nothing changed this round.
        for _ in range(64):
            before = self._size()
            for mod in self.modules:
                envs: Dict[int, Env] = {}
                for scope in mod.scopes:
                    env = self.env(mod, scope, envs)
                    if scope.parent is None:
                        facts = self.module_kinds[mod.rel]
                        facts.names |= env.names
                        facts.tables |= env.tables
                    for node in scope.nodes:
                        if scope.parent is not None and isinstance(node, ast.Return) and node.value:
                            kind = self.kind(mod, node.value, env)
                            if kind:
                                self.returns.setdefault((mod.rel, scope.name), set()).add(kind)
                        elif isinstance(node, ast.Call):
                            self._bind(mod, node, env)
            if self._size() == before:
                return
        raise RuntimeError('writer analysis did not converge')

    # ── detection ───────────────────────────────────────────────────────────────────────

    def _insert(self, mod: Module, node: ast.AST, env: Env) -> str:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == 'put_item':
            base = self.kind(mod, node.func.value, env)
            if base == TABLE:
                return 'put_item'
            if base == WRITER:
                return 'batch_writer().put_item'
            if any(kw.arg == 'TableName' and self.refs_name(mod, kw.value, env)
                   for kw in node.keywords):
                return 'client put_item(TableName=...)'
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is None:
                    continue
                if isinstance(key, ast.Constant) and key.value == 'Put' and isinstance(value, ast.Dict) \
                        and any(isinstance(k, ast.Constant) and k.value == 'TableName'
                                and self.refs_name(mod, v, env)
                                for k, v in zip(value.keys, value.values)):
                    return "transact_write_items {'Put': ...}"
                if self.refs_name(mod, key, env) and any(
                        isinstance(sub, ast.Constant) and sub.value == 'PutRequest'
                        for sub in ast.walk(value)):
                    return "batch_write_item {'PutRequest': ...}"
        return ''

    def hits(self) -> List[Hit]:
        found: Set[Hit] = set()
        for mod in self.modules:
            envs: Dict[int, Env] = {}
            for scope in mod.scopes:
                env = self.env(mod, scope, envs)
                for node in scope.nodes:
                    kind = self._insert(mod, node, env)
                    if kind:
                        found.add(Hit(mod.rel, node.lineno, scope.qualname, kind))
        return sorted(found, key=lambda h: (h.rel, h.line, h.kind))


def _module(rel: str, root: str, inner: Tuple[str, ...], source: str) -> Module:
    is_package = inner[-1] == '__init__.py'
    parts = list(inner[:-1]) + ([] if is_package else [inner[-1][:-3]])
    return Module(rel, root, '.'.join(parts), is_package, ast.parse(source, filename=rel))


def load_repo() -> List[Module]:
    """Every backend module. Deploy roots: `shared/`, else `<group>/<function>/`."""
    modules = []
    for path in sorted(FUNCTIONS.rglob('*.py')):
        if SKIP_DIRS.intersection(path.parts):
            continue
        parts = path.relative_to(FUNCTIONS).parts
        if parts[0] == 'shared':
            root, inner = 'shared', parts[1:]
        elif len(parts) >= 3:
            root, inner = '/'.join(parts[:2]), parts[2:]
        else:
            root, inner = '/'.join(parts[:-1]) or '.', parts[-1:]
        rel = path.relative_to(ROOT).as_posix()
        modules.append(_module(rel, root, inner, path.read_text(encoding='utf-8')))
    return modules


# ── self-test: the guard proves it can see each shape before it is trusted ───────────────

_FIXTURES = {
    'fx/positive.py': '''
import boto3
from lambda_utils import shared_tables
NAME = shared_tables.flow_submissions_table_name()
dynamodb = boto3.resource('dynamodb')
def alias():
    t = dynamodb.Table(NAME)
    t.put_item(Item={})
def chained():
    dynamodb.Table(FLOW_SUBMISSIONS_TABLE).put_item(Item={})
def literal(db):
    db.Table('stack-wecare-digital-FlowSubmissionTable').put_item(Item={})
def batch():
    with dynamodb.Table(FLOW_SUBMISSIONS_TABLE).batch_writer() as writer:
        writer.put_item(Item={})
def transact(client):
    client.transact_write_items(TransactItems=[{'Put': {'TableName': NAME, 'Item': {}}}])
def low_level(client):
    client.put_item(TableName=NAME, Item={})
def _flow_table():
    return dynamodb.Table(NAME)
def helper():
    _flow_table().put_item(Item={})
def save(table, row):
    table.put_item(Item=row)
def route():
    save(dynamodb.Table(NAME), {})
def from_env():
    import os
    dynamodb.Table(os.environ.get('FLOW_SUBMISSIONS_TABLE', 'x')).put_item(Item={})
''',
    'fx/store.py': '''
def write(table, item):
    table.put_item(Item=item)
''',
    'fx/caller.py': '''
import boto3
from fx import store
def go():
    store.write(boto3.resource('dynamodb').Table(FLOW_SUBMISSIONS_TABLE), {})
''',
    'fx/negative.py': '''
import boto3, hashlib
dynamodb = boto3.resource('dynamodb')
CONTACTS = 'stack-wecare-digital-ContactsTable'
def allowed(client):
    table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
    table.update_item(Key={}, UpdateExpression='SET a = :a')
    table.delete_item(Key={})
    table.get_item(Key={})
    dynamodb.Table(CONTACTS).put_item(Item={})
    client.transact_write_items(TransactItems=[{'Update': {'TableName': FLOW_SUBMISSIONS_TABLE}}])
def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()
def derived():
    other = digest(FLOW_SUBMISSIONS_TABLE)
    dynamodb.Table(other).put_item(Item={})
''',
}
_EXPECTED = {
    ('fx/positive.py', 'alias', 'put_item'),
    ('fx/positive.py', 'chained', 'put_item'),
    ('fx/positive.py', 'literal', 'put_item'),
    ('fx/positive.py', 'batch', 'batch_writer().put_item'),
    ('fx/positive.py', 'transact', "transact_write_items {'Put': ...}"),
    ('fx/positive.py', 'low_level', 'client put_item(TableName=...)'),
    ('fx/positive.py', 'helper', 'put_item'),
    ('fx/positive.py', 'save', 'put_item'),
    ('fx/positive.py', 'from_env', 'put_item'),
    ('fx/store.py', 'write', 'put_item'),
}


def self_test() -> List[str]:
    modules = [_module(rel, 'selftest', tuple(rel.split('/')), source)
               for rel, source in _FIXTURES.items()]
    seen = {(h.rel, h.function, h.kind) for h in Analysis(modules).hits()}
    return [f'self-test missed {e}' for e in sorted(_EXPECTED - seen)] + \
        [f'self-test false positive {e}' for e in sorted(seen - _EXPECTED)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--verbose', action='store_true', help='also list the sanctioned writer')
    args = parser.parse_args()

    blind = self_test()
    if blind:
        print('FLOW SUBMISSION WRITERS CHECK COULD NOT RUN: the detector is blind')
        for line in blind:
            print(' -', line)
        return 2
    try:
        modules = load_repo()
        hits = Analysis(modules).hits()
    except (SyntaxError, UnicodeDecodeError, RuntimeError) as error:
        print(f'FLOW SUBMISSION WRITERS CHECK COULD NOT RUN: {type(error).__name__}: {error}')
        return 2

    sanctioned = [h for h in hits if h.rel == SANCTIONED]
    pending = [h for h in hits if h.rel != SANCTIONED and h.key in KNOWN_PENDING]
    unexpected = [h for h in hits if h.rel != SANCTIONED and h.key not in KNOWN_PENDING]
    stale = sorted(set(KNOWN_PENDING) - {h.key for h in pending})
    errors = [f'{h.rel}:{h.line} {h.function}: {h.kind}' for h in unexpected]
    errors += [f'{key}: KNOWN_PENDING entry matches no insert any more; delete it' for key in stale]
    if not any(h.function.split('.')[-1] == SANCTIONED_FUNCTION for h in sanctioned):
        errors.append(f'{SANCTIONED}: no insert found in {SANCTIONED_FUNCTION}; the guard can no '
                      'longer see the sanctioned writer, so it cannot vouch for the others')

    if args.verbose:
        for h in sanctioned:
            print(f'WRITER   {h.rel}:{h.line} {h.function}: {h.kind}')
    for h in pending:
        print(f'PENDING  {h.rel}:{h.line} {h.function}: {h.kind} ({KNOWN_PENDING[h.key]})')
    for line in errors:
        print(f'FAIL     {line}')

    summary = (f'{len(modules)} files, {len(sanctioned)} sanctioned insert(s) in '
               f'flow_completion.{SANCTIONED_FUNCTION}, {len(pending)} pending, '
               f'{len(unexpected)} unexpected')
    if errors:
        print(f'FLOW SUBMISSION WRITERS CHECK FAILED: {summary}; route every insert through '
              f'flow_completion.{SANCTIONED_FUNCTION}.')
        return 1
    print(f'FLOW SUBMISSION WRITERS CHECK PASSED: {summary}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
