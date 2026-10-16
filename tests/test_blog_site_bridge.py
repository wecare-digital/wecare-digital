"""Contracts for the publish -> Amplify -> static-site verification bridge."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "operations" / "seo-tools"))
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_blog_sources import FakeS3, FakeTable  # noqa: E402


class FakeAmplify:
    def __init__(self):
        self.starts = []
        self.status = "SUCCEED"

    def start_job(self, **kwargs):
        self.starts.append(dict(kwargs))
        return {"jobSummary": {"jobId": "1922", "status": "PENDING"}}

    def get_job(self, **kwargs):
        return {"job": {"summary": {"jobId": kwargs["jobId"], "status": self.status}}}


@pytest.fixture()
def env(monkeypatch):
    import blog_queue
    import blog_site_bridge as bridge
    import blog_sources
    import storage

    table = FakeTable()
    s3 = FakeS3()
    amplify = FakeAmplify()
    queued = {"build": [], "check": [], "verify": []}

    monkeypatch.setattr(storage, "table", lambda: table)
    monkeypatch.setattr(blog_sources, "s3_client", lambda: s3)
    monkeypatch.setattr(bridge, "amplify_client", lambda: amplify)
    monkeypatch.setattr(
        blog_queue, "enqueue_site_build",
        lambda generation, actor, delay_seconds=0: (
            queued["build"].append((generation, actor, delay_seconds))
            or {"queued": 1, "failed": 0, "configured": True}))
    monkeypatch.setattr(
        blog_queue, "enqueue_site_check",
        lambda job_id, attempt=1, delay_seconds=0: (
            queued["check"].append((job_id, attempt, delay_seconds))
            or {"queued": 1, "failed": 0, "configured": True}))
    monkeypatch.setattr(
        blog_queue, "enqueue_site_verify",
        lambda source_ids, job_id, attempt=1, delay_seconds=0: (
            queued["verify"].append((list(source_ids), job_id, attempt, delay_seconds))
            or {"queued": len(source_ids), "failed": 0, "configured": True,
                "failedSourceIds": []}))

    def article(record_id: str, slug: str):
        now = storage.now_iso()
        row = {
            "id": record_id,
            "recordType": blog_sources.ARTICLE_WORK_RECORD_TYPE,
            "createdAt": now,
            "updatedAt": now,
            "slug": "parent-source",
            "parentSourceId": "",
            "category": "Conversations",
            "batchId": "blogbatch_test",
            "editorialStatus": "PUBLISHED",
            "articleStatus": "PUBLISHED",
            "siteVerifyState": "",
            "draftRecord": {
                "title": slug.replace("-", " ").title(),
                "slug": slug,
                "seoTitle": slug.replace("-", " ").title() + " | WECARE.DIGITAL",
                "metaDescription": "A useful description long enough for the publication contract.",
                "contentMarkdown": "A complete approved article body with enough substance.",
                "status": "PUBLISHED",
            },
            "pipeline": {
                **blog_sources.empty_pipeline(),
                "publishStatus": "PUBLISHED",
                "postId": "blog_" + record_id[-1],
                "postUrl": f"https://wecare.digital/post/{slug}",
                "publishedAt": now,
            },
        }
        table.items[record_id] = storage._clean(row)
        return record_id

    return {
        "table": table, "s3": s3, "amplify": amplify, "queued": queued,
        "bridge": bridge, "bs": blog_sources, "storage": storage, "article": article,
    }


def test_two_publishes_coalesce_into_one_delayed_build(env):
    first = env["article"]("blogwork_1", "first-post")
    second = env["article"]("blogwork_2", "second-post")

    one = env["bridge"].note_published(first, "publisher")
    two = env["bridge"].note_published(second, "publisher")

    assert one["scheduled"] is True
    assert two["scheduled"] is False
    assert two["coalesced"] is True
    assert len(env["queued"]["build"]) == 1
    generation, actor, delay = env["queued"]["build"][0]
    assert generation == 1
    assert actor == "publisher"
    assert delay == env["bridge"].COALESCE_DELAY_SECONDS
    assert env["bridge"].control()["generation"] == 2


def test_one_amplify_build_snapshots_every_pending_article(env):
    first = env["article"]("blogwork_1", "first-post")
    second = env["article"]("blogwork_2", "second-post")
    env["bridge"].note_published(first, "publisher")
    env["bridge"].note_published(second, "publisher")

    result = env["bridge"].start_build("site-bridge")

    assert result["started"] is True
    assert result["jobId"] == "1922"
    assert result["articles"] == 2
    assert len(env["amplify"].starts) == 1
    assert env["amplify"].starts[0]["appId"] == env["bridge"].APP_ID
    assert env["amplify"].starts[0]["branchName"] == env["bridge"].BRANCH_NAME
    assert env["queued"]["check"] == [
        ("1922", 1, env["bridge"].CHECK_DELAY_SECONDS)]
    for source_id in (first, second):
        row = env["bs"].get_source(source_id)
        assert row["pipeline"]["siteBuildStatus"] == "BUILDING"
        assert row["pipeline"]["siteBuildJobId"] == "1922"


def test_successful_amplify_deploy_fans_out_site_verification(env):
    source_id = env["article"]("blogwork_1", "first-post")
    env["bridge"].note_published(source_id, "publisher")
    env["bridge"].start_build("site-bridge")

    result = env["bridge"].check_build("1922", attempt=1)

    assert result["status"] == "VERIFYING"
    assert result["verificationQueued"] == 1
    assert env["queued"]["verify"] == [([source_id], "1922", 1, 0)]
    row = env["bs"].get_source(source_id)
    assert row["pipeline"]["siteBuildStatus"] == "DEPLOYED"
    assert row["pipeline"]["verifyStatus"] == "SITE_DEPLOYED"


def test_static_site_verification_checks_page_sitemap_search_and_rss(env, monkeypatch):
    import blog_verify

    slug = "a-real-post"
    title = "A Real Post"
    monkeypatch.setattr(blog_verify, "expectation", lambda source_id: {
        "slug": slug, "title": title,
    })

    canonical = f"https://wecare.digital/post/{slug}/"
    responses = {
        f"/post/{slug}/": (200, f"<html><head><title>{title}</title>"
                           f'<link rel="canonical" href="{canonical}"></head></html>'),
        "/sitemap.xml": (200, f"<url><loc>{canonical}</loc></url>"),
        "/blog/search-index.json": (200, json.dumps({
            "ok": True, "posts": [{"slug": slug, "title": title}]})),
        "/blog/rss.xml": (200, f"<item><link>{canonical}</link></item>"),
    }

    def fake_fetch(url):
        path = "/" + url.split("wecare.digital/", 1)[1].split("?", 1)[0]
        return responses[path]

    monkeypatch.setattr(env["bridge"], "_fetch_text", fake_fetch)
    result = env["bridge"].verify_static_surfaces("blogwork_1", "1922")

    assert result["assertions"] == 6
    assert result["passed"] == 6
    assert result["failed"] == 0
    assert result["verified"] is True


def test_only_bridge_can_move_article_to_final_verified(env, monkeypatch):
    source_id = env["article"]("blogwork_1", "final-post")
    env["bridge"].note_published(source_id, "publisher")
    env["bridge"].start_build("site-bridge")
    env["bridge"].check_build("1922", attempt=1)

    import blog_verify
    monkeypatch.setattr(blog_verify, "run", lambda source_id, actor: {
        "verificationRunId": "blogver_native",
        "status": "VERIFIED",
    })
    monkeypatch.setattr(env["bridge"], "verify_static_surfaces", lambda source_id, job_id: {
        "sourceId": source_id, "jobId": job_id, "slug": "final-post",
        "title": "Final Post", "canonical": "https://wecare.digital/post/final-post/",
        "assertions": 6, "passed": 6, "failed": 0, "failedAssertions": [],
        "fetchErrors": {}, "results": [], "verified": True,
    })

    result = env["bridge"].verify_article(source_id, "1922", actor="site-bridge")

    assert result["status"] == "VERIFIED"
    row = env["bs"].get_source(source_id)
    assert row["articleStatus"] == "VERIFIED"
    assert row["draftRecord"]["status"] == "VERIFIED"
    assert row["pipeline"]["backendVerifyStatus"] == "VERIFIED"
    assert row["pipeline"]["siteVerifyStatus"] == "VERIFIED"
    assert row["pipeline"]["verifyStatus"] == "VERIFIED"
    assert row["pipeline"]["verifiedAt"]
    reports = [
        value for value in env["table"].items.values()
        if value.get("recordType") == env["bridge"].VERIFY_RECORD_TYPE
    ]
    assert len(reports) == 1
    assert reports[0]["status"] == "VERIFIED"



def test_deploy_uses_managed_policy_for_amplify_bridge():
    """The shared role is already at its aggregate inline-policy byte ceiling."""
    source = (ROOT / "scripts" / "deploy_seo_tools.py").read_text(encoding="utf-8")
    assert 'AMPLIFY_BRIDGE_POLICY_NAME = "wecare-blog-site-bridge-amplify"' in source
    assert '"amplify:StartJob", "amplify:GetJob"' in source
    assert 'branches/{AMPLIFY_BRANCH}/jobs/*' in source
    assert "attach_role_policy" in source
    # The Amplify actions must not be added back to the already-full source-intake inline policy.
    intake = source.split("def ensure_blog_source_perms()", 1)[1].split(
        "def ensure_blog_site_bridge_perms()", 1)[0]
    assert "amplify:StartJob" not in intake
