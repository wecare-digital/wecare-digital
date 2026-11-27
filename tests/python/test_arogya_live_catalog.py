"""Synthetic catalogue contract checks; never contact Apollo or AWS."""
from unittest.mock import Mock

import pytest

from lambda_utils.arogya import provider_runtime as runtime

NOW = 1795737600


def test_catalogue_only_returns_normalized_live_options():
    provider = Mock()
    provider.catalog.return_value = [{'HospitalId': 1, 'HospitalName': 'Synthetic Hospital',
        'City': 'Chennai', 'privateField': 'must not be returned'}]
    data = runtime.read_catalog({'action': 'catalog', 'kind': 'hospitals'}, now=NOW,
        session=lambda now: (provider, 'test-session'))
    assert data == {'options': [{'id': '1', 'label': 'Synthetic Hospital', 'city': 'Chennai'}],
        'observedAt': NOW}
    provider.catalog.assert_called_once_with('hospitals', token='test-session')


def test_doctor_choices_use_selected_provider_ids():
    provider = Mock()
    provider.catalog.return_value = {'data': [{'doctorId': 24, 'doctorName': 'Synthetic Doctor'}]}
    result = runtime.read_catalog({'action': 'catalog', 'kind': 'doctors',
        'hospitalId': '10', 'specialityId': '12'}, now=NOW,
        session=lambda now: (provider, 'test-session'))
    assert result['options'] == [{'id': '24', 'label': 'Synthetic Doctor'}]
    provider.catalog.assert_called_once_with('doctors', token='test-session',
        hospital_id=10, speciality_id=12)


def test_available_dates_are_from_provider_and_past_dates_are_excluded():
    provider = Mock()
    provider.available_dates.return_value = {'dates': ['2026-01-01', '30/11/2026', '2026-11-30']}
    data = runtime.read_catalog({'action': 'catalog', 'kind': 'dates',
        'hospitalId': '10', 'doctorId': '24'}, now=NOW,
        session=lambda now: (provider, 'test-session'))
    assert data['options'] == [{'id': '2026-11-30', 'label': '2026-11-30'}]
    provider.available_dates.assert_called_once_with('consultation', token='test-session',
        hospital_id=10, item_id=24)


def test_unauthorized_or_unknown_provider_schema_fails_closed(monkeypatch):
    monkeypatch.delenv('APOLLO_REGISTRY_TABLE', raising=False)
    with pytest.raises(runtime.CatalogueUnavailable):
        runtime.read_catalog({'action': 'catalog', 'kind': 'hospitals'}, now=NOW)
    provider = Mock()
    provider.catalog.return_value = {'error': 'upstream response'}
    with pytest.raises(runtime.CatalogueUnavailable):
        runtime.read_catalog({'action': 'catalog', 'kind': 'hospitals'}, now=NOW,
            session=lambda now: (provider, 'test-session'))


@pytest.mark.parametrize('body', [
    {'action': 'catalog', 'kind': 'doctors', 'hospitalId': '1/../../', 'specialityId': '2'},
    {'action': 'catalog', 'kind': 'booking'},
    {'action': 'catalog', 'kind': 'hospitals', 'token': 'caller-provided'},
    {'action': 'catalog', 'kind': 'dates', 'hospitalId': '1', 'doctorId': '2', 'healthCheckId': '3'},
])
def test_invalid_requests_do_not_read_provider(body):
    session = Mock()
    with pytest.raises(runtime.InvalidCatalogueRequest):
        runtime.read_catalog(body, now=NOW, session=session)
    session.assert_not_called()
