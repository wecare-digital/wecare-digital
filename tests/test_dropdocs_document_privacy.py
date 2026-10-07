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
from lambda_utils.ecommerce import document_errors, dropdocs_storage  # noqa: E402
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
        #: Let a HEAD lie about ``ContentLength``, so the size ceiling can be exercised
        #: without allocating a hundred megabytes in a test.
        self.declared_sizes: Dict[str, int] = {}
        #: Fail the HEAD of the DESTINATION only. There are now two HEADs on the promotion
        #: path - the source size check and the proving HEAD - so failing them by operation
        #: name alone could no longer distinguish which one a test meant.
        self.fail_on_destination_head: Any = None

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
            def read(self_inner, amt=None):
                # boto3's StreamingBody takes an optional byte count, and the promotion
                # passes one. Honouring it here is what lets case (g) prove the limit holds
                # even when a HEAD under-reports the object.
                return held["body"] if amt is None else held["body"][:amt]

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
        if media_paths.is_gated(Key) and self.fail_on_destination_head is not None:
            raise self.fail_on_destination_head
        held = self.objects.get(Key)
        if held is None:
            raise FakeS3Error("NotFound")
        return {"ContentLength": self.declared_sizes.get(Key, len(held["body"])),
                "ContentType": held["contentType"]}

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
    # TWO heads, and which is which matters: the first sizes the SOURCE before a byte
    # moves, the second proves the copy landed at the DESTINATION.
    head = [call for call in s3.call_log if call["operation"] == "head_object"]
    assert len(head) == 2
    assert head[0]["Key"] == SOURCE_KEY
    assert not media_paths.is_gated(head[0]["Key"])
    assert media_paths.is_gated(head[1]["Key"])
    copy = [call for call in s3.call_log if call["operation"] == "copy_object"][0]
    assert copy["MetadataDirective"] == "REPLACE"
    assert copy["ContentType"] == "application/pdf"  # preserved, not re-guessed
    assert copy["CopySource"] == {"Bucket": BUCKET, "Key": SOURCE_KEY}


def test_a_the_proving_head_comes_after_the_copy_not_before():
    """Ordering, not presence. HEADing before the copy proves nothing about the copy.

    The full order is: size the source, read it, copy it, prove the destination. The last
    ``head_object`` is the proving one, which is why the index is taken from the right.
    """
    s3 = FakeS3()
    dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=SOURCE_KEY)
    proving = len(s3.calls) - 1 - s3.calls[::-1].index("head_object")
    assert s3.calls.index("copy_object") < proving
    # the size check, by contrast, comes before anything is transferred
    assert s3.calls.index("head_object") < s3.calls.index("get_object")


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
    resolve-before-generate property would be silently lost rather than loudly broken.

    ``DocumentRejected``, not ``DocumentNotPrivate``: a malformed digest is a shape failure
    and will never succeed on retry, so the HTTP layer must answer 400 rather than a 503
    that invites one.
    """
    table = _seeded_table()
    for bad in ("", "abc", "g" * 64, "a" * 63, "a" * 65, "a" * 32 + "-" * 32):
        with pytest.raises(document_errors.DocumentRejected):
            store.attach_document(
                table, _identity(), PUBLIC_ID,
                storage_key="secure/u/dropdocs/wecare-digital-x.pdf", sha256=bad,
                content_type="application/pdf", size_bytes=10, source_key=SOURCE_KEY,
                public_source_retained=True)
    assert _doc_rows(table) == []


@pytest.mark.parametrize("size", [None, -1, "", "not a number"])
def test_b_a_missing_or_negative_byte_count_is_a_shape_refusal_not_a_privacy_one(size):
    """Same reasoning as the digest above, and the same 400. A privacy exception here would
    tell the caller to retry a request that can never succeed, and would also muddy the one
    alert that is supposed to mean "two checks disagreed about where an object lives"."""
    table = _seeded_table()
    with pytest.raises(document_errors.DocumentRejected):
        store.attach_document(
            table, _identity(), PUBLIC_ID,
            storage_key=f"secure/u/dropdocs/wecare-digital-{'e' * 64}.pdf",
            sha256="e" * 64, content_type="application/pdf", size_bytes=size,
            source_key=SOURCE_KEY, public_source_retained=True)
    assert _doc_rows(table) == []


def test_b_a_privacy_refusal_and_a_shape_refusal_are_different_exceptions():
    """Asserted directly, because the handler's 400-vs-503 split rests on it and an
    `except DocumentRejected` placed after `except DocumentNotPrivate` would silently
    collapse the two if one subclassed the other."""
    assert not issubclass(document_errors.DocumentRejected,
                          document_errors.DocumentNotPrivate)
    assert not issubclass(document_errors.DocumentNotPrivate,
                          document_errors.DocumentRejected)
    assert not issubclass(document_errors.DocumentLimitReached,
                          document_errors.DocumentRejected)
    # and the store and the storage module borrow the SAME classes, so an `except` written
    # against either spelling catches both
    assert store.DocumentNotPrivate is document_errors.DocumentNotPrivate
    assert dropdocs_storage.DocumentNotPrivate is document_errors.DocumentNotPrivate
    assert dropdocs_storage.DocumentRejected is document_errors.DocumentRejected


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
    # the DESTINATION head only: failing both would also fail the source size check, and
    # the 503 would then prove nothing about the proving HEAD.
    s3.fail_on_destination_head = FakeS3Error("NotFound")
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
    # the source size check is the first thing that touches S3, so a missing object is
    # refused before a single byte is transferred
    assert set(s3.calls) == {"head_object"}


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


# ── (g) the caller chooses the source, so the source is allow-listed ──────────
#
# `sourceKey` arrives in a request body. The role can read all of `secure/*` as well as the
# WhatsApp incoming prefix, so without a bound a customer could name another customer's
# locker upload and have it registered as their own - and for a source under `o/`, copied
# into the gated tree under their own ownership, which inverts the leak this phase exists to
# close. One prefix is accepted. Everything else is a 400.

OTHER_CUSTOMERS_UPLOAD = "secure/u/0199abcd-somebody-else/passport.pdf"


@pytest.mark.parametrize("key", [
    OTHER_CUSTOMERS_UPLOAD,                         # another customer's locker original
    "secure/d/0199abcd-somebody-else/rendition.pdf",  # ...and their deliverable rendition
    "secure/u/dropdocs/wecare-digital-deadbeef.pdf",  # another customer's promoted document
    "o/public/wa-tpl/approved-template.png",        # a public object outside the one prefix
    "o/blog-production/sources/pdf/abcd.pdf",
    "stack/whatsapp-media/x.pdf",                   # legacy-rooted, and still outside it
    "o/stack/whatsapp-media/x.pdf",                 # one level ABOVE the allowed prefix
    "o/stack/whatsapp-media/incoming-other/x.pdf",  # a sibling whose name shares the stem
    "https://wecare.digital/get/o/stack/whatsapp-media/incoming/x.pdf",
    "", None,
])
def test_g_only_a_whatsapp_arrival_may_be_promoted(key):
    """The allow-list, as an enumeration of what it excludes."""
    s3 = FakeS3()
    s3.objects[OTHER_CUSTOMERS_UPLOAD] = {"body": b"someone else's passport",
                                          "contentType": "application/pdf"}
    with pytest.raises(document_errors.DocumentRejected):
        dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=key)
    # refused before S3 is touched at all, so it is not an existence oracle either
    assert s3.calls == []


def test_g_the_check_runs_on_the_canonical_key_not_the_raw_input():
    """Both directions of the same property, which is why it is a test of its own.

    A legacy-rooted spelling of an ALLOWED key (``stack/whatsapp-media/incoming/...``, no
    ``o/`` - the shape `media_paths.canonical` exists to normalise) names exactly the object
    the prefix permits, so it must be accepted. And the matching legacy spelling of a
    DISALLOWED key must not slip through by dropping the root, which the parametrize above
    covers. Checking the raw input instead would get one of these two wrong whichever way it
    was written.
    """
    legacy = "stack/whatsapp-media/incoming/wecare-digital-ab12.pdf"
    assert media_paths.canonical(legacy) == SOURCE_KEY
    s3 = FakeS3()
    result = dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=legacy)
    assert result["promoted"] is True
    assert media_paths.is_gated(result["storageKey"])


def test_g_the_allowed_prefix_is_composed_not_written_out():
    """It must stay equal to the key `inbound-whatsapp-handler` writes and to the single
    ``s3:GetObject`` resource the role is granted. Three copies of a literal drift."""
    assert dropdocs_storage.WHATSAPP_INCOMING_PREFIX == media_paths.public(
        "stack/whatsapp-media", "incoming/")
    assert dropdocs_storage.WHATSAPP_INCOMING_PREFIX == "o/stack/whatsapp-media/incoming/"
    assert not media_paths.is_gated(dropdocs_storage.WHATSAPP_INCOMING_PREFIX)


def test_g_an_already_gated_source_is_refused_over_http_and_writes_no_row(handler,
                                                                         monkeypatch):
    """The one that mattered. A gated key names SOMEBODY's private upload and this route
    cannot tell whose, so accepting it made the 201 body an existence oracle for the private
    tree - key, content type and exact byte count. A browser upload reached ``secure/u/``
    through the locker's own presigned PUT and already has a locker row, so it never needed
    this route."""
    s3 = FakeS3()
    s3.objects[OTHER_CUSTOMERS_UPLOAD] = {"body": b"someone else's passport",
                                          "contentType": "application/pdf"}
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table)

    response = handler.handler(_attach_event(sourceKey=OTHER_CUSTOMERS_UPLOAD), None)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"] == "DOCUMENT_SOURCE_REFUSED"
    assert _doc_rows(table) == []
    assert s3.calls == []
    # the refusal names neither the key it was given nor the prefix it would have accepted
    assert OTHER_CUSTOMERS_UPLOAD not in response["body"]
    assert "whatsapp-media" not in response["body"]
    assert "secure/" not in response["body"]


def test_g_a_public_object_outside_the_prefix_is_not_copied_into_the_gated_tree(handler,
                                                                               monkeypatch):
    """The worse half of the same hole: a key under ``o/`` is unlisted-but-public with the
    URL as the secret, so a leaked URL must not be convertible into a durable private
    document owned by whoever found it."""
    s3 = FakeS3()
    leaked = "o/public/wa-tpl/someone-elses-document.pdf"
    s3.objects[leaked] = {"body": b"a leaked public document",
                          "contentType": "application/pdf"}
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table)

    response = handler.handler(_attach_event(sourceKey=leaked), None)

    assert response["statusCode"] == 400
    assert _doc_rows(table) == []
    assert "copy_object" not in s3.calls
    assert s3.calls == []


def test_g_a_refused_source_is_logged_by_type_only(handler, monkeypatch, caplog):
    import logging

    s3 = FakeS3()
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table)
    caplog.set_level(logging.INFO)

    handler.handler(_attach_event(sourceKey=OTHER_CUSTOMERS_UPLOAD), None)

    for record in caplog.records:
        message = record.getMessage()
        assert OTHER_CUSTOMERS_UPLOAD not in message
        assert "passport" not in message


# ── (g2) the read is bounded ──────────────────────────────────────────────────

def test_g_the_ceiling_is_the_same_one_the_locker_already_applies(handler):
    """Two numbers that must agree, in two files. Pinned, because they do not stay equal on
    their own - and the attach path not consulting the locker's own limit is how a 512 MB
    function ends up hashing an arbitrarily large object in memory."""
    assert dropdocs_storage.MAX_DOCUMENT_BYTES == handler.MAX_DOCUMENT_BYTES
    assert dropdocs_storage.MAX_DOCUMENT_BYTES == 100 * 1024 * 1024


def test_g_an_oversized_source_is_refused_before_a_byte_is_transferred():
    """The HEAD is what makes this cheap: an oversized object costs one call and no
    transfer, rather than an OOM or a timeout surfacing as a 502 nobody can read."""
    s3 = FakeS3()
    s3.declared_sizes[SOURCE_KEY] = dropdocs_storage.MAX_DOCUMENT_BYTES + 1

    with pytest.raises(document_errors.DocumentRejected):
        dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=SOURCE_KEY)

    assert s3.calls == ["head_object"]
    assert "get_object" not in s3.calls
    assert "copy_object" not in s3.calls


def test_g_an_object_at_exactly_the_ceiling_is_accepted():
    """A ceiling that refuses its own boundary value is an off-by-one, not a policy."""
    s3 = FakeS3()
    s3.declared_sizes[SOURCE_KEY] = dropdocs_storage.MAX_DOCUMENT_BYTES
    result = dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=SOURCE_KEY)
    assert result["promoted"] is True


def test_g_a_head_that_under_reports_the_object_still_cannot_blow_the_limit(monkeypatch):
    """The body read is bounded explicitly rather than trusted from the HEAD, because the
    limit has to hold even when the two disagree."""
    monkeypatch.setattr(dropdocs_storage, "MAX_DOCUMENT_BYTES", 8)
    s3 = FakeS3()
    s3.declared_sizes[SOURCE_KEY] = 1  # a HEAD claiming the object is tiny

    with pytest.raises(document_errors.DocumentRejected):
        dropdocs_storage.promote_to_secure(s3, bucket=BUCKET, source_key=SOURCE_KEY)

    assert "copy_object" not in s3.calls


def test_g_an_oversized_source_answers_400_and_writes_no_row(handler, monkeypatch):
    s3 = FakeS3()
    s3.declared_sizes[SOURCE_KEY] = dropdocs_storage.MAX_DOCUMENT_BYTES + 1
    table = _seeded_table()
    _wire(handler, monkeypatch, s3, table)

    response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "DOCUMENT_SOURCE_REFUSED"
    assert _doc_rows(table) == []


# ── (g3) the digest index has a stated ceiling ────────────────────────────────

def test_g_a_request_may_not_hold_unbounded_documents():
    """``documentSha256s`` is an attribute on the REQ# row, so there IS a hard ceiling
    whether or not we choose one: the 400 KB item limit arrives near five thousand digests
    and turns every further attach into an unreadable validation error. A stated cap turns
    that into a refusal a caller can read."""
    table = _seeded_table()
    table.rows[REQUEST_INTERNAL]["documentSha256s"] = [
        f"{index:064x}" for index in range(store.MAX_DOCUMENTS_PER_REQUEST)]

    with pytest.raises(document_errors.DocumentLimitReached):
        store.attach_document(
            table, _identity(), PUBLIC_ID,
            storage_key=f"secure/u/dropdocs/wecare-digital-{'f' * 64}.pdf",
            sha256="f" * 64, content_type="application/pdf", size_bytes=10,
            source_key=SOURCE_KEY, public_source_retained=True)
    assert _doc_rows(table) == []


def test_g_a_replay_still_succeeds_at_the_ceiling():
    """Idempotency must survive the cap. Refusing a digest the request already holds would
    turn a harmless retry into a failure the caller cannot resolve."""
    table = _seeded_table()
    held = [f"{index:064x}" for index in range(store.MAX_DOCUMENTS_PER_REQUEST - 1)]
    digest = "a" * 64
    table.rows[REQUEST_INTERNAL]["documentSha256s"] = held + [digest]
    gated = f"secure/u/dropdocs/wecare-digital-{digest}.pdf"
    table.seed({"requestId": f"{store.DOC_PREFIX}{REQUEST_INTERNAL}#{digest}",
                "ownerCustomerId": OWNER, "targetRequestId": REQUEST_INTERNAL,
                "storageKey": gated, "sha256": digest, "contentType": "application/pdf",
                "sizeBytes": 10, "sourceKey": SOURCE_KEY, "publicSourceRetained": True,
                "attachedAt": 1})

    view = store.attach_document(table, _identity(), PUBLIC_ID, storage_key=gated,
                                 sha256=digest, content_type="application/pdf",
                                 size_bytes=10, source_key=SOURCE_KEY,
                                 public_source_retained=True)

    assert view["documentId"] == digest
    assert len(_doc_rows(table)) == 1


def test_g_the_cap_answers_409_rather_than_a_validation_error(handler, monkeypatch):
    s3 = FakeS3()
    table = _seeded_table()
    table.rows[REQUEST_INTERNAL]["documentSha256s"] = [
        f"{index:064x}" for index in range(store.MAX_DOCUMENTS_PER_REQUEST)]
    _wire(handler, monkeypatch, s3, table)

    response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 409
    body = json.loads(response["body"])
    assert body["error"] == "DOCUMENT_LIMIT_REACHED"
    assert body["limit"] == store.MAX_DOCUMENTS_PER_REQUEST
    assert _doc_rows(table) == []


def test_g_the_list_read_is_bounded_by_the_same_cap():
    """A row that overshot the cap in a concurrent burst must still read back at a bounded
    cost - `list_documents` issues one GetItem per digest, deliberately not a Query."""
    table = _seeded_table()
    table.rows[REQUEST_INTERNAL]["documentSha256s"] = [
        f"{index:064x}" for index in range(store.MAX_DOCUMENTS_PER_REQUEST + 50)]
    reads: List[str] = []
    original = table.get_item

    def _counting(**kwargs):
        reads.append(str((kwargs.get("Key") or {}).get("requestId")))
        return original(**kwargs)

    table.get_item = _counting
    store.list_documents(table, _identity(), PUBLIC_ID)
    # one resolve of the REQ# row, one of the REQNO# pointer, then at most the cap
    assert len([key for key in reads if key.startswith(store.DOC_PREFIX)]) == \
        store.MAX_DOCUMENTS_PER_REQUEST


# ── (g4) the read route exists, so list_documents has a caller ────────────────

def _list_event(request_id: str = PUBLIC_ID) -> Dict[str, Any]:
    return {"requestContext": {
                "http": {"method": "GET",
                         "path": f"/secure-files/dropdocs/{request_id}/documents"},
                "stage": "$default"},
            "headers": {"authorization": "Bearer t", "origin": "https://wecare.digital"}}


def test_g_the_list_route_returns_the_callers_own_documents(handler, monkeypatch):
    table = _seeded_table()
    _wire(handler, monkeypatch, FakeS3(), table)
    assert handler.handler(_attach_event(), None)["statusCode"] == 201

    response = handler.handler(_list_event(), None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["requestId"] == PUBLIC_ID
    assert len(body["documents"]) == 1
    assert media_paths.is_gated(body["documents"][0]["storageKey"])
    # same privacy properties as the write: no public key, nothing cacheable
    assert "o/" not in response["body"]
    assert "sourceKey" not in response["body"]
    assert response["headers"]["Cache-Control"] == "no-store"


def test_g_the_list_route_is_not_an_existence_oracle(handler, monkeypatch):
    """One identical refusal for "no such request", "not yours" and "not Drop Docs" - the
    same property the attach route is careful about. A list route that leaked the
    distinction would re-open it."""
    _wire(handler, monkeypatch, FakeS3(), _seeded_table())
    unknown = handler.handler(_list_event("WD-REQ-ZZZZZZZZ"), None)

    _wire(handler, monkeypatch, FakeS3(), _seeded_table(owner=STRANGER))
    foreign = handler.handler(_list_event(), None)

    _wire(handler, monkeypatch, FakeS3(), _seeded_table(kind=SUBMIT_REQUEST))
    wrong_kind = handler.handler(_list_event(), None)

    for response in (unknown, foreign, wrong_kind):
        assert response["statusCode"] == 403
        assert json.loads(response["body"])["error"] == "NOT_REGISTERED"
    assert unknown["body"] == foreign["body"] == wrong_kind["body"]


def test_g_the_list_route_is_behind_the_same_flag(handler, monkeypatch):
    """The pair switches on together. A readable list of a customer's documents while the
    write is off would be new surface nobody decided to expose."""
    table = _seeded_table()
    _wire(handler, monkeypatch, FakeS3(), table, enabled=False)

    response = handler.handler(_list_event(), None)

    assert response["statusCode"] == 503
    assert json.loads(response["body"])["error"] == "DROPDOCS_ATTACH_DISABLED"


def test_g_the_list_route_needs_a_customer_pool_token(handler, monkeypatch):
    monkeypatch.setenv("DROPDOCS_ATTACH_ENABLED", "true")
    monkeypatch.setattr(handler, "_customer_identity", lambda _event: None)
    monkeypatch.setattr(handler, "_table", lambda _name: _seeded_table())

    assert handler.handler(_list_event(), None)["statusCode"] == 401

    source = (FUNC_DIR / "handler.py").read_text(encoding="utf-8")
    arm = source.split('tail[2] == "documents"', 1)[1].split("\n        if ", 1)[0]
    assert "_customer_identity(event)" in arm
    assert "require_auth" not in arm


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_g_the_list_route_is_read_only(handler, monkeypatch, method):
    table = _seeded_table()
    _wire(handler, monkeypatch, FakeS3(), table)
    event = _list_event()
    event["requestContext"]["http"]["method"] = method

    response = handler.handler(event, None)

    assert response["statusCode"] == 405
    assert _doc_rows(table) == []


def test_g_both_dropdocs_routes_are_registered_for_provisioning():
    """The route has to exist in the provisioner or the handler arm is unreachable, which is
    a failure mode no unit test would catch."""
    source = (ROOT / "scripts" / "provision_secure_files_api.py").read_text(encoding="utf-8")
    assert '("POST", "/secure-files/dropdocs/attach")' in source
    assert '("GET", "/secure-files/dropdocs/{requestId}/documents")' in source


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
