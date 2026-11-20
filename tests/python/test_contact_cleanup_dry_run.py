"""Tests for scripts/contact_cleanup_dry_run.py using in-memory fake DynamoDB tables.

All identifiers below are synthetic. No real phone, contact id or name is used.
"""
import importlib.util
import json
import os
import re

import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "contact_cleanup_dry_run.py")
_spec = importlib.util.spec_from_file_location("contact_cleanup_dry_run", _SCRIPT)
dry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dry)

NOW = 1_800_000_000
DAY = 86400


class FakeTable:
    """Paginating, read-only fake. Any write call raises, as does a configured failure."""

    def __init__(self, items=None, page_size=2, fail=None, indexes=None):
        self.items = list(items or [])
        self.page_size = page_size
        self.fail = fail
        self.calls = []

    def _maybe_fail(self, op):
        self.calls.append(op)
        if self.fail:
            raise RuntimeError("boom")

    def scan(self, **kwargs):
        self._maybe_fail("scan")
        start = int((kwargs.get("ExclusiveStartKey") or {}).get("i", 0))
        page = self.items[start:start + self.page_size]
        out = {"Items": page}
        if start + self.page_size < len(self.items):
            out["LastEvaluatedKey"] = {"i": start + self.page_size}
        return out

    def query(self, **kwargs):
        self._maybe_fail("query")
        attr = kwargs["KeyConditionExpression"].split("=")[0].strip()
        value = list(kwargs["ExpressionAttributeValues"].values())[0]
        return {"Items": [i for i in self.items if i.get(attr) == value]}

    def get_item(self, **kwargs):
        self._maybe_fail("get_item")
        return {}

    def put_item(self, **kw):
        raise AssertionError("write attempted: put_item")

    update_item = delete_item = batch_write_item = put_item


class FakeTTL:
    def __init__(self, states=None, fail=False):
        self.states = states or {}
        self.fail = fail
        self.calls = []

    def describe_time_to_live(self, TableName):
        self.calls.append(TableName)
        if self.fail:
            raise RuntimeError("nope")
        if self.states.get(TableName):
            return {"TimeToLiveDescription": {"TimeToLiveStatus": "ENABLED", "AttributeName": "expiresAt"}}
        return {"TimeToLiveDescription": {"TimeToLiveStatus": "DISABLED"}}


def contact(cid, phone, **extra):
    row = {"id": cid, "contactId": cid, "phone": phone, "name": "Same Name"}
    row.update(extra)
    return row


def msg(mid, cid, content="hello there", **extra):
    row = {"id": mid, "contactId": cid, "content": content}
    row.update(extra)
    return row


def make_tables(contacts, messages=None, inbound=None, outbound=None, payments=None, attempts=None,
                invoices=None, orders=None, **fails):
    t = {
        "contacts": FakeTable(contacts),
        "messages": FakeTable(messages),
        "inbound": FakeTable(inbound),
        "outbound": FakeTable(outbound),
        "payments": FakeTable(payments),
        "attempts": FakeTable(attempts),
        "invoices": FakeTable(invoices),
        "orders": FakeTable(orders),
    }
    for name, flag in fails.items():
        t[name].fail = flag
    return t


NAMES = dry.table_names_from(dry.build_parser().parse_args([]))


def run(tables, selection, **kw):
    return dry.classify(tables, selection, now=NOW, table_names=NAMES, **kw)


def by_cid(report):
    return {c["contactId"]: c for c in report["contacts"]}


def base_contacts():
    return [
        contact("k1", "+15550000001"),
        contact("k2", "+15550000002"),
        contact("u1", "+15550000011"),
        contact("u2", "+15550000012"),
    ]


def test_same_name_contacts_stay_distinct_only_selected_kept():
    rep = run(make_tables(base_contacts()), dry.Selection(contact_ids=["k1"]))
    c = by_cid(rep)
    assert c["k1"]["classification"] == dry.OPERATOR_HOLD
    assert c["k2"]["classification"] == dry.ELIGIBLE
    assert c["u1"]["classification"] == dry.ELIGIBLE


def test_name_is_not_a_selector():
    with pytest.raises(ValueError):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"names": ["Same Name"]}, fh)
        try:
            dry.load_selection_file(fh.name)
        finally:
            os.unlink(fh.name)
    assert not hasattr(dry.Selection(), "names")
    # A selection with only a phone that matches nothing keeps nothing and blocks.
    rep = run(make_tables(base_contacts()), dry.Selection(phones=["+19990000000"]))
    assert rep["status"] == "BLOCKED_SELECTION_MISMATCH"
    assert rep["eligible"] == []


def test_match_by_id_phone_bsuid():
    rows = [contact("a", "+15551110001"), contact("b", "+15551110002", bsuid="BS.1"),
            contact("c", "+15551110003"), contact("d", "+15551110004")]
    rep = run(make_tables(rows), dry.Selection(contact_ids=["a"], phones=["+1 555-111-0003"],
                                                bsuids=["BS.1"]))
    c = by_cid(rep)
    assert [c[x]["classification"] for x in "abc"] == [dry.OPERATOR_HOLD] * 3
    assert c["d"]["classification"] == dry.ELIGIBLE
    assert rep["status"] == "OK"


def test_match_by_merge_link_both_directions():
    rows = [contact("t", "+15552220001", mergedContactIds=["s1"]),
            contact("s1", "", bsuid="B1", mergedIntoContactId="t", mergeState="merged"),
            contact("s2", "", bsuid="B2", mergedIntoContactId="t", mergeState="merged"),
            contact("other", "+15552220009")]
    rep = run(make_tables(rows), dry.Selection(contact_ids=["t"]))
    c = by_cid(rep)
    assert c["s1"]["classification"] == dry.OPERATOR_HOLD
    assert c["s2"]["classification"] == dry.OPERATOR_HOLD
    assert c["other"]["classification"] == dry.ELIGIBLE


def test_unselected_merged_contact_needs_review():
    rows = [contact("t", "+15553330001"), contact("x", "+15553330002", mergedIntoContactId="zzz")]
    c = by_cid(run(make_tables(rows), dry.Selection(contact_ids=["t"])))
    assert c["x"]["classification"] == dry.REVIEW_REQUIRED


def test_ambiguous_phone_selector_blocks_everything():
    rows = [contact("a", "+15554440001"), contact("b", "+15554440001"), contact("c", "+15554440002")]
    rep = run(make_tables(rows), dry.Selection(phones=["+15554440001"]))
    assert rep["status"] == "BLOCKED_SELECTION_MISMATCH"
    assert rep["eligible"] == []
    assert by_cid(rep)["c"]["classification"] == dry.REVIEW_REQUIRED


def test_expectation_mismatch_marks_nothing_eligible_and_exits_nonzero(tmp_path):
    contacts = base_contacts()
    msgs = [msg(f"m{i}", "k1") for i in range(3)]
    tables = make_tables(contacts, messages=msgs)
    rep = run(tables, dry.Selection(contact_ids=["k1"]), expect_keep_contacts=2,
              expect_keep_messages=22)
    assert rep["status"] == "BLOCKED_SELECTION_MISMATCH"
    assert rep["eligible"] == []
    assert not any(c["classification"] == dry.ELIGIBLE for c in rep["contacts"])
    assert any("expected 2 kept contacts" in p for p in rep["problems"])
    assert any("expected 22 kept messages" in p for p in rep["problems"])

    code = dry.main(["--keep-contact-id", "k1", "--expect-keep-contacts", "2"],
                    backend=lambda region: (lambda name: tables[_logical(name)], None))
    assert code == 3


def test_expectation_met_is_ok():
    contacts = base_contacts()
    msgs = [msg(f"m{i}", "k1") for i in range(2)] + [msg(f"n{i}", "k2") for i in range(3)]
    rep = run(make_tables(contacts, messages=msgs), dry.Selection(contact_ids=["k1", "k2"]),
              expect_keep_contacts=2, expect_keep_messages=5)
    assert rep["status"] == "OK"
    assert rep["totals"]["keptSelectedMessages"] == 5
    assert {e["contactId"] for e in rep["eligible"]} == {"u1", "u2"}


def _logical(name):
    for logical, full in NAMES.items():
        if full == name:
            return logical
    raise KeyError(name)


def test_razorpay_payment_linked_contact_retained_via_invoice_and_payment_tables():
    invoices = [{"invoiceId": "i1", "contactId": "u1", "paymentStatus": "captured"}]
    payments = [{"id": "p1", "paymentId": "pay_ABC12345", "contact": "+15550000012"}]
    c = by_cid(run(make_tables(base_contacts(), invoices=invoices, payments=payments),
                   dry.Selection(contact_ids=["k1"])))
    assert c["u1"]["classification"] == dry.FINANCIAL_RETENTION
    assert c["u2"]["classification"] == dry.FINANCIAL_RETENTION
    assert c["k2"]["classification"] == dry.ELIGIBLE


def test_attempt_and_order_linkage():
    rows = [contact("k1", "+15550000001"),
            contact("o1", "+15550000021", checkoutCustomerId="CUS_1"),
            contact("o2", "+15550000022"),
            contact("o3", "+15550000023", customerUuid="CUS_9")]
    orders = [{"orderId": "O1", "customerId": "CUS_1"}, {"orderId": "O2", "customerPhone": "+15550000022"}]
    attempts = [{"paymentAttemptId": "a1", "customerId": "CUS_9", "referenceId": "r1"}]
    c = by_cid(run(make_tables(rows, orders=orders, attempts=attempts),
                   dry.Selection(contact_ids=["k1"])))
    for cid in ("o1", "o2", "o3"):
        assert c[cid]["classification"] == dry.FINANCIAL_RETENTION


def test_payment_message_under_unrelated_contact_is_retained():
    msgs = [msg("m1", "u1", content="hi"),
            msg("m2", "u2", content="Your payment link", paymentReferenceId="ref-1")]
    rep = run(make_tables(base_contacts(), inbound=msgs), dry.Selection(contact_ids=["k1"]))
    c = by_cid(rep)
    assert c["u1"]["classification"] == dry.ELIGIBLE
    assert c["u2"]["classification"] == dry.FINANCIAL_RETENTION
    assert c["u2"]["financialMessages"] == 1


def test_message_matching_known_provider_id_is_financial():
    payments = [{"id": "p1", "paymentId": "pay_KNOWN9999", "contact": ""}]
    msgs = [msg("m1", "u1", content="see attachment", extraRef="pay_KNOWN9999")]
    c = by_cid(run(make_tables(base_contacts(), messages=msgs, payments=payments),
                   dry.Selection(contact_ids=["k1"])))
    assert c["u1"]["classification"] == dry.FINANCIAL_RETENTION


def test_keyword_only_adds_protection():
    msgs = [msg("m1", "u1", content="please refund me")]
    c = by_cid(run(make_tables(base_contacts(), messages=msgs), dry.Selection(contact_ids=["k1"])))
    assert c["u1"]["classification"] == dry.FINANCIAL_RETENTION


def test_locked_contact():
    rows = base_contacts() + [contact("lk", "+15550000031", locked=True)]
    c = by_cid(run(make_tables(rows), dry.Selection(contact_ids=["k1"])))
    assert c["lk"]["classification"] == dry.LEGAL_OR_IDENTITY_LOCK


def test_precedence_hold_over_financial_over_lock():
    rows = [contact("k1", "+15550000001", locked=True),
            contact("f1", "+15550000041", locked=True)]
    invoices = [{"invoiceId": "i", "contactId": "k1", "paymentStatus": "captured"},
                {"invoiceId": "j", "contactId": "f1", "paymentStatus": "captured"}]
    c = by_cid(run(make_tables(rows, invoices=invoices), dry.Selection(contact_ids=["k1"])))
    assert c["k1"]["classification"] == dry.OPERATOR_HOLD
    assert c["f1"]["classification"] == dry.FINANCIAL_RETENTION
    assert c["f1"]["alsoProtectedBy"]


def test_query_failure_is_review_required():
    rep = run(make_tables(base_contacts(), invoices=[]), dry.Selection(contact_ids=["k1"]))
    assert by_cid(rep)["u1"]["classification"] == dry.ELIGIBLE
    bad = make_tables(base_contacts(), invoices=[])
    bad["invoices"].fail = True
    rep = run(bad, dry.Selection(contact_ids=["k1"]))
    assert rep["status"] == "INCOMPLETE"
    assert rep["eligible"] == []
    assert by_cid(rep)["u1"]["classification"] == dry.REVIEW_REQUIRED


def test_message_table_failure_blocks_eligibility():
    tables = make_tables(base_contacts())
    tables["outbound"].fail = True
    rep = run(tables, dry.Selection(contact_ids=["k1"]))
    assert rep["eligible"] == []
    assert by_cid(rep)["u1"]["classification"] == dry.REVIEW_REQUIRED
    assert _exit_code(tables) == 2


def _exit_code(tables):
    return dry.main(["--keep-contact-id", "k1"],
                    backend=lambda region: (lambda name: tables[_logical(name)], None))


def test_contacts_scan_failure_is_incomplete():
    tables = make_tables(base_contacts())
    tables["contacts"].fail = True
    rep = run(tables, dry.Selection(contact_ids=["k1"]))
    assert rep["status"] == "INCOMPLETE" and rep["eligible"] == []


def test_contact_without_id_or_identity_needs_review():
    rows = base_contacts() + [{"phone": "+15550000051"}, contact("noid2", "")]
    rep = run(make_tables(rows), dry.Selection(contact_ids=["k1"]))
    cls = [c["classification"] for c in rep["contacts"]]
    assert cls.count(dry.REVIEW_REQUIRED) == 2


def test_message_linked_only_by_phone_flags_review_and_counts():
    msgs = [msg("m1", "", content="x", phone="+15550000011"), {"id": "m2", "contactId": "u2", "content": "ok"}]
    msgs[0].pop("contactId")
    c = by_cid(run(make_tables(base_contacts(), messages=msgs), dry.Selection(contact_ids=["k1"])))
    assert c["u1"]["classification"] == dry.REVIEW_REQUIRED
    assert c["u1"]["messageCounts"]["messages"]["total"] == 1
    assert c["u2"]["classification"] == dry.ELIGIBLE


def test_pagination_reads_every_page_with_exact_counts():
    rows = [contact("k1", "+15550000001")] + [contact(f"x{i}", f"+1555000{i:04d}") for i in range(7)]
    msgs = [msg(f"m{i}", "x3") for i in range(5)]
    outbound = [msg(f"o{i}", "x3") for i in range(3)]
    inbound = [msg(f"i{i}", "x3") for i in range(4)]
    tables = make_tables(rows, messages=msgs, inbound=inbound, outbound=outbound)
    rep = run(tables, dry.Selection(contact_ids=["k1"]))
    x3 = by_cid(rep)["x3"]
    assert x3["messageCounts"] == {"messages": {"total": 5, "financial": 0, "uncertain": 0},
                                   "inbound": {"total": 4, "financial": 0, "uncertain": 0},
                                   "outbound": {"total": 3, "financial": 0, "uncertain": 0}}
    assert x3["messageTotal"] == 12
    assert rep["totals"]["contactsScanned"] == 8
    assert rep["totals"]["contactsEligible"] == 7
    assert rep["totals"]["messagesEligible"] == 12


def test_non_advancing_pagination_is_incomplete():
    class Stuck(FakeTable):
        def scan(self, **kw):
            return {"Items": [{"id": "z"}], "LastEvaluatedKey": {"i": 1}}

    tables = make_tables(base_contacts())
    tables["messages"] = Stuck()
    rep = run(tables, dry.Selection(contact_ids=["k1"]))
    assert rep["eligible"] == []


def test_selected_contacts_all_messages_kept_with_per_table_counts():
    msgs = [msg(f"m{i}", "k1") for i in range(10)]
    inbound = [msg(f"i{i}", "k1") for i in range(7)]
    outbound = [msg(f"o{i}", "k1") for i in range(5)]
    rep = run(make_tables(base_contacts(), messages=msgs, inbound=inbound, outbound=outbound),
              dry.Selection(contact_ids=["k1"]))
    k1 = by_cid(rep)["k1"]
    assert (k1["messageCounts"]["messages"]["total"], k1["messageCounts"]["inbound"]["total"],
            k1["messageCounts"]["outbound"]["total"]) == (10, 7, 5)
    assert rep["totals"]["keptSelectedMessages"] == 22
    assert rep["totals"]["messagesEligible"] == 0


def test_already_archived_reported_separately():
    rows = base_contacts() + [contact("ar", "+15550000061", archivedAt=123, archivedBy="op")]
    rep = run(make_tables(rows), dry.Selection(contact_ids=["k1"]))
    assert "ar" not in {e["contactId"] for e in rep["eligible"]}
    assert rep["totals"]["contactsAlreadyArchived"] == 1


def test_ttl_at_risk_listing():
    soon, past, far = NOW + 10 * DAY, NOW - DAY, NOW + 400 * DAY
    msgs = [msg("pay-soon", "u1", paymentReferenceId="r", expiresAt=soon),
            msg("pay-past", "u1", paymentReferenceId="r", expiresAt=past),
            msg("pay-far", "u1", paymentReferenceId="r", expiresAt=far),
            msg("keep-soon", "k1", expiresAt=soon),
            msg("plain-soon", "u2", expiresAt=soon)]
    ttl = FakeTTL({NAMES["messages"]: True, NAMES["inbound"]: True, NAMES["outbound"]: True})
    rep = run(make_tables(base_contacts(), messages=msgs), dry.Selection(contact_ids=["k1"]),
              ttl_client=ttl, ttl_warn_days=90)
    risk = {r["messageId"]: r["flag"] for r in rep["ttl"]["atRisk"]}
    assert risk == {"pay-soon": "EXPIRES_WITHIN_WINDOW", "pay-past": "ALREADY_PAST_EXPIRY",
                    "keep-soon": "EXPIRES_WITHIN_WINDOW"}
    row = rep["ttl"]["perTable"]["messages"]
    assert (row["protectedMessages"], row["expiringSoon"], row["alreadyExpired"]) == (4, 2, 1)
    assert rep["ttl"]["ttlState"]["messages"].startswith("ENABLED")
    assert rep["ttl"]["ttlState"]["payments"] == "DISABLED"
    assert set(ttl.calls) == set(NAMES[k] for k in ("messages", "inbound", "outbound", "payments",
                                                    "attempts", "invoices"))


def test_ttl_describe_failure_is_reported_not_fatal():
    rep = run(make_tables(base_contacts()), dry.Selection(contact_ids=["k1"]), ttl_client=FakeTTL(fail=True))
    assert rep["ttl"]["ttlState"]["messages"].startswith("UNKNOWN")
    assert rep["status"] == "OK"


def test_read_only_proxy_blocks_writes():
    proxy = dry.ReadOnlyTable(FakeTable([]))
    for name in ("put_item", "update_item", "delete_item", "batch_write_item", "batch_writer"):
        with pytest.raises(PermissionError):
            getattr(proxy, name)
    # And a full run touches only read calls on every table.
    tables = make_tables(base_contacts(), messages=[msg("m", "u1")])
    run(tables, dry.Selection(contact_ids=["k1"]))
    for t in tables.values():
        assert set(t.calls) <= {"scan", "query", "get_item"}


def test_source_has_no_write_api_calls():
    src = open(_SCRIPT, encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("#", '"')))
    for call in (".put_item(", ".update_item(", ".delete_item(", ".batch_write", ".batch_writer(",
                 ".transact_write", ".update_time_to_live("):
        assert call not in code


def test_output_redacts_phones_and_bodies(tmp_path, capsys):
    secret_phone = "+15559998877"
    rows = [contact("wa15550000001", "+15550000001"), contact("wa15559998877", secret_phone)]
    msgs = [msg("m1", "wa15559998877", content="SECRET BODY TEXT")]
    tables = make_tables(rows, messages=msgs)
    out = tmp_path / "report.json"
    code = dry.main(["--keep-contact-id", "wa15550000001", "--output", str(out)],
                    backend=lambda region: (lambda name: tables[_logical(name)], None))
    assert code == 0
    printed = capsys.readouterr().out
    report_text = out.read_text()
    assert "15559998877" not in printed and "9998877" not in printed.replace("****8877", "")
    assert "15550000001" not in printed
    assert "SECRET BODY TEXT" not in printed and "SECRET BODY TEXT" not in report_text
    assert secret_phone not in report_text
    assert "wa15559998877" in report_text
    assert "****8877" in printed
    assert oct(os.stat(out).st_mode & 0o777) == "0o600"
    assert "Archive" in printed
    assert "wa****8877 ****8877 messages=1" in printed


def test_main_requires_a_selector(capsys):
    assert dry.main([], backend=lambda r: (None, None)) == 64


def test_output_and_config_inside_untracked_repo_path_refused():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    inside = os.path.join(repo_root, "docs", "ops", "selection-should-not-exist.json")
    assert dry.refuse_if_tracked_location(inside)
    assert dry.refuse_if_tracked_location("/tmp/outside-repo/selection.json") is None


def test_selection_file_roundtrip(tmp_path):
    path = tmp_path / "sel.json"
    path.write_text(json.dumps({"contactIds": ["a"], "phones": ["+1 (555) 000-0001"], "bsuids": ["B"]}))
    sel = dry.load_selection_file(str(path))
    assert sel.contact_ids == ["a"] and sel.phones == ["15550000001"] and sel.bsuids == ["B"]


def test_source_and_tests_hardcode_no_selection():
    # Operator-supplied words that must never appear in the repo; kept out of the repo itself.
    forbidden = tuple(w.strip().lower() for w in
                      os.environ.get("CONTACT_CLEANUP_FORBIDDEN_WORDS", "").split(",") if w.strip())
    for path in (_SCRIPT, __file__):
        text = open(path, encoding="utf-8").read().lower()
        assert not any(word in text for word in forbidden)
    assert not re.search(r"\+\d{10,}", open(_SCRIPT, encoding="utf-8").read())


def test_location_guard_fails_closed_when_git_unavailable(monkeypatch):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    monkeypatch.setattr(dry, "_git", lambda args, cwd: (128, ""))
    inside = os.path.join(repo_root, "docs", "ops", "sel.json")
    assert dry.refuse_if_tracked_location(inside)
    assert dry.refuse_if_tracked_location("/tmp/outside-repo/selection.json") is None


def test_write_report_replaces_loose_existing_file(tmp_path):
    out = tmp_path / "r.json"
    out.write_text("old")
    os.chmod(out, 0o644)
    dry.write_report(str(out), {"a": 1})
    assert oct(os.stat(out).st_mode & 0o777) == "0o600"
    assert json.loads(out.read_text()) == {"a": 1}
