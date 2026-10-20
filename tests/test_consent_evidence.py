"""Consent is evidence with an append-only history, not a boolean.

These tests pin the three properties the model exists to guarantee:
  * appending evidence never erases prior history, and the current state is the latest record;
  * OPTED_OUT is a first-class state that is representable and respected;
  * an import carries EXISTING evidence only and can never manufacture an opt-in from an
    address book - a boolean/weak import cannot overwrite richer evidence.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))

from lambda_utils.identity import consent  # noqa: E402

NOW = 1_700_000_000


# ── building and validating a record ───────────────────────────────────────────

def test_a_record_carries_the_full_evidence_shape():
    record = consent.build_record(
        channel='whatsapp', state='opted_in', source='web_form', at=NOW,
        purpose='marketing', reference='form:WD_SUBSCRIBE#42', expiry=NOW + 1000)
    assert record == {
        'channel': 'WHATSAPP', 'state': 'OPTED_IN', 'source': 'WEB_FORM',
        'at': NOW, 'purpose': 'MARKETING',
        'reference': 'form:WD_SUBSCRIBE#42', 'expiry': NOW + 1000,
    }


def test_an_unknown_channel_state_source_or_purpose_is_refused():
    for bad in [
        dict(channel='TELEGRAM', state='OPTED_IN', source='WEB_FORM', at=NOW),
        dict(channel='SMS', state='MAYBE', source='WEB_FORM', at=NOW),
        dict(channel='SMS', state='OPTED_IN', source='TELEPATHY', at=NOW),
        dict(channel='SMS', state='OPTED_IN', source='WEB_FORM', at=NOW, purpose='SPAM'),
    ]:
        with pytest.raises(consent.InvalidConsentRecord):
            consent.build_record(**bad)


def test_a_missing_purpose_defaults_to_the_strictest():
    record = consent.build_record(channel='EMAIL', state='OPTED_IN', source='WEB_FORM', at=NOW)
    assert record['purpose'] == consent.MARKETING


def test_a_non_positive_timestamp_is_refused():
    with pytest.raises(consent.InvalidConsentRecord):
        consent.build_record(channel='SMS', state='OPTED_IN', source='WEB_FORM', at=0)


# ── append-only history ─────────────────────────────────────────────────────────

def test_appending_evidence_keeps_the_entire_prior_history():
    first = consent.build_record(channel='WHATSAPP', state='OPTED_IN', source='WEB_FORM',
                                 at=NOW)
    contact = {consent.ATTRIBUTE: [first]}
    second = consent.build_record(channel='WHATSAPP', state='OPTED_OUT',
                                  source='CUSTOMER_REQUEST', at=NOW + 100)
    ledger = consent.append(contact, second)
    assert ledger == [first, second], 'the opt-in record must survive the opt-out'
    assert len(ledger) == 2


def test_append_never_mutates_the_input_ledger():
    first = consent.build_record(channel='SMS', state='OPTED_IN', source='WEB_FORM', at=NOW)
    contact = {consent.ATTRIBUTE: [first]}
    consent.append(contact, consent.build_record(
        channel='SMS', state='OPTED_OUT', source='CUSTOMER_REQUEST', at=NOW + 1))
    assert contact[consent.ATTRIBUTE] == [first], 'the stored ledger was mutated in place'


def test_an_identical_replayed_record_does_not_duplicate_history():
    record = consent.build_record(channel='EMAIL', state='OPTED_IN', source='WEB_FORM', at=NOW)
    contact = {consent.ATTRIBUTE: [record]}
    assert consent.append(contact, dict(record)) == [record]


def test_a_junk_entry_is_dropped_on_read_rather_than_raising():
    contact = {consent.ATTRIBUTE: [
        {'channel': 'NOPE'},  # junk
        consent.build_record(channel='SMS', state='OPTED_IN', source='WEB_FORM', at=NOW),
    ]}
    ledger = consent.ledger_of(contact)
    assert len(ledger) == 1
    assert ledger[0]['channel'] == 'SMS'


# ── current state resolution ────────────────────────────────────────────────────

def test_current_state_is_the_latest_non_expired_record():
    contact = {consent.ATTRIBUTE: [
        consent.build_record(channel='WHATSAPP', state='OPTED_IN', source='WEB_FORM', at=NOW),
        consent.build_record(channel='WHATSAPP', state='OPTED_OUT',
                             source='CUSTOMER_REQUEST', at=NOW + 10),
    ]}
    assert consent.current_state(contact, 'WHATSAPP', now=NOW + 20) == consent.OPTED_OUT
    assert not consent.is_sendable(contact, 'WHATSAPP', now=NOW + 20)


def test_a_channel_with_no_record_is_pending_never_opted_in():
    assert consent.current_state({}, 'SMS', now=NOW) == consent.PENDING
    assert not consent.is_sendable({}, 'SMS', now=NOW)


def test_an_expired_opt_in_is_not_sendable():
    contact = {consent.ATTRIBUTE: [
        consent.build_record(channel='EMAIL', state='OPTED_IN', source='WEB_FORM',
                             at=NOW, expiry=NOW + 100),
    ]}
    assert consent.is_sendable(contact, 'EMAIL', now=NOW + 50)
    assert not consent.is_sendable(contact, 'EMAIL', now=NOW + 200)


def test_opted_out_is_respected_even_after_a_later_weaker_signal_is_filtered_by_purpose():
    # A transactional opt-in must not re-permission marketing after a marketing opt-out.
    contact = {consent.ATTRIBUTE: [
        consent.build_record(channel='SMS', state='OPTED_OUT', source='CUSTOMER_REQUEST',
                             at=NOW, purpose='MARKETING'),
        consent.build_record(channel='SMS', state='OPTED_IN', source='CHECKOUT_VERIFIED',
                             at=NOW + 10, purpose='TRANSACTIONAL'),
    ]}
    assert consent.current_state(contact, 'SMS', now=NOW + 20,
                                 purpose='MARKETING') == consent.OPTED_OUT


# ── summary for the UI ──────────────────────────────────────────────────────────

def test_summarize_reports_state_history_depth_and_sendability():
    contact = {consent.ATTRIBUTE: [
        consent.build_record(channel='WHATSAPP', state='OPTED_IN', source='WEB_FORM', at=NOW),
        consent.build_record(channel='WHATSAPP', state='OPTED_OUT',
                             source='CUSTOMER_REQUEST', at=NOW + 10),
    ]}
    summary = consent.summarize(contact, now=NOW + 20)
    assert set(summary) == {'WHATSAPP'}
    assert summary['WHATSAPP']['state'] == consent.OPTED_OUT
    assert summary['WHATSAPP']['history'] == 2
    assert summary['WHATSAPP']['sendable'] is False


# ── import: existing evidence only, never manufactured opt-in ────────────────────

def test_an_imported_row_with_no_evidence_does_not_become_opted_in():
    with pytest.raises(consent.ConsentImportRefused):
        consent.record_from_import(
            {'channel': 'WHATSAPP', 'state': 'OPTED_IN', 'importSource': 'CSV_IMPORT',
             'at': NOW}, now=NOW)


def test_an_address_book_can_never_manufacture_an_opt_in():
    with pytest.raises(consent.ConsentImportRefused):
        consent.record_from_import(
            {'channel': 'SMS', 'state': 'OPTED_IN', 'importSource': 'ADDRESS_BOOK',
             'at': NOW, 'reference': 'book:contacts', 'evidenceSource': 'ADDRESS_BOOK'},
            now=NOW)


def test_an_import_may_carry_an_existing_opt_in_with_original_source_and_reference():
    record = consent.record_from_import(
        {'channel': 'EMAIL', 'state': 'OPTED_IN', 'importSource': 'MIGRATION', 'at': NOW,
         'evidenceSource': 'DOUBLE_OPT_IN', 'reference': 'mailchimp:list#9/confirm'},
        now=NOW)
    assert record['state'] == consent.OPTED_IN
    # The stored source is the ORIGINATING one, not the import mechanism.
    assert record['source'] == 'DOUBLE_OPT_IN'
    assert record['reference'] == 'mailchimp:list#9/confirm'


def test_an_import_may_always_carry_an_opt_out():
    record = consent.record_from_import(
        {'channel': 'WHATSAPP', 'state': 'OPTED_OUT', 'importSource': 'CSV_IMPORT', 'at': NOW},
        now=NOW)
    assert record['state'] == consent.OPTED_OUT


def test_an_import_missing_a_timestamp_is_refused():
    with pytest.raises(consent.ConsentImportRefused):
        consent.record_from_import(
            {'channel': 'SMS', 'state': 'OPTED_OUT', 'importSource': 'CSV_IMPORT'}, now=NOW)


def test_a_weak_import_cannot_overwrite_richer_existing_evidence():
    """A real opt-in with a reference is on the ledger; a later importable OPTED_OUT appends
    rather than erasing, and a manufactured OPTED_IN import is refused outright - so there is
    no path by which a boolean import clobbers the evidence."""
    opt_in = consent.build_record(channel='WHATSAPP', state='OPTED_IN', source='DOUBLE_OPT_IN',
                                  at=NOW, reference='confirm#1')
    contact = {consent.ATTRIBUTE: [opt_in]}
    with pytest.raises(consent.ConsentImportRefused):
        consent.record_from_import(
            {'channel': 'WHATSAPP', 'state': 'OPTED_IN', 'importSource': 'CSV_IMPORT',
             'at': NOW + 5}, now=NOW)
    # The original evidence is still intact and sendable.
    assert consent.ledger_of(contact) == [opt_in]
    assert consent.is_sendable(contact, 'WHATSAPP', now=NOW + 10)
