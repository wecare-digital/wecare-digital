"""Every module the checkout path can reach must be IN the deployment ZIP.

The failure this guards against is specific and silent: a handler whose imports all resolve in
the repository, packaged without one of them, deploys cleanly and then fails on the first real
request with `Unable to import module 'handler'`. No build step catches it, because the build
step is the thing that dropped the file.

It also pins the inverse - what must NOT ship. Tests, `__pycache__` and dev dependencies in a
Lambda package are dead weight at best, and at worst a test fixture carrying a credential shape
inside a production artifact.

Two source roots, deliberately, because one of them is not enough
----------------------------------------------------------------
Most assertions here run against the WORKING TREE, which is the right scope for the packaging
question: "would a package built from this repository today be complete". But in this repo that
tree is shared by several concurrent sessions, so it routinely carries files that are modified or
untracked and belong to nobody here - and `build_zip` packages all of them. A suite that only ever
asserts over the working tree is therefore asserting over other people's in-flight edits, and can
go red or green for reasons that have nothing to do with packaging.

So `committed` builds the same package from `git archive HEAD`, and the completeness assertions run
against both. The working-tree build catches a packaging rule that started dropping a file; the
committed build is the one whose result is reproducible by anyone, on any machine, from the same
SHA. The deployed-revision evidence lives in docs/execution/checkout-deployment-20261001.md.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "provision_checkout.py"

#: Everything the two coexisting checkout flows can reach. The website Razorpay path
#: (`website_checkout`, `blog_contribution`, `razorpay_orders`, `checkout_pricing`,
#: `order_creation`, `customer_receipt`, `customer_session`) is NOT imported by the handler today
#: - it ships ahead
#: of the owner's architecture decision. It is listed anyway, deliberately: the day that decision
#: lands, wiring it must not also require discovering that the package was incomplete.
#:
#: Checked only for modules that EXIST under the source root being packaged, and that caveat is
#: load-bearing rather than a loophole. Five of these files exist only on `origin/stack`; a local
#: checkout 25 commits behind simply does not have them, which is a git position, not a packaging
#: defect. What this list catches is the real bug: a module present in the tree and left out of
#: the ZIP - an `EXCLUDE_DIRS` entry, a suffix filter, a renamed package directory.
#: `test_every_import_resolves` is the assertion that has no escape hatch.
REQUIRED = (
    "handler.py",
    "lambda_utils/customer_auth.py",
    "lambda_utils/customer_session.py",
    "lambda_utils/payment_readiness.py",
    "lambda_utils/payment_status.py",
    "lambda_utils/response.py",
    "lambda_utils/logging.py",
    "lambda_utils/media_paths.py",
    "lambda_utils/ecommerce/order_keys.py",
    "lambda_utils/ecommerce/payment_attempt.py",
    "lambda_utils/ecommerce/website_checkout.py",
    "lambda_utils/ecommerce/blog_contribution.py",
    "lambda_utils/ecommerce/checkout_pricing.py",
    "lambda_utils/ecommerce/order_creation.py",
    "lambda_utils/ecommerce/customer_receipt.py",
    "lambda_utils/integrations/razorpay_orders.py",
)

SHARED = ROOT / "amplify" / "functions" / "shared"


def _on_disk(arcname: str) -> bool:
    if arcname == "handler.py":
        return (ROOT / "amplify" / "functions" / "ecommerce" / "checkout"
                / "handler.py").is_file()
    return (SHARED / arcname).is_file()


def _provisioner():
    spec = importlib.util.spec_from_file_location("provision_checkout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_checkout"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built():
    module = _provisioner()
    try:
        yield module.build_package(ROOT)
    finally:
        sys.modules.pop("provision_checkout", None)


@pytest.fixture(scope="module")
def committed(tmp_path_factory):
    """The same package, built from `git archive HEAD` instead of from the working tree.

    This is the build whose outcome is reproducible from a SHA. The working-tree build shares its
    directory with other sessions' uncommitted work, so a file that is present there proves nothing
    about what a reviewer or CI would package.

    Yields a namespace carrying the exported `root` as well as the build, because "present on disk
    but missing from the ZIP" needs a disk to ask about, and that disk must be the archive's.
    """
    try:
        toplevel = Path(subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True).stdout.strip()).resolve()
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git unavailable: {type(exc).__name__}")

    # `git archive` run from a subdirectory restricts its output to that subdirectory. If ROOT is
    # not the repository toplevel, these tests are already running from an exported tree - which IS
    # committed state - and archiving would silently produce an empty tar rather than failing.
    if toplevel != ROOT.resolve():
        pytest.skip(f"running from an export under {toplevel}; the working-tree build is "
                    f"already a build of committed state")

    export = tmp_path_factory.mktemp("committed-tree")
    archive = export / "HEAD.tar"
    try:
        with archive.open("wb") as fh:
            subprocess.run(["git", "archive", "HEAD"], cwd=str(toplevel),
                           stdout=fh, check=True, stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git archive unavailable: {type(exc).__name__}")
    tree = export / "tree"
    tree.mkdir()
    with tarfile.open(archive, "r:") as tar:
        tar.extractall(tree)  # noqa: S202 - our own repository's archive
    if not (tree / "amplify" / "functions" / "ecommerce" / "checkout" / "handler.py").is_file():
        pytest.skip("git archive HEAD produced no checkout handler")
    module = _provisioner()
    try:
        zip_bytes, members, errors, warnings = module.build_package(tree)
        yield SimpleNamespace(root=tree, zip_bytes=zip_bytes, members=members,
                              errors=errors, warnings=warnings)
    finally:
        sys.modules.pop("provision_checkout", None)


def _committed_on_disk(tree_root: Path, arcname: str) -> bool:
    if arcname == "handler.py":
        return (tree_root / "amplify" / "functions" / "ecommerce" / "checkout"
                / "handler.py").is_file()
    return (tree_root / "amplify" / "functions" / "shared" / arcname).is_file()


def test_no_module_present_on_disk_is_dropped_from_the_zip(built):
    """The packaging bug this file exists for: a file in the tree, missing from the artifact."""
    _, members, _, _ = built
    dropped = [name for name in REQUIRED if _on_disk(name) and name not in members]
    assert not dropped, ("present on disk but absent from the ZIP:\n  "
                         + "\n  ".join(dropped))


def test_the_whole_shared_tree_is_packaged(built):
    """Stated as a count rather than a list, so an exclusion rule that starts skipping a
    subdirectory is caught even for modules nobody thought to enumerate above."""
    _, members, _, _ = built
    on_disk = {f"lambda_utils/{p.relative_to(SHARED / 'lambda_utils').as_posix()}"
               for p in (SHARED / "lambda_utils").rglob("*.py")
               if "__pycache__" not in p.parts and "tests" not in p.parts}
    assert on_disk - set(members) == set()


def test_every_import_resolves(built):
    """Static, so it cannot fail falsely on a missing env var the way a real import would.
    `provided` is empty because this function has no layers: everything must come from the
    package, the python3.12 runtime, or the stdlib."""
    _, _, errors, _ = built
    assert not errors, "unresolved imports:\n  " + "\n  ".join(errors)


def test_the_configured_handler_symbol_exists(built):
    """A package can have every import satisfied and still be unbootable, because AWS is
    configured to call a symbol that does not exist - `Runtime.HandlerNotFound` on first
    invocation. Two functions in this fleet define `lambda_handler` rather than `handler`."""
    spec = importlib.util.spec_from_file_location("provision_checkout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dal = module._deploy_module(ROOT)
    _, members = dal.build_zip(
        dal.Spec("wecare-checkout", "ecommerce/checkout"))
    assert dal.validate_handler(members, "handler.handler") == []


def test_no_tests_or_caches_ship(built):
    _, members, _, _ = built
    junk = [name for name in members
            if "__pycache__" in name
            or name.endswith((".pyc", ".pyo"))
            or Path(name).name.startswith("test_")
            or "/tests/" in name]
    assert not junk, "shipped in the Lambda package:\n  " + "\n  ".join(junk)


def test_the_package_is_python_only(built):
    """No template, font or data file is read from disk anywhere in the checkout path, so a
    non-.py member would be an accident. Stated as an assertion rather than a comment, because
    "we don't need templates" is exactly the kind of claim that silently stops being true."""
    _, members, _, _ = built
    assert sorted(n for n in members if not n.endswith(".py")) == []


# ── the same questions, asked of committed state ──────────────────────────────
#
# The assertions above build from the working tree, which several sessions write to at once. These
# build from `git archive HEAD`, so their answer is reproducible from a SHA by anyone. Keeping both
# is the point: the first catches a packaging rule that drops a file, the second cannot pass or fail
# because of somebody else's uncommitted edit.

def test_no_committed_module_is_dropped_from_the_zip(committed):
    dropped = [name for name in REQUIRED
               if _committed_on_disk(committed.root, name) and name not in committed.members]
    assert not dropped, ("committed but absent from the ZIP:\n  " + "\n  ".join(dropped))


def test_every_import_resolves_in_committed_state(committed):
    """The assertion with no escape hatch, asked of the tree a reviewer can check out. A local
    checkout behind `origin/stack` legitimately lacks some REQUIRED modules; an unresolved import
    is never legitimate."""
    assert not committed.errors, ("unresolved imports at HEAD:\n  "
                                  + "\n  ".join(committed.errors))


def test_the_committed_package_ships_no_tests_or_caches(committed):
    junk = [name for name in committed.members
            if "__pycache__" in name
            or name.endswith((".pyc", ".pyo"))
            or Path(name).name.startswith("test_")
            or "/tests/" in name]
    assert not junk, "shipped in the Lambda package:\n  " + "\n  ".join(junk)


def test_the_committed_package_is_python_only(committed):
    assert sorted(n for n in committed.members if not n.endswith(".py")) == []


def test_the_committed_handler_symbol_exists(committed):
    module = _provisioner()
    try:
        dal = module._deploy_module(committed.root)
        _, members = dal.build_zip(dal.Spec("wecare-checkout", "ecommerce/checkout"))
        assert dal.validate_handler(members, "handler.handler") == []
    finally:
        sys.modules.pop("provision_checkout", None)


def test_an_uncommitted_sibling_is_visible_as_a_difference(built, committed):
    """Not a failure - a measurement. The two builds differ by exactly the files other sessions
    have not committed yet, and naming that difference is what stops a red working-tree run from
    being read as a packaging defect.
    """
    _, tree_members, _, _ = built
    only_in_tree = sorted(set(tree_members) - set(committed.members))
    only_in_committed = sorted(set(committed.members) - set(tree_members))
    # Committed state can never be missing a module the working tree has committed; anything here
    # is uncommitted work, which is allowed to exist but must not be invisible.
    assert all(name.endswith(".py") for name in only_in_tree + only_in_committed), (
        f"a non-python member appeared in one build only: "
        f"{only_in_tree + only_in_committed}")


def test_source_root_actually_packages_from_that_root(tmp_path):
    """A `--source-root` that is silently ignored is worse than not having one: the operator
    believes reviewed bytes shipped while the dirty tree shipped instead. Proven against a
    synthetic tree, so it does not depend on this checkout's git position.
    """
    spec = importlib.util.spec_from_file_location("provision_checkout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    shared = tmp_path / "amplify" / "functions" / "shared" / "lambda_utils"
    (shared / "ecommerce").mkdir(parents=True)
    (shared / "__init__.py").write_text("")
    (shared / "ecommerce" / "__init__.py").write_text("")
    (shared / "only_in_the_synthetic_root.py").write_text("MARKER = 'synthetic'\n")
    (shared / "b.py").write_text("x = 1\n")
    (shared / "c.py").write_text("y = 2\n")
    handler_dir = tmp_path / "amplify" / "functions" / "ecommerce" / "checkout"
    handler_dir.mkdir(parents=True)
    (handler_dir / "handler.py").write_text(
        "from lambda_utils import only_in_the_synthetic_root\n\n\ndef handler(e, c):\n"
        "    return only_in_the_synthetic_root.MARKER\n")

    _, members, errors, _ = module.build_package(tmp_path)
    assert errors == []
    assert "lambda_utils/only_in_the_synthetic_root.py" in members
    assert b"synthetic" in members["lambda_utils/only_in_the_synthetic_root.py"]
    # And nothing leaked in from the real repository.
    assert "lambda_utils/customer_auth.py" not in members


def test_a_source_root_without_a_checkout_handler_is_refused(tmp_path):
    """Fails loudly rather than falling back to the working tree, which would reintroduce the
    exact hazard --source-root exists to remove."""
    spec = importlib.util.spec_from_file_location("provision_checkout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(FileNotFoundError):
        module.build_package(tmp_path)


def test_the_package_is_deterministic(built):
    """Two builds of the same bytes must produce the same CodeSha256, or every dry run reports a
    spurious `WOULD UPDATE` and the comparison stops meaning anything."""
    zip_bytes, _, _, _ = built
    spec = importlib.util.spec_from_file_location("provision_checkout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    again, _, _, _ = module.build_package(ROOT)
    assert module.package_sha(zip_bytes) == module.package_sha(again)


# ── the two property assertions, asked of BOTH builds ─────────────────────────
#
# R6.1 (integer paise) and secret-handling (lazy credential reads) are the two properties here
# whose answer must be reproducible from a SHA, so they are the two that least belong on the
# working-tree build alone. They used to take `built` only - the fixture that packages whatever
# three other sessions have uncommitted - while every weaker assertion in this file was asked of
# both. `packaged_members` closes that: each runs twice, once over the tree and once over
# `git archive HEAD`.

@pytest.fixture(params=["working-tree", "committed"])
def packaged_members(request):
    """The member dict from one of the two builds. Skips with `committed` when git cannot."""
    if request.param == "working-tree":
        _, members, _, _ = request.getfixturevalue("built")
        return members
    return request.getfixturevalue("committed").members


def _import_time_calls(tree: ast.AST) -> list:
    """Every `Call` that runs when the module is IMPORTED, not when something is invoked.

    Computed as "every call that is not inside a function body", which is wider than the previous
    `tree.body` filtered to `Assign`/`Expr`/`AnnAssign` in three ways that each hid a real shape:

    - a module-scope `try:` / `if:` / `with:` wrapping the read (the single most likely spelling of
      an import-time secret fetch, since it would be written defensively),
    - a class-body assignment, which executes at import just as surely as a module-level one,
    - a decorator expression or a default argument value, which are evaluated at `def` time.

    Lambda bodies are deferred like function bodies. Decorators and defaults live outside
    `node.body`, so they stay in scope by construction.
    """
    deferred = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bodies = node.body
        elif isinstance(node, ast.Lambda):
            bodies = [node.body]
        else:
            continue
        for stmt in bodies:
            for inner in ast.walk(stmt):
                deferred.add(inner)
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and n not in deferred]


def test_no_packaged_module_reads_a_secret_at_import_time(packaged_members):
    """A module-scope `get_secret_value` caches the value for the life of the execution
    environment, so a rotation does not take effect until every warm sandbox recycles. The
    razorpay-webhook function was fixed for exactly this on 2026-09-19.

    Asked of EVERY packaged module rather than of two named files. The narrow version inspected
    `razorpay_orders.py` and `handler.py` only, and so did not cover `wix_ecom.py` - which is the
    one secret `wecare-checkout-role` can actually read, and therefore the one module where this
    regression would have a live consequence rather than a theoretical one.
    """
    readers, checked = [], 0
    assert "handler.py" in packaged_members, "the handler itself must always be packaged"
    for name, raw in sorted(packaged_members.items()):
        if not name.endswith(".py") or b"get_secret_value" not in raw:
            continue
        checked += 1
        tree = ast.parse(raw.decode("utf-8"), filename=name)
        for call in _import_time_calls(tree):
            if "get_secret_value" in ast.unparse(call.func):
                readers.append(f"{name}:{call.lineno}")
    assert checked, ("no packaged module mentions get_secret_value at all — the package is not "
                     "what this test thinks it is")
    assert not readers, ("reads a secret at import time (breaks rotation until every warm "
                         "sandbox recycles):\n  " + "\n  ".join(readers))


def test_no_float_arithmetic_on_the_money_path(packaged_members):
    """R6.1. `0.1 + 0.2` is not `0.3` in binary floating point, and a one-paise mismatch against
    the checkout total must fail closed - so a rounding artefact becomes a refused order.

    Presence is asserted before parsing. `if name not in members: continue` meant a money module
    DROPPED from the package made this test pass - the same succeeds-at-doing-nothing shape the
    evidence document calls out for `git archive` run from a subdirectory. A money module that is
    not in the package is the more serious defect, not the excuse to skip the check.
    """
    # `wix_ecom.py` was retired with the Wix exit; the AWS-native money path adds
    # `catalog_pricing.py` (coupon/tax/supply pricing). R6.1 holds over the native modules.
    money = ("lambda_utils/ecommerce/checkout_pricing.py",
             "lambda_utils/ecommerce/money.py",
             "lambda_utils/ecommerce/catalog_pricing.py",
             "lambda_utils/integrations/razorpay_orders.py")
    missing = [name for name in money if name not in packaged_members]
    assert not missing, ("money module(s) absent from the package, so R6.1 could not be checked "
                         "over them:\n  " + "\n  ".join(missing))
    for name in money:
        tree = ast.parse(packaged_members[name].decode("utf-8"), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "float":
                pytest.fail(f"{name}:{node.lineno} calls float() on the money path")
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                pytest.fail(f"{name}:{node.lineno} holds a float literal "
                            f"({node.value!r}) on the money path")
