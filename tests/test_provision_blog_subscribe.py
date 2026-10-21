"""Static contract for the blog-subscribe provisioner.

No AWS call is needed here: this pins the blast radius and route surface the source is allowed to
create. Live read-back remains provision_blog_subscribe.py --verify.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/provision_blog_subscribe.py"
HANDLER = ROOT / "amplify/functions/auth/blog-subscribe/handler.py"


def _source():
    return SCRIPT.read_text(encoding="utf-8")


def test_only_the_one_public_subscription_path_is_declared():
    source = _source()
    assert 'ROUTE_KEYS = ("POST /blog/subscribe", "OPTIONS /blog/subscribe")' in source
    assert "/contacts" not in source


def test_role_can_write_contacts_and_otp_proofs_but_has_no_cognito_or_delete():
    source = _source()
    tree = ast.parse(source, filename=str(SCRIPT))
    text = ast.unparse(tree)
    assert "dynamodb:GetItem" in text
    assert "dynamodb:PutItem" in text
    assert "dynamodb:UpdateItem" in text
    assert "dynamodb:Query" in text
    assert "ses:SendEmail" in text
    assert "lambda:InvokeFunction" in text
    # DeleteItem exists only to release a phone/email claim after a successful identity change.
    assert text.count("dynamodb:DeleteItem") == 1
    assert "IdentityClaimsTable" in text
    assert "dynamodb:Scan" not in text
    assert "cognito-idp" not in text.lower()


def test_contacts_access_is_scoped_to_the_contacts_table_and_indexes():
    source = _source()
    assert 'CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"' in source
    assert 'table/{CONTACTS_TABLE}/index/*' in source


def test_deploy_registry_points_at_this_provisioner():
    deploy = (ROOT / "scripts/deploy_all_lambdas.py").read_text(encoding="utf-8")
    assert '"wecare-blog-subscribe"' in deploy
    assert 'provisioned_by="python scripts/provision_blog_subscribe.py"' in deploy


def test_handler_never_calls_the_staff_contacts_http_endpoint():
    source = HANDLER.read_text(encoding="utf-8")
    assert '"/contacts"' not in source
    assert "require_auth" not in source
    # The public door writes through its own constrained server code after proof validation.
    assert "_proof_valid" in source
    assert "VERIFICATION_REQUIRED" in source
    assert 'BLOG_TAG = "blog-subscriber"' in source
