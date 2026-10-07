"""A Drop Docs document is never a customer document while its object is reachable under ``o/``.

Why this file exists at all
---------------------------
`inbound-whatsapp-handler` writes an inbound attachment to
``o/stack/whatsapp-media/incoming/``, and CloudFront ``E2GP22R4BIFGQ3`` serves the whole
``o/`` root **unauthenticated**. ``o/`` is a location, not a permission - only ``secure/``
is gated, by the ``wecare-get-miss-redirect`` Lambda@Edge. So an object that arrived over
WhatsApp is readable by anyone holding its URL, and "we will remember to copy it" is not a
control.

The control is the ORDER of two writes. `dropdocs_storage.promote_to_secure` copies the
object into ``secure/`` and HEADs the destination to prove it landed;
`service_request_store.attach_document` refuses to write a ``DOC#`` row for a key that is
not ``media_paths.is_gated``. Because the registration is last, every failure mode leaves
*no row at all* rather than a customer document pointing at a public object. These tests
pin that ordering, not the happy path.

What is deliberately NOT asserted
---------------------------------
That the public original is gone. It is not, and cannot be: no role in this account holds
``s3:DeleteObject``, by design. The original expires under the existing
``s3_whatsapp_media_incoming`` TTL in ``operations/system-cleanup``. That residual exposure
is asserted to be *reported* - exactly one warning, carrying the retained key under the
alert ``DROPDOCS_PUBLIC_SOURCE_RETAINED`` - because a silent residual exposure is the worse
outcome. Case (f) asserts no ``delete_object`` call can ever appear, on the AST, so nobody
"tidies this up" by adding one.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
FUNC_DIR = ROOT / "amplify" / "functions" / "core" / "secure-files"
SHARED = ROOT / "amplify" / "functions" / "shared"
STORAGE_MODULE = SHARED / "lambda_utils" / "ecommerce" / "dropdocs_storage.py"

for path in (str(ROOT / "tests"), str(FUNC_DIR), str(SHARED)):
    if path not in sys.path:
        sys.path.insert(0, path)

from service_requests_fake_dynamo import RequestTable  # noqa: E402

from lambda_utils import customer_auth, media_paths  # noqa: E402
from lambda_utils.ecommerce import dropdocs_storage  # noqa: E402
from lambda_utils.ecommerce import service_request_store as store  # noqa: E402
from lambda_utils.ecommerce.service_requests import DROP_DOCS, SUBMIT_REQUEST  # noqa: E402

OWNER = "11111111-2222-3333-4444-555555555555"
STRANGER = "99999999-8888-7777-6666-555555555555"
PUBLIC_ID = "WD-REQ-ABCDEFGH"
REQUEST_INTERNAL = "REQ#01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"
SOURCE_KEY = "o/stack/whatsapp-media/incoming/wecare-digital-ab12.pdf"
DOCUMENT_BYTES = b"%PDF-1.7 a trade licence, as a customer actually sent it\n"
BUCKET = "wecare-digital-get"


# ── fakes ─────────────────────────────────────────────────────────────────────

class FakeS3Error(Exception):
    """Stands in for ``botocore.exceptions.ClientError``.

    A bare exception is enough: `promote_to_secure` converts *any* S3 refusal into
    ``DocumentPromotionFailed``, which is the fail-closed behaviour these tests care about.
    Narrowing it to a real ``ClientError`` would test botocore rather than the ordering.
    """


class FakeS3:
    """Records every S3 call by name, so the call SET can be asserted as an equality.

    A set equality is the point: it catches a `delete_object` somebody adds later just as
    loudly as it catches a missing `head_object`. Anything this fake does not implement
    raises, rather than quietly succeeding.
    """

    def __init__(self, *, content_type: str = "application/pdf",
                 body: bytes = DOCUMENT_BYTES) -> None:
        self.objects: Dict[str, Dict[str, Any]] = {
            SOURCE_KEY: {"body": body, "contentType": content_type}
        }
        self.calls: List[str] = []
        self.call_log: List[Dict[str, Any]] = []
        self.fail_on: Dict[str, Exception] = {}

    def _record(self, name: str, **kwargs) -> None:
        self.calls.append(name)
        self.call_log.append({"operation": name, **kwargs})
        if name in self.fail_on:
            raise self.fail_on[name]

    def get_object(self, Bucket=None, Key=None):  # noqa: N803 - boto3 casing
        self._record("get_object", Bucket=Bucket, Key=Key)
        held = self.objects.get(Key)
        if held is None:
            raise FakeS3Error("NoSuchKey")

        class _Body:
            def read(self_inner):
                return held["body"]

        return {"Body": _Body(), "ContentType": held["contentType"]}

    def copy_object(self, Bucket=None, Key=None, CopySource=None, ContentType=None,
                    MetadataDirective=None):  # noqa: N803
        self._record("copy_object", Bucket=Bucket, Key=Key, CopySource=CopySource,
                     ContentType=ContentType, MetadataDirective=MetadataDirective)
        source = self.objects.get((CopySource or {}).get("Key"))
        if source is None:
            raise FakeS3Error("NoSuchKey")
        self.objects[Key] = {"body": source["body"],
                             "contentType": ContentType or source["contentType"]}
        return {}

    def head_object(self, Bucket=None, Key=None):  # noqa: N803
        self._record("head_object", Bucket=Bucket, Key=Key)
        held = self.objects.get(Key)
        if held is None:
            raise FakeS3Error("NotFound")
        return {"ContentLength": len(held["body"]), "ContentType": held["contentType"]}

    def __getattr__(self, name):  # pragma: no cover - reached only by an unexpected call
        def _unsupported(*_args, **_kwargs):
            raise AssertionError(f"the Drop Docs path must not call s3.{name}")
        return _unsupported


def _identity(customer_id: str = OWNER) -> customer_auth.CustomerIdentity:
    return customer_auth.CustomerIdentity(customer_id=customer_id,
                                          phone="+918100640044", subject=customer_id)


def _seeded_table(*, kind: str = DROP_DOCS, owner: str = OWNER) -> RequestTable:
    """A request table holding ONE paid request and its public-id pointer.

    Seeded rather than activated through the money path: this file is about storage
    privacy, and `tests/test_service_lines_dropdocs_vault.py` already pins that a Drop Docs
    REQ# row can only come into existence behind a paid-order claim.
    """
    table = RequestTable()
    table.seed({"requestId": REQUEST_INTERNAL, "kind": kind, "publicRequestId": PUBLIC_ID,
                "customerId": owner, "status": "SUBMITTED", "statusRank": 10,
                "createdAt": 1, "updatedAt": 1})
    table.seed({"requestId": f"REQNO#{PUBLIC_ID}", "ownerCustomerId": owner,
                "targetRequestId": REQUEST_INTERNAL, "reservedAt": 1})
    return table


def _doc_rows(table: RequestTable) -> List[str]:
    return [key for key in table.rows if str(key).startswith(store.DOC_PREFIX)]


@pytest.fixture()
def handler(monkeypatch):
    """The locker handler, loaded by PATH under a name of its own.

    64 files in this repo are called ``handler.py`` and several test modules import a bare
    ``handler``, so whichever runs first owns ``sys.modules["handler"]``. A unique module
    name removes the shared key, so this file neither depends on nor affects collection
    order - the same reason `tests/test_secure_files.py` does it.
    """
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("SECURE_FILES_PAYMENT_ENABLED", raising=False)
    monkeypatch.delenv("DROPDOCS_ATTACH_ENABLED", raising=False)

    spec = importlib.util.spec_from_file_location(
        "wecare_dropdocs_locker_handler", FUNC_DIR / "handler.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wecare_dropdocs_locker_handler"] = module
    spec.loader.exec_module(module)
    return module


def _attach_event(**over) -> Dict[str, Any]:
    body = {"requestId": PUBLIC_ID, "sourceKey": SOURCE_KEY}
    body.update(over)
    return {"requestContext": {"http": {"method": "POST",
                                        "path": "/secure-files/dropdocs/attach"},
                               "stage": "$default"},
            "headers": {"authorization": "Bearer t", "origin": "https://wecare.digital"},
            "body": json.dumps(body)}


def _wire(handler, monkeypatch, s3: FakeS3, table: RequestTable, *, enabled: bool = True):
    if enabled:
        monkeypatch.setenv("DROPDOCS_ATTACH_ENABLED", "true")
    monkeypatch.setattr(handler, "_customer_identity",
                        lambda _event: {"username": "+918100640044",
                                        "phone": "918100640044", "subject": OWNER})
    monkeypatch.setattr(handler, "_s3_client", lambda: s3)
    monkeypatch.setattr(handler, "_table", lambda name: table)


# ── (a) the promotion itself ──────────────────────────────────────────────────

def test_a_a_public_source_is_copied_into_secure_under_its_content_hash():
    import hashlib

    s3 = FakeS3()
    result = dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=SOURCE_KEY)

    digest = hashlib.sha256(DOCUMENT_BYTES).hexdigest()
    assert result["sha256"] == digest
    assert result["promoted"] is True
    assert result["publicSourceRetained"] is True
    assert result["contentType"] == "application/pdf"
    assert result["sizeBytes"] == len(DOCUMENT_BYTES)

    key = result["storageKey"]
    assert media_paths.is_gated(key)
    assert key == f"secure/u/dropdocs/wecare-digital-{digest}.pdf"
    # the basename carries the hash of the BYTES, not of the name
    assert key.rsplit("/", 1)[-1] == f"wecare-digital-{digest}.pdf"


def test_a_the_s3_call_set_is_exactly_read_copy_prove_and_never_delete():
    """A set equality, so a `delete_object` added later fails here as well as in case (f)."""
    s3 = FakeS3()
    dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=SOURCE_KEY)
    assert set(s3.calls) == {"get_object", "copy_object", "head_object"}
    assert "delete_object" not in s3.calls
    # and the HEAD is of the DESTINATION, which is what proves the copy landed
    head = [call for call in s3.call_log if call["operation"] == "head_object"]
    assert len(head) == 1
    assert media_paths.is_gated(head[0]["Key"])
    copy = [call for call in s3.call_log if call["operation"] == "copy_object"][0]
    assert copy["MetadataDirective"] == "REPLACE"
    assert copy["ContentType"] == "application/pdf"  # preserved, not re-guessed
    assert copy["CopySource"] == {"Bucket": BUCKET, "Key": SOURCE_KEY}


def test_a_the_head_comes_after_the_copy_not_before():
    """Ordering, not presence. HEADing before the copy proves nothing about the copy."""
    s3 = FakeS3()
    dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=SOURCE_KEY)
    assert s3.calls.index("copy_object") < s3.calls.index("head_object")


def test_a_an_already_gated_source_is_not_copied_anywhere():
    """A browser upload already landed in ``secure/u/`` via the locker's presigned PUT.

    It is still read, because `attach_document` keys its row on the content hash and a row
    with no digest could never converge on a replay - but nothing is copied and the key
    returned is the source key itself, so no object moves between roots.
    """
    gated = "secure/u/wecare-digital-deadbeef.pdf"
    s3 = FakeS3()
    s3.objects[gated] = {"body": DOCUMENT_BYTES, "contentType": "application/pdf"}

    result = dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=gated)

    assert result["storageKey"] == gated
    assert result["promoted"] is False
    assert result["publicSourceRetained"] is False
    assert set(s3.calls) == {"get_object"}


def test_a_an_extension_is_whitelisted_exactly_as_the_locker_does_it(handler):
    """Shared discipline, separately implemented: the result lands in an S3 key."""
    for name in ("a.pdf", "a.PNG", "a.tar.gz", "noextension", "a.verylongextension",
                 "a.p df", "a.../../etc", ""):
        assert dropdocs_storage.safe_extension(name) == handler._safe_extension(name)
    # a dot in a DIRECTORY segment must not become the extension
    assert dropdocs_storage.safe_extension("o/a.b/c") == ""


# ── (b) the fail-closed gate: no row for a non-gated key ──────────────────────

def test_b_a_non_gated_storage_key_writes_no_doc_row():
    """THE load-bearing test. The refusal must come before any write, not after."""
    table = _seeded_table()
    with pytest.raises(dropdocs_storage.DocumentNotPrivate):
        store.attach_document(table, _identity(), PUBLIC_ID,
                              storage_key=SOURCE_KEY, sha256="a" * 64,
                              content_type="application/pdf", size_bytes=10,
                              source_key=SOURCE_KEY, public_source_retained=True)
    assert _doc_rows(table) == []
    # not merely "no DOC# row" - nothing was written at all
    assert [name for name, _ in table.applied] == []


@pytest.mark.parametrize("key", ["o/stack/whatsapp-media/incoming/x.pdf",
                                 "stack/whatsapp-media/incoming/x.pdf",
                                 "secure-ish/u/x.pdf", "", None,
                                 "https://wecare.digital/get/o/x.pdf"])
def test_b_every_shape_of_public_key_is_refused(key):
    """Including a LEGACY un-rooted key, which `media_paths.canonical` roots under ``o/``.

    That one matters: ``stack/whatsapp-media/incoming/x.pdf`` *looks* prefix-free and is
    public, which is precisely the trap `canonical` exists to close.
    """
    table = _seeded_table()
    with pytest.raises(dropdocs_storage.DocumentNotPrivate):
        store.attach_document(table, _identity(), PUBLIC_ID, storage_key=key,
                              sha256="b" * 64, content_type="application/pdf",
                              size_bytes=10, source_key=SOURCE_KEY,
                              public_source_retained=True)
    assert _doc_rows(table) == []


def test_b_a_malformed_digest_writes_no_row():
    """A ``DOC#`` key with a junk digest could never be converged on by a replay, so the
    resolve-before-generate property would be silently lost rather than loudly broken."""
    table = _seeded_table()
    for bad in ("", "abc", "g" * 64, "a" * 63, "a" * 65, "a" * 32 + "-" * 32):
        with pytest.raises(dropdocs_storage.DocumentNotPrivate):
            store.attach_document(
                table, _identity(), PUBLIC_ID,
                storage_key="secure/u/dropdocs/wecare-digital-x.pdf", sha256=bad,
                content_type="application/pdf", size_bytes=10, source_key=SOURCE_KEY,
                public_source_retained=True)
    assert _doc_rows(table) == []


def test_b_an_uppercase_digest_is_normalised_rather_than_refused():
    """One canonical spelling, so the same bytes cannot produce two ``DOC#`` keys. Refusing
    would be the wrong fail-closed: it would turn a cosmetic difference into a lost replay."""
    table = _seeded_table()
    gated = f"secure/u/dropdocs/wecare-digital-{'d' * 64}.pdf"
    store.attach_document(table, _identity(), PUBLIC_ID, storage_key=gated,
                          sha256="D" * 64, content_type="application/pdf", size_bytes=10,
                          source_key=SOURCE_KEY, public_source_retained=True)
    assert _doc_rows(table) == [f"{store.DOC_PREFIX}{REQUEST_INTERNAL}#{'d' * 64}"]


def test_b_a_wrong_kind_or_foreign_request_gets_one_identical_refusal():
    """Not an existence oracle: "not yours", "not Drop Docs" and "no such id" are one answer."""
    gated = f"secure/u/dropdocs/wecare-digital-{'c' * 64}.pdf"
    kwargs = dict(storage_key=gated, sha256="c" * 64, content_type="application/pdf",
                  size_bytes=10, source_key=SOURCE_KEY, public_source_retained=True)

    amendment = _seeded_table(kind=SUBMIT_REQUEST)
    with pytest.raises(customer_auth.CustomerNotAuthorized):
        store.attach_document(amendment, _identity(), PUBLIC_ID, **kwargs)
    assert _doc_rows(amendment) == []

    foreign = _seeded_table(owner=STRANGER)
    with pytest.raises(customer_auth.CustomerNotAuthorized):
        store.attach_document(foreign, _identity(), PUBLIC_ID, **kwargs)
    assert _doc_rows(foreign) == []

    absent = _seeded_table()
    with pytest.raises(customer_auth.CustomerNotAuthorized):
        store.attach_document(absent, _identity(), "WD-REQ-ZZZZZZZZ", **kwargs)
    assert _doc_rows(absent) == []


# ── (c) a failed copy is a 503 and no row ─────────────────────────────────────

def test_c_a_copy_failure_answers_503_and_writes_no_row(handler, monkeypatch):
    s3 = FakeS3()
    s3.fail_on["copy_object"] = FakeS3Error("AccessDenied")
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table)

    response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 503
    assert json.loads(response["body"])["error"] == "DOCUMENT_NOT_STORED"
    assert _doc_rows(table) == []
    assert "delete_object" not in s3.calls


def test_c_a_missing_destination_after_a_successful_copy_also_writes_no_row(handler,
                                                                           monkeypatch):
    """The HEAD is not ceremony. A copy that reports success while the object is not
    readable would otherwise mint a row pointing at nothing, while the PUBLIC original is
    still being served."""
    s3 = FakeS3()
    s3.fail_on["head_object"] = FakeS3Error("NotFound")
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table)

    response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 503
    assert _doc_rows(table) == []


def test_c_a_missing_source_writes_no_row(handler, monkeypatch):
    s3 = FakeS3()
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table)

    response = handler.handler(_attach_event(sourceKey="o/stack/whatsapp-media/incoming/no.pdf"),
                               None)

    assert response["statusCode"] == 503
    assert _doc_rows(table) == []
    assert set(s3.calls) == {"get_object"}


def test_c_the_route_refuses_while_the_flag_is_unset(handler, monkeypatch):
    s3 = FakeS3()
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table, enabled=False)

    response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 503
    assert json.loads(response["body"])["error"] == "DROPDOCS_ATTACH_DISABLED"
    # nothing was read, nothing was written, nothing was asked of S3
    assert s3.calls == []
    assert _doc_rows(table) == []


def test_c_the_flag_is_read_per_call_not_captured_at_import(handler, monkeypatch):
    """A switch that needs every warm sandbox to recycle is not much of a switch."""
    assert handler._dropdocs_attach_enabled() is False
    monkeypatch.setenv("DROPDOCS_ATTACH_ENABLED", "true")
    assert handler._dropdocs_attach_enabled() is True
    monkeypatch.setenv("DROPDOCS_ATTACH_ENABLED", "off")
    assert handler._dropdocs_attach_enabled() is False


def test_c_the_route_needs_a_customer_pool_token(handler, monkeypatch):
    """`_customer_identity`, never `require_auth`: that one is hardcoded to the ADMIN pool,
    so a customer token would pass `get_user` and fall through to role Viewer."""
    s3 = FakeS3()
    table = _seeded_table()
    monkeypatch.setenv("DROPDOCS_ATTACH_ENABLED", "true")
    monkeypatch.setattr(handler, "_customer_identity", lambda _event: None)
    monkeypatch.setattr(handler, "_s3_client", lambda: s3)
    monkeypatch.setattr(handler, "_table", lambda _name: table)

    response = handler.handler(_attach_event(), None)
    assert response["statusCode"] == 401
    assert s3.calls == []
    assert _doc_rows(table) == []

    source = (FUNC_DIR / "handler.py").read_text(encoding="utf-8")
    arm = source.split('if tail == ["dropdocs", "attach"]:', 1)[1].split("\n        if ", 1)[0]
    assert "_customer_identity(event)" in arm
    assert "require_auth" not in arm


def test_c_a_token_without_a_sub_authorises_nothing(handler, monkeypatch):
    """The `sub` IS the owner key every REQ# row is filed under. No sub, no authority."""
    s3 = FakeS3()
    table = _seeded_table()
    monkeypatch.setenv("DROPDOCS_ATTACH_ENABLED", "true")
    monkeypatch.setattr(handler, "_customer_identity",
                        lambda _event: {"username": "+918100640044",
                                        "phone": "918100640044", "subject": ""})
    monkeypatch.setattr(handler, "_s3_client", lambda: s3)
    monkeypatch.setattr(handler, "_table", lambda _name: table)

    response = handler.handler(_attach_event(), None)
    assert response["statusCode"] == 401
    assert s3.calls == []
    assert _doc_rows(table) == []


# ── (d) the same bytes twice is one document ──────────────────────────────────

def test_d_attaching_the_same_bytes_twice_yields_one_row_and_one_key(handler, monkeypatch):
    s3 = FakeS3()
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table)

    first = handler.handler(_attach_event(), None)
    second = handler.handler(_attach_event(), None)

    assert first["statusCode"] == 201
    assert second["statusCode"] == 201
    one = json.loads(first["body"])["document"]
    two = json.loads(second["body"])["document"]
    assert one["storageKey"] == two["storageKey"]
    assert one["documentId"] == two["documentId"]
    assert len(_doc_rows(table)) == 1
    # and the request's index of its documents did not double up either
    assert table.rows[REQUEST_INTERNAL]["documentSha256s"] == [one["documentId"]]
    assert store.list_documents(table, _identity(), PUBLIC_ID) == [one]


def test_d_a_different_document_is_a_second_row(handler, monkeypatch):
    """The convergence in (d) must be on the CONTENT, not on the request."""
    table = _seeded_table()
    s3 = FakeS3()
    _wire(handler, monkeypatch, s3, table)
    assert handler.handler(_attach_event(), None)["statusCode"] == 201

    other = "o/stack/whatsapp-media/incoming/wecare-digital-cd34.pdf"
    s3.objects[other] = {"body": b"a different licence entirely",
                         "contentType": "application/pdf"}
    assert handler.handler(_attach_event(sourceKey=other), None)["statusCode"] == 201

    assert len(_doc_rows(table)) == 2
    assert len(store.list_documents(table, _identity(), PUBLIC_ID)) == 2


def test_d_a_rename_is_not_a_new_document(handler, monkeypatch):
    """Re-exporting from a phone with different filenames is the common case."""
    table = _seeded_table()
    s3 = FakeS3()
    renamed = "o/stack/whatsapp-media/incoming/wecare-digital-zz99.pdf"
    s3.objects[renamed] = {"body": DOCUMENT_BYTES, "contentType": "application/pdf"}
    _wire(handler, monkeypatch, s3, table)

    assert handler.handler(_attach_event(), None)["statusCode"] == 201
    assert handler.handler(_attach_event(sourceKey=renamed), None)["statusCode"] == 201
    assert len(_doc_rows(table)) == 1


def test_d_another_customer_sees_none_of_it(handler, monkeypatch):
    table = _seeded_table()
    _wire(handler, monkeypatch, FakeS3(), table)
    assert handler.handler(_attach_event(), None)["statusCode"] == 201

    with pytest.raises(customer_auth.CustomerNotAuthorized):
        store.list_documents(table, _identity(STRANGER), PUBLIC_ID)


# ── (e) no key under o/ escapes, except in the one alert ──────────────────────

def test_e_no_public_key_appears_in_the_response(handler, monkeypatch):
    table = _seeded_table()
    _wire(handler, monkeypatch, FakeS3(), table)

    response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 201
    assert "o/" not in response["body"]
    assert SOURCE_KEY not in response["body"]
    assert "whatsapp-media" not in response["body"]
    assert media_paths.is_gated(json.loads(response["body"])["document"]["storageKey"])
    # and the response is not cacheable
    assert response["headers"]["Cache-Control"] == "no-store"


def test_e_the_public_source_is_stored_as_provenance_but_never_handed_out(handler,
                                                                         monkeypatch):
    """A deliberate asymmetry, so it is recorded rather than discovered.

    The ROW keeps ``sourceKey`` - it is how an operator traces where a document came from,
    and the row is backend-only. The VIEW does not, because handing a key under ``o/`` to a
    browser would publish the very URL the promotion exists to make irrelevant.
    """
    table = _seeded_table()
    _wire(handler, monkeypatch, FakeS3(), table)
    handler.handler(_attach_event(), None)

    row = table.rows[_doc_rows(table)[0]]
    assert row["sourceKey"] == SOURCE_KEY
    assert row["publicSourceRetained"] is True
    assert media_paths.is_gated(row["storageKey"])

    view = store.list_documents(table, _identity(), PUBLIC_ID)[0]
    assert "sourceKey" not in view
    assert not any("o/" in str(value) for value in view.values())


def test_e_exactly_one_log_line_carries_the_retained_public_key(caplog):
    """The retention is reported, once, under a searchable alert - and nowhere else.

    Silence would be the worse outcome: the public original survives until the
    ``s3_whatsapp_media_incoming`` TTL expires it, because no role holds
    ``s3:DeleteObject``.
    """
    import logging

    caplog.set_level(logging.INFO, logger=dropdocs_storage.logger.name)
    dropdocs_storage.promote_to_secure(FakeS3(), bucket=BUCKET, source_key=SOURCE_KEY)

    carrying = [record for record in caplog.records if SOURCE_KEY in record.getMessage()]
    assert len(carrying) == 1
    only = carrying[0]
    assert only.levelno == logging.WARNING
    payload = json.loads(only.getMessage())
    assert payload["alert"] == "DROPDOCS_PUBLIC_SOURCE_RETAINED"
    assert payload["publicSourceKey"] == SOURCE_KEY
    assert media_paths.is_gated(payload["storageKey"])
    # every OTHER line this path emits is free of the public key
    others = [r for r in caplog.records if r is not only]
    assert others and not any("o/" in r.getMessage() for r in others)


def test_e_no_log_line_from_the_attach_route_carries_a_public_key(handler, monkeypatch,
                                                                 caplog):
    import logging

    table = _seeded_table()
    _wire(handler, monkeypatch, FakeS3(), table)
    caplog.set_level(logging.INFO, logger=store.logger.name)
    caplog.set_level(logging.INFO, logger=handler.logger.name)

    handler.handler(_attach_event(), None)

    from_route = [r for r in caplog.records
                  if r.name in (store.logger.name, handler.logger.name)]
    assert from_route
    for record in from_route:
        assert "o/" not in record.getMessage(), record.getMessage()


def test_e_no_phone_number_is_logged_by_this_path(handler, monkeypatch, caplog):
    import logging

    table = _seeded_table()
    _wire(handler, monkeypatch, FakeS3(), table)
    caplog.set_level(logging.INFO)

    handler.handler(_attach_event(), None)

    for record in caplog.records:
        message = record.getMessage()
        assert "918100640044" not in message
        assert "8100640044" not in message


# ── (f) the absences, asserted on the AST ─────────────────────────────────────

NEW_SOURCES = {
    "dropdocs_storage.py": STORAGE_MODULE,
    "service_request_store.py": SHARED / "lambda_utils" / "ecommerce"
    / "service_request_store.py",
    "secure-files/handler.py": FUNC_DIR / "handler.py",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("label", sorted(NEW_SOURCES))
def test_f_nothing_on_this_path_can_delete_an_object(label):
    """Asserted on the AST, not the text, because the comments explaining why there is no
    delete necessarily contain the word. No role in this account holds ``s3:DeleteObject``,
    so a call here would fail at runtime - but it would fail AFTER the row was written."""
    offenders = [node.lineno for node in ast.walk(_tree(NEW_SOURCES[label]))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in ("delete_object", "delete_objects",
                                        "delete_item", "DeleteItem")]
    assert offenders == [], f"{label} deletes something at line(s) {offenders}"


def test_f_every_destination_key_is_composed_through_media_paths():
    """A hand-built ``secure/...`` literal is the defect `media_paths` exists to prevent: a
    key one level off its data still returned HTTP 200 on the apex host, so it errored
    nowhere, logged nothing and alarmed nothing for two days."""
    tree = _tree(STORAGE_MODULE)

    literals = [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert not [text for text in literals if text.startswith(("secure/", "o/", "/secure"))]

    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "secure"
             and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "media_paths"]
    assert len(calls) == 1, "the destination must be composed in exactly one place"


def test_f_the_new_locker_prefix_is_composed_through_media_paths(handler):
    source = (FUNC_DIR / "handler.py").read_text(encoding="utf-8")
    assert 'DROPDOCS_PREFIX = media_paths.secure("u/dropdocs/")' in source
    assert handler.DROPDOCS_PREFIX == "secure/u/dropdocs/"
    assert handler.DROPDOCS_PREFIX.startswith(handler.SECURE_PREFIX)
    assert media_paths.is_gated(handler.DROPDOCS_PREFIX)
    # the three pre-existing constants are untouched: their keys are already persisted
    assert handler.UPLOAD_PREFIX == "secure/u/"
    assert handler.DELIVER_PREFIX == "secure/d/"


def test_f_the_promotion_module_imports_no_money_mover_and_no_boto3():
    """Pure except for the injected client, which is what makes every case above offline."""
    names = set()
    for node in ast.walk(_tree(STORAGE_MODULE)):
        if isinstance(node, ast.ImportFrom):
            names.update(part for part in (node.module or "").split("."))
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
    assert not names & {"boto3", "botocore", "urllib", "requests", "razorpay_orders",
                        "razorpay_verify", "order_creation", "finalization"}
    literals = [node.value for node in ast.walk(_tree(STORAGE_MODULE))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert not any("secretsmanager" in text for text in literals)


def test_f_the_gate_is_ordered_ownership_then_kind_then_gatedness():
    """Source-level ordering, because the ordering IS the guarantee and a reviewer cannot
    see it from the signature. Gatedness is checked before anything is marshalled, so a
    non-gated key cannot reach a write under any interleaving."""
    source = (SHARED / "lambda_utils" / "ecommerce"
              / "service_request_store.py").read_text(encoding="utf-8")
    body = source.split("def attach_document", 1)[1].split("\ndef ", 1)[0]

    resolve = body.index("_resolve_dropdocs_request(")
    gated = body.index("media_paths.is_gated(storage_key)")
    write = body.index("_transact(table, items)")
    assert resolve < gated < write
