import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "amplify" / "functions" / "operations" / "blog-auto-audit" / "rules.py"
HANDLER = ROOT / "amplify" / "functions" / "operations" / "blog-auto-audit" / "handler.py"
PROVISION = ROOT / "scripts" / "provision_blog_auto_audit.py"

spec = importlib.util.spec_from_file_location("blog_auto_audit_rules", RULES)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)


def test_protected_corpus_contract_is_exact():
    assert rules.PROTECTED_TOTAL == 1430
    assert rules.PROTECTED_COUNTS == {"Conversations": 976, "Gastronomy": 454}
    assert rules.AUTHOR == "Anew by WECARE.DIGITAL"


def test_safe_patch_repairs_batch5_without_identity_fields():
    post = {
        "title": "Prakruti and Vikruti",
        "content": "* The Dosha Questionnaire\n* Recipe symbols and modification notes",
        "richContent": {
            "nodes": [{"textData": {"text": "Follow ’s distinction by treating food choice as contextual rather than fixed."}}],
        },
        "slug": "keep-me",
        "authorName": rules.AUTHOR,
        "publishedAt": "2026-01-01T00:00:00Z",
    }
    updates, fields, count = rules.safe_patch(post)
    assert "Traditional dosha self-observation" in updates["content"]
    assert "Notes on contextual food adjustments" in updates["content"]
    assert updates["richContent"]["nodes"][0]["textData"]["text"] == (
        "Treat food choice as contextual rather than fixed."
    )
    assert count == 3
    assert set(fields) == {"content", "richContent"}
    assert "slug" not in updates
    assert "authorName" not in updates
    assert "publishedAt" not in updates


def test_unknown_source_scaffolding_is_review_only():
    post = {
        "content": "The breakfast chapter says something that needs editorial review.",
        "richContent": {},
    }
    updates, _, _ = rules.safe_patch(post)
    findings = rules.review_findings(post)
    assert updates == {}
    assert any(f["code"] == "SOURCE_STRUCTURE" for f in findings)


def test_external_url_is_review_only():
    findings = rules.review_findings({"content": "See https://example.com/source."})
    assert any(f["code"] == "PUBLIC_EXTERNAL_URL" for f in findings)


def test_handler_never_deletes_or_changes_identity_fields():
    source = HANDLER.read_text(encoding="utf-8")
    assert "delete_item" not in source
    assert "batch_writer" not in source
    assert 'Attr("authorName").eq(rules.AUTHOR)' in source
    assert 'Attr("publishedAt").eq(post.get("publishedAt"))' in source
    assert 'Attr("slug").eq(post.get("slug"))' in source


def test_provisioning_is_dedicated_and_scheduled():
    source = PROVISION.read_text(encoding="utf-8")
    assert 'FUNCTION_NAME = "wecare-blog-auto-audit"' in source
    assert 'EXEC_ROLE = "wecare-blog-auto-audit-role"' in source
    assert 'SCHEDULE_NAME = "wecare-blog-auto-audit-daily"' in source
    assert '"BLOG_AUTO_APPLY": "true"' in source
    assert '"dynamodb:DeleteItem"' not in source
    assert '"s3:' not in source
