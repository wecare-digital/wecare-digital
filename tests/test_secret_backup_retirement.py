"""Future archive selection keeps only approved credentials, without reading values."""
import ast
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def selector():
    source = SCRIPTS / "secrets_backup.py"
    tree = ast.parse(source.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in ("approved_secret", "backup_secret_ids")]
    scope = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
    return scope["backup_secret_ids"]


def test_secrets_outside_the_provider_allow_list_cannot_enter_a_future_backup():
    """A credential restored inside its recovery window is not approved, so it stays out."""
    choose = selector()
    assert choose({"wecare/retired-vendor/api-key", "wecare/meta-system-user-token"},
                  ["wecare/retired-vendor/app-oauth", "wecare/backup/recovery-passphrase"]) == [
        "wecare/backup/recovery-passphrase", "wecare/meta-system-user-token"]


def test_unrelated_required_secrets_are_preserved_and_deduplicated():
    choose = selector()
    assert choose({"wecare/razorpay/api", "wecare/otp/pepper"},
                  ["wecare/razorpay/api", "wecare/flow-private-key"]) == [
        "wecare/flow-private-key", "wecare/otp/pepper", "wecare/razorpay/api"]


def test_every_required_secret_is_approved():
    """A required secret the allow-list rejected would be dropped from every archive, so the
    two lists must agree; the run summary names any exclusion, but this catches it first."""
    source = SCRIPTS / "secrets_backup.py"
    tree = ast.parse(source.read_text())
    required = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "REQUIRED_SECRET_IDS"
                            for t in n.targets))
    assert selector()(set(), required) == sorted(required)
