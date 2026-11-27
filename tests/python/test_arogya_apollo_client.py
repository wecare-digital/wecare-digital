"""Verify fixed-origin API requests and public error hygiene with synthetic responses."""
import io
import json
import urllib.error
import pytest
from lambda_utils.arogya.apollo_client import ApolloClient, ApolloUnavailable, ApolloSessionExpired, ORIGIN
from lambda_utils.arogya.apollo_session import MAILBOX


class Opener:
    def __init__(self, value=None, error=None): self.calls = []; self.value = value or {}; self.error = error
    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error: raise self.error
        return io.BytesIO(json.dumps(self.value).encode())


def client(value=None, error=None):
    instance = ApolloClient('synthetic-application-header')
    instance._opener = Opener(value, error)
    return instance


def test_login_and_verification_follow_observed_portal_contracts():
    api = client()
    api.login({'userName': 'encoded-user', 'password': 'encoded-password'})
    api.send_otp(MAILBOX)
    api.verify_otp(user_id=12, email=MAILBOX, otp='123456')
    requests = [x[0] for x in api._opener.calls]
    assert [r.full_url for r in requests] == [ORIGIN + suffix for suffix in ('Login', 'SendOtp', 'VerifyOtp')]
    assert all(r.get_method() == 'POST' for r in requests)
    assert json.loads(requests[1].data)['lstEmails'] == [MAILBOX]
    assert json.loads(requests[2].data) == {'userId': 12, 'emailorMobile': MAILBOX, 'otp': '123456'}
    assert all(timeout == 6 for _, timeout in api._opener.calls)


def test_catalog_lookup_cannot_become_an_arbitrary_api_proxy():
    api = client([])
    api.catalog('doctors', token='synthetic-session', hospital_id=2, speciality_id=260)
    request = api._opener.calls[0][0]
    assert request.full_url == ORIGIN + 'GetDoctorsByMultiSpecAndHospital/260/2'
    assert request.get_header('Authorization') == 'Bearer synthetic-session'
    with pytest.raises(ApolloUnavailable): api.catalog('AddICPatientRequest', token='synthetic-session', hospital_id=2)
    with pytest.raises(ApolloUnavailable): api.catalog('doctors', token='synthetic-session', hospital_id='../other', speciality_id=260)
    assert len(api._opener.calls) == 1


def test_schedule_is_an_explicit_read_operation_even_though_provider_uses_post():
    api = client([])
    api.available_dates('consultation', token='synthetic-session', hospital_id=2, item_id=1785652)
    request = api._opener.calls[0][0]
    assert request.full_url == ORIGIN + 'GetConsultationAppointmentDates'
    assert json.loads(request.data) == {'hospitalId': 2, 'doctorId': 1785652, 'isAngularRequest': True}


def test_provider_errors_do_not_echo_secrets_or_patient_data(caplog):
    error = urllib.error.HTTPError(ORIGIN, 401, 'synthetic-private-message', {}, io.BytesIO(b'synthetic-private-body'))
    api = client(error=error)
    with pytest.raises(ApolloSessionExpired) as raised: api.get_profile('synthetic-session')
    assert str(raised.value) == 'Provider authorization required'
    assert 'synthetic' not in str(raised.value)
    assert 'resource=GetProfile status=401' in caplog.text
    assert 'synthetic' not in caplog.text


def test_transport_diagnostics_do_not_log_error_reasons_or_request_credentials(caplog):
    api = client(error=urllib.error.URLError('synthetic-private-reason'))
    with pytest.raises(ApolloUnavailable):
        api.login({'userName': 'synthetic-user', 'password': 'synthetic-password'})
    assert 'resource=Login category=URLError' in caplog.text
    assert 'synthetic' not in caplog.text
