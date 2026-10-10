"""The invoice-sequence reconciliation script reports by default and only ever moves forward.

WHAT THIS FILE IS FOR
---------------------
`scripts/reconcile_invoice_sequence.py` is the operator tool for the one thing the code cannot
fix by itself: a counter that was reset below numbers that have already gone to customers, where
part of the evidence (the invoice rows, and after a full system reset the reservation rows too)
no longer exists. It touches the GST counter, so the two properties that matter are not about
arithmetic:

1. nothing is written unless `--apply` is passed, so running it to look is always safe;
2. `--apply` can only move `last_seq` FORWARD, because moving it backwards would re-offer numbers
   that are already out - the defect the whole change exists to stop.

The counter is `crm_fake_dynamo`, which really evaluates the `attribute_not_exists(last_seq) OR
last_seq < :floor` guard and raises `ConditionalCheckFailedException`; that guard IS property 2.
The two scanned tables get purpose-built fakes because the shared fake has no `scan`, and
pagination is modelled because a single-page read would under-report the floor.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))
sys.path.insert(0, str(Path(__file__).parent))

import reconcile_invoice_sequence as rec  # noqa: E402
from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402

FY = "2026-2027"
KEYS_TABLE = order_keys.commerce_keys_table_name()


class _ScanTable:
    """A table that answers `scan` in fixed-size pages, and refuses every write.

    Refusing writes is the assertion, not an omission: this script must never put, update or
    delete anything on the invoice table or the keys table, so a fake that cannot do so turns
    that promise into a test failure rather than a code review.
    """

    def __init__(self, items, *, page_size: int = 50) -> None:
        self.items = [dict(item) for item in items]
        self.page_size = page_size
        self.pages = 0

    def scan(self, ExclusiveStartKey=None, **_):
        self.pages += 1
        start = int((ExclusiveStartKey or {}).get("n", 0))
        window = self.items[start:start + self.page_size]
        page = {"Items": window}
        if start + self.page_size < len(self.items):
            page["LastEvaluatedKey"] = {"n": start + self.page_size}
        return page

    def put_item(self, **_):
        raise AssertionError("reconciliation must not write to a scanned table")

    def update_item(self, **_):
        raise AssertionError("reconciliation must not write to a scanned table")

    def delete_item(self, **_):
        raise AssertionError("reconciliation must not write to a scanned table")


def _invoice_rows(*sequences, fy_short: str = "2627"):
    return [{"invoiceNumber": f"WD/{fy_short}/{seq:05d}"} for seq in sequences]


def _reservation_rows(*sequences):
    return [{"orderId": f"{order_keys.INVOICE_NUMBER_PREFIX}WD/2627/{seq:05d}",
             "invoiceNumber": f"WD/2627/{seq:05d}", "fy": FY,
             "kind": order_keys.INVOICE_NUMBER_KIND} for seq in sequences]


@pytest.fixture
def wired(monkeypatch):
    """`rec` pointed at in-memory tables. Returns a setup callable and the live handles."""
    state: dict = {}

    def setup(*, invoices=(), reservations=(), last_seq=None, page_size: int = 50):
        counter = FakeDynamo({rec.INVOICE_SEQ_TABLE: "fy"})
        counter_table = counter.Table(rec.INVOICE_SEQ_TABLE)
        if last_seq is not None:
            counter_table.rows[FY] = {"fy": FY, "last_seq": int(last_seq), "prefix": "WD"}
        tables = {
            rec.INVOICES_TABLE: _ScanTable(invoices, page_size=page_size),
            KEYS_TABLE: _ScanTable(reservations, page_size=page_size),
            rec.INVOICE_SEQ_TABLE: counter_table,
        }

        class _Resource:
            def Table(self, name):  # noqa: N802 - the boto3 resource spelling
                return tables[name]

        monkeypatch.setattr(rec, "_resource", lambda: _Resource())
        state.update(tables=tables, counter=counter_table)
        return state

    return setup


def _last_seq(state) -> int:
    row = state["counter"].rows.get(FY, {})
    return int(row.get("last_seq", 0) or 0)


# ══════════════════════════════════════════════════════════════════════════════
# report only, by default
# ══════════════════════════════════════════════════════════════════════════════

def test_the_default_run_writes_nothing_even_when_the_counter_is_behind(wired, capsys):
    state = wired(invoices=_invoice_rows(1, 2, 3, 4), last_seq=1)

    exit_code = rec.main(["--fy", FY])

    # 1, not 0: a counter behind the series is the condition an operator is asked to act on.
    assert exit_code == 1
    assert _last_seq(state) == 1
    out = capsys.readouterr().out
    assert "report only; nothing written" in out
    assert "--apply" in out


def test_an_explicit_dry_run_is_the_same_as_the_default(wired):
    state = wired(invoices=_invoice_rows(4), last_seq=1)

    assert rec.main(["--fy", FY, "--dry-run"]) == 1
    assert _last_seq(state) == 1


def test_apply_and_dry_run_together_are_refused(wired):
    wired(invoices=_invoice_rows(4), last_seq=1)

    with pytest.raises(SystemExit):
        rec.main(["--fy", FY, "--dry-run", "--apply"])


def test_a_floor_at_or_below_the_counter_is_a_no_op_even_with_apply(wired, capsys):
    state = wired(invoices=_invoice_rows(1, 2, 3, 4), reservations=_reservation_rows(4),
                  last_seq=9)

    assert rec.main(["--fy", FY, "--floor", "WD/2627/00004", "--apply"]) == 0
    assert _last_seq(state) == 9
    assert "nothing to do" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════════════
# --apply, forward only
# ══════════════════════════════════════════════════════════════════════════════

def test_apply_advances_the_counter_to_the_floor_and_is_idempotent(wired):
    state = wired(invoices=_invoice_rows(1, 2, 3, 4), last_seq=1)

    assert rec.main(["--fy", FY, "--apply"]) == 0
    assert _last_seq(state) == 4

    # A second run finds nothing to do rather than advancing again.
    assert rec.main(["--fy", FY, "--apply"]) == 0
    assert _last_seq(state) == 4


def test_the_conditional_guard_refuses_to_move_the_counter_backwards(wired):
    """The guard itself, exercised directly: two concurrent runs cannot lose a number."""
    state = wired(last_seq=10)

    assert rec.advance_counter(state["counter"], fy=FY, floor=4) is False
    assert _last_seq(state) == 10
    assert rec.advance_counter(state["counter"], fy=FY, floor=11) is True
    assert _last_seq(state) == 11


def test_apply_creates_the_counter_row_when_the_wipe_removed_it(wired):
    state = wired(reservations=_reservation_rows(1, 2), last_seq=None)

    assert rec.main(["--fy", FY, "--apply"]) == 0
    assert _last_seq(state) == 2


# ══════════════════════════════════════════════════════════════════════════════
# the three sources
# ══════════════════════════════════════════════════════════════════════════════

def test_the_operator_floor_wins_when_it_is_the_highest_source(wired, capsys):
    state = wired(invoices=_invoice_rows(2), reservations=_reservation_rows(3), last_seq=1)

    assert rec.main(["--fy", FY, "--floor", "WD/2627/00004", "--apply"]) == 0
    assert _last_seq(state) == 4
    out = capsys.readouterr().out
    assert "proposed floor" in out


def test_the_reservation_rows_win_when_the_invoice_rows_were_erased(wired):
    """The C2 recovery shape: the invoices are gone, the `INVOICENO#` rows are not."""
    state = wired(invoices=(), reservations=_reservation_rows(1, 2, 3, 4), last_seq=0)

    assert rec.main(["--fy", FY, "--apply"]) == 0
    assert _last_seq(state) == 4


def test_every_invoice_page_is_read(wired):
    state = wired(invoices=_invoice_rows(*range(1, 8)), last_seq=0, page_size=2)

    assert rec.main(["--fy", FY, "--apply"]) == 0
    assert _last_seq(state) == 7
    assert state["tables"][rec.INVOICES_TABLE].pages == 4


def test_numbers_from_another_financial_year_do_not_raise_this_years_floor(wired):
    state = wired(invoices=_invoice_rows(99, fy_short="2526") + _invoice_rows(2), last_seq=0)

    assert rec.main(["--fy", FY, "--apply"]) == 0
    assert _last_seq(state) == 2


def test_an_unreadable_number_contributes_nothing_rather_than_failing_the_report(wired):
    state = wired(invoices=[{"invoiceNumber": "WD-PAY-TEMP-legacy"}, {}] + _invoice_rows(3),
                  last_seq=0)

    assert rec.main(["--fy", FY, "--apply"]) == 0
    assert _last_seq(state) == 3


def test_a_floor_that_is_not_an_invoice_number_for_this_year_is_refused(wired):
    wired(invoices=_invoice_rows(1), last_seq=0)

    with pytest.raises(SystemExit):
        rec.main(["--fy", FY, "--floor", "WD/2526/00009"])
