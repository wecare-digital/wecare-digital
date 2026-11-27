"""Explicit Admin delegation for the Apollo service; never returns credentials."""
import re
import secrets
import time
import urllib.request

MAILBOX = 'wecare.digital.bw@gmail.com'
PROVIDER = 'google-gmail-apollo'
BINDING = 'arogya:provider:gmail'
CREDENTIALS = 'arogya:provider:credentials'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Apollo configuration redirect refused')


def application_header():
    """Read the public application identifier from the official portal bundle only."""
    root = 'https://aauser-ic.apollohospitals.com/'
    opener = urllib.request.build_opener(NoRedirect)
    def read(url, maximum):
        with opener.open(url, timeout=6) as response:
            raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise ValueError('Apollo application configuration exceeded limit')
            return raw.decode('utf-8')
    html = read(root, 524288)
    names = re.findall(r'<script[^>]+src=["\']((?:main[.-])[A-Za-z0-9_.-]+\.js)["\']', html)
    if len(names) != 1:
        raise ValueError('Apollo application configuration could not be verified')
    script = read(root + names[0], 4 * 1024 * 1024)
    values = re.findall(r'apiKeyV2\s*:\s*["\']([^"\'\r\n]{1,1024})["\']', script)
    if len(set(values)) != 1:
        raise ValueError('Apollo application configuration could not be verified')
    return values[0]


def status(owner, table):
    binding = table.get_item(Key={'pk': BINDING}, ConsistentRead=True).get('Item', {})
    credentials = table.get_item(Key={'pk': CREDENTIALS}, ConsistentRead=True).get('Item', {})
    gmail = table.get_item(Key={'pk': 'connection:' + owner + ':' + PROVIDER}, ConsistentRead=True).get('Item', {})
    return {'mailbox': MAILBOX, 'gmailConnected': bool(gmail.get('cipher')), 'delegated': binding.get('owner') == owner,
            'credentialsConfigured': bool(credentials.get('cipher')) and credentials.get('owner') == owner
                and bool(binding.get('revision')) and binding.get('revision') == credentials.get('revision')}


def configure(owner, args, *, table, encrypt, token, http, refuse, header=application_header):
    if args.get('authorizeService') is not True:
        raise refuse('Explicit authorization for the Arogya service is required')
    password = args.get('password')
    if not isinstance(password, str) or not 1 <= len(password) <= 256:
        raise refuse('Enter the Apollo account password in the secure settings form')
    # The caller is the gateway-verified Admin. The business grant is explicitly
    # delegated here, rather than copied from a ChatGPT connection or browser.
    access = token(owner, PROVIDER)
    profile, _ = http('https://gmail.googleapis.com/gmail/v1/users/me/profile',
                      headers={'Authorization': 'Bearer ' + access})
    if str(profile.get('emailAddress', '')).lower() != MAILBOX:
        raise refuse('Connect the Apollo business mailbox before activating the service')
    try:
        app_header = header()
    except Exception:
        raise refuse('Apollo application configuration could not be verified') from None
    cipher = encrypt({'username': MAILBOX, 'password': password, 'applicationHeader': app_header}, owner, PROVIDER)
    now = int(time.time())
    revision = secrets.token_hex(16)
    table.put_item(Item={'pk': CREDENTIALS, 'owner': owner, 'provider': PROVIDER,
                         'cipher': cipher, 'updatedAt': now, 'revision': revision})
    table.delete_item(Key={'pk': 'arogya:provider:apollo'})
    table.put_item(Item={'pk': BINDING, 'owner': owner, 'provider': PROVIDER,
                         'expectedMailbox': MAILBOX, 'authorizedAt': now, 'revision': revision})
    return {'status': 'configured', 'mailbox': MAILBOX, 'credentialsConfigured': True,
            'message': 'Service access saved. Apollo sign-in renews on demand.'}
