"""Offline tests for paid Drop Docs' published Meta FLOW_JSON release gate."""
from copy import deepcopy
from io import BytesIO
import json

from scripts import check_drop_docs_published_flow_live as audit

GOOD_LINK = "https://mmg.whatsapp.net/m1/test-flow.json?temporary=ok"


def reviewed_asset():
    return json.loads(audit.FLOW_SOURCE.read_text(encoding="utf-8"))


def test_reviewed_drop_docs_json_matches_signed_completion_contract():
    expected = reviewed_asset()
    report = audit.compare_published_to_source(expected, expected)
    assert report["ok"] is True
    assert report["screens"] == ["SELECT_TARGET", "NOTE", "UPLOAD", "CONFIRMATION"]
    assert report["semanticSha256"] == report["sourceSemanticSha256"]


def test_old_or_mutated_published_flow_is_never_accepted():
    expected = reviewed_asset()
    changed = deepcopy(expected)
    changed["screens"][-1]["id"] = "COMPLETE_UNREVIEWED"
    assert not audit.compare_published_to_source(changed, expected)["ok"]
    changed = deepcopy(expected)
    changed["screens"][-1]["terminal"] = False
    assert not audit.compare_published_to_source(changed, expected)["ok"]
    changed = deepcopy(expected)
    changed["screens"][-1]["layout"]["children"] = []
    assert not audit.compare_published_to_source(changed, expected)["ok"]


def test_meta_asset_url_must_be_https_and_from_allowlisted_cdn():
    assert audit.trusted_meta_asset_url(GOOD_LINK)
    for link in (
        "http://mmg.whatsapp.net/m1/a.json",
        "https://mmg.whatsapp.net.evil.example/a.json",
        "https://127.0.0.1/a.json",
        "https://user:pass@mmg.whatsapp.net/a.json",
        "https://mmg.whatsapp.net/flow.txt",
        "https://mmg.whatsapp.net/a.json#fragment",
    ):
        assert not audit.trusted_meta_asset_url(link)


class FakeLambda:
    def __init__(self, flow_id, *, assets=None, code=200):
        self.flow_id = flow_id
        self.assets = assets if assets is not None else [
            {"name": "flow.json", "assetType": "FLOW_JSON", "downloadUrl": GOOD_LINK}]
        self.code = code
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        event = json.loads(kwargs["Payload"].decode("utf-8"))
        assert kwargs["InvocationType"] == "RequestResponse"
        assert event == {
            "httpMethod": "GET", "path": "/wa-business/flows/assets",
            "queryStringParameters": {"flowId": self.flow_id}}
        envelope = {"statusCode": self.code,
                    "body": json.dumps({"flowId": self.flow_id, "assets": self.assets})}
        return {"StatusCode": 200, "Payload": BytesIO(json.dumps(envelope).encode())}


def test_live_meta_asset_read_is_exactly_one_get_and_never_a_send():
    client = FakeLambda("39581903361452878")
    assert audit.read_meta_flow_asset_url(client, client.flow_id) == GOOD_LINK
    assert len(client.calls) == 1
    assert client.calls[0]["FunctionName"] == audit.FLOW_READER


def test_missing_or_unsafe_provider_asset_fails_closed():
    import pytest
    flow_id = "39581903361452878"
    for assets in ([], [{"name": "flow.json", "assetType": "FLOW_JSON",
                           "downloadUrl": "http://unsafe.invalid/x.json"}],
                   [{"name": "unrelated.png", "assetType": "IMAGE"}]):
        with pytest.raises(RuntimeError):
            audit.read_meta_flow_asset_url(FakeLambda(flow_id, assets=assets), flow_id)
    with pytest.raises(RuntimeError):
        audit.read_meta_flow_asset_url(FakeLambda(flow_id, code=403), flow_id)


class FakeResponse:
    def __init__(self, body, final_url=GOOD_LINK):
        self.body = body
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def geturl(self):
        return self.final_url

    def read(self, size):
        return self.body[:size]


class FakeOpener:
    def __init__(self, body, final_url=GOOD_LINK):
        self.response = FakeResponse(body, final_url)

    def open(self, request, timeout=None):
        assert request.full_url == GOOD_LINK and timeout == 15
        return self.response


def test_download_validates_size_and_redirects_without_network():
    import pytest
    doc = reviewed_asset()
    assert audit.load_published_flow_json(
        GOOD_LINK, opener=FakeOpener(json.dumps(doc).encode())) == doc
    with pytest.raises(RuntimeError):
        audit.load_published_flow_json(
            GOOD_LINK, opener=FakeOpener(b"x" * (audit.MAX_FLOW_BYTES + 1)))
    with pytest.raises(RuntimeError):
        audit.load_published_flow_json(
            GOOD_LINK, opener=FakeOpener(b"{}", "https://evil.example/x.json"))
