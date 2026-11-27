"""Synthetic messages only. No mailbox access or real OTPs."""
import base64
import pytest
from lambda_utils.arogya.gmail_otp import find_apollo_otp, MailboxAccessRequired

MAILBOX = 'test-mailbox@gmail.com'
SENDER = 'test-sender@apollohospitals.com'
START = 1000000


def transport(*, profile=MAILBOX, received=START + 1000, text='Your Apollo OTP is 123456', sender=SENDER, mime='text/plain'):
    calls = []
    def get(path, params):
        calls.append((path, params))
        if path.endswith('/profile'):
            return {'emailAddress': profile}
        if path.endswith('/messages'):
            return {'messages': [{'id': 'synthetic-message'}]}
        return {'internalDate': str(received), 'payload': {
            'mimeType': mime, 'headers': [
                {'name': 'From', 'value': sender}, {'name': 'To', 'value': MAILBOX}],
            'body': {'data': base64.urlsafe_b64encode(text.encode()).decode()}}}
    return get, calls


def find(get, **extra):
    return find_apollo_otp(get, expected_mailbox=MAILBOX, approved_sender=SENDER,
                           requested_at_ms=START, now_ms=START + 2000, **extra)


def test_current_challenge_code_is_not_in_repr_and_uses_narrow_gmail_query():
    get, calls = transport()
    result = find(get)
    assert result.code == '123456'
    assert '123456' not in repr(result)
    assert calls[1][1]['q'] == f'from:{SENDER} to:{MAILBOX} after:1000'


def test_wrong_mailbox_is_rejected_before_message_search():
    get, calls = transport(profile='other@gmail.com')
    with pytest.raises(MailboxAccessRequired):
        find(get)
    assert len(calls) == 1


@pytest.mark.parametrize('options', [
    {'received': START - 1}, {'sender': 'unapproved@example.com'},
    {'text': 'OTP 123456 and 654321'}, {'text': 'An unrelated number 123456'},
])
def test_stale_wrong_sender_ambiguous_and_unrelated_messages_are_ignored(options):
    get, _ = transport(**options)
    assert find(get) is None


def test_consumed_message_is_not_reused():
    get, calls = transport()
    assert find(get, consumed_message_ids=frozenset({'synthetic-message'})) is None
    assert len(calls) == 2


def test_html_styles_attributes_and_comments_cannot_be_mistaken_for_codes():
    html = '''<style>body {color:#000000;background:#123123}</style>
        <script>var number=654321;</script><!-- 999999 -->
        <p style="color:#111111" data-id="888888">Please use this One Time Password (OTP)
        to sign in: <strong>123456</strong>.</p>'''
    get, _ = transport(text=html, mime='text/html')
    assert find(get).code == '123456'
    get, _ = transport(text=html + '<p>Another OTP: 222222</p>', mime='text/html')
    assert find(get) is None


def test_transport_refuses_arbitrary_resources_before_loading_a_token():
    from lambda_utils.arogya.gmail_otp import GmailApi, GmailReadUnavailable
    client = GmailApi(lambda: pytest.fail('must not load credentials for a rejected resource'))
    with pytest.raises(GmailReadUnavailable):
        client('https://example.com/', {})
    with pytest.raises(GmailReadUnavailable):
        client('/gmail/v1/users/me/messages/send', {'to': 'elsewhere'})


def test_transport_calls_only_fixed_gmail_origin_and_bounds_response():
    import io
    from lambda_utils.arogya.gmail_otp import GmailApi
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.get_method(), timeout))
            assert request.get_header('Authorization') == 'Bearer synthetic-token'
            return io.BytesIO(b'{"emailAddress":"test-mailbox@gmail.com"}')
    client = GmailApi(lambda: 'synthetic-token')
    client._opener = Opener()
    assert client('/gmail/v1/users/me/profile', {})['emailAddress'] == MAILBOX
    assert calls == [('https://gmail.googleapis.com/gmail/v1/users/me/profile', 'GET', 5)]
