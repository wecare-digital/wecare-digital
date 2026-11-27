"""Fixed-origin Apollo IC API transport, based on the inspected official portal.

This client has no public booking-write method. Paid booking submission needs its
own owner/idempotency gate; a general proxy must never expose agent credentials.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

ORIGIN = 'https://aaservicesv2.apollohospitals.com/ICUser/'


class ApolloUnavailable(RuntimeError):
    pass


class ApolloSessionExpired(ApolloUnavailable):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ApolloUnavailable('Provider redirect refused')


class ApolloClient:
    def __init__(self, application_header: str):
        if not application_header or '\n' in application_header or '\r' in application_header:
            raise ValueError('Provider application configuration required')
        self._application_header = application_header
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _request(self, path, *, token='', payload=None):
        if not re.fullmatch(r'[A-Za-z0-9/]+', path):
            raise ApolloUnavailable('Provider resource refused')
        headers = {'Accept': 'application/json', 'xauthtoken': self._application_header}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        data = None
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(ORIGIN + path, data=data, headers=headers,
                                         method='POST' if payload is not None else 'GET')
        try:
            with self._opener.open(request, timeout=6) as response:
                raw = response.read(1048577)
                if len(raw) > 1048576:
                    raise ApolloUnavailable('Provider response exceeded limit')
                value = json.loads(raw)
                if not isinstance(value, (dict, list)):
                    raise ApolloUnavailable('Provider response invalid')
                return value
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise ApolloSessionExpired('Provider authorization required') from None
            raise ApolloUnavailable('Provider request failed') from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise ApolloUnavailable('Provider temporarily unavailable') from None

    def login(self, payload):
        if set(payload) != {'userName', 'password'}:
            raise ApolloUnavailable('Provider sign-in payload refused')
        return self._request('Login', payload=payload)

    def send_otp(self, email):
        from .apollo_session import MAILBOX
        if email != MAILBOX:
            raise ApolloUnavailable('Provider mailbox refused')
        # Do not disable provider CAPTCHA or request-decryption protections. If
        # the approved service interface requires an interactive challenge, stop.
        return self._request('SendOtp', payload={
            'lstEmails': [email],
            'leadSource': 'ApolloAdminLogin', 'emailTemplateId': 188,
        })

    def verify_otp(self, *, user_id, email, otp):
        from .apollo_session import MAILBOX
        if email != MAILBOX or type(user_id) is not int or user_id <= 0 or not re.fullmatch(r'\d{6}', otp):
            raise ApolloUnavailable('Provider verification payload refused')
        return self._request('VerifyOtp', payload={'userId': user_id, 'emailorMobile': email, 'otp': otp})

    def get_profile(self, token):
        return self._request('GetProfile', token=token)

    def catalog(self, kind, *, token, hospital_id=None, speciality_id=None):
        if not token:
            raise ApolloSessionExpired('Provider authorization required')
        fixed = {'hospitals': 'GetAllICHospitals', 'appointmentTypes': 'GetAppointmentTypes',
                 'salutations': 'GetSalutations', 'hours': 'GetICHours', 'minutes': 'GetICMinutes'}
        if kind in fixed:
            return self._request(fixed[kind], token=token)
        if type(hospital_id) is not int or not 0 < hospital_id < 100000:
            raise ApolloUnavailable('Hospital identifier refused')
        if kind == 'specialities':
            return self._request(f'GetMultiSpecialitiesByHospitalId/{hospital_id}', token=token)
        if kind == 'healthChecks':
            return self._request(f'GetHealthChecksByHospitalId/{hospital_id}', token=token)
        if kind == 'doctors' and type(speciality_id) is int and 0 < speciality_id < 100000:
            return self._request(f'GetDoctorsByMultiSpecAndHospital/{speciality_id}/{hospital_id}', token=token)
        raise ApolloUnavailable('Provider catalogue resource refused')

    def available_dates(self, kind, *, token, hospital_id, item_id):
        if not token:
            raise ApolloSessionExpired('Provider authorization required')
        if any(type(value) is not int or value <= 0 for value in (hospital_id, item_id)):
            raise ApolloUnavailable('Provider schedule identifiers refused')
        if kind == 'consultation':
            return self._request('GetConsultationAppointmentDates', token=token, payload={
                'hospitalId': hospital_id, 'doctorId': item_id, 'isAngularRequest': True})
        if kind == 'healthCheck':
            return self._request('GetHealthCheckAppointmentDates', token=token, payload={
                'hospitalId': hospital_id, 'healthCheckId': item_id, 'isAngularRequest': True})
        raise ApolloUnavailable('Provider schedule resource refused')
