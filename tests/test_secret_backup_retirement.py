"""Future archive selection excludes retired credentials without reading values."""
import ast
from pathlib import Path


def selector():
    source = Path(__file__).resolve().parents[1] / "scripts/secrets_backup.py"
    tree = ast.parse(source.read_text())
    nodes = [n for n in tree.body if (
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
            t.id == "RETIRED_SECRET_PREFIXES" for t in n.targets)) or (
        isinstance(n, ast.FunctionDef) and n.name == "backup_secret_ids")]
    scope = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
    return scope["backup_secret_ids"]


def test_restored_provider_secrets_cannot_reenter_future_backup():
    choose = selector()
    assert choose({"wecare/wix/headless-api-key", "wecare/meta-system-user-token"},
                  ["wecare/wix/app-oauth", "wecare/backup/recovery-passphrase"]) == [
        "wecare/backup/recovery-passphrase", "wecare/meta-system-user-token"]


def test_unrelated_required_secrets_are_preserved_and_deduplicated():
    choose = selector()
    assert choose({"wecare/razorpay/api", "wecare/otp/pepper"},
                  ["wecare/razorpay/api", "wecare/flow-private-key"]) == [
        "wecare/flow-private-key", "wecare/otp/pepper", "wecare/razorpay/api"]
