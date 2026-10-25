"""Fixed read adapters. No caller-supplied URLs, queries, credentials or writes."""
import base64
import re


def required_fields(credentials: dict, names: tuple[str, ...], refuse) -> dict:
    """Validate runtime fields without returning their values in an error."""
    if not isinstance(credentials, dict) or any(
            not isinstance(credentials.get(name), str) or not credentials[name].strip()
            for name in names):
        raise refuse('Provider credential configuration is incomplete')
    return credentials


def account_http(http, refuse, url: str, **kwargs) -> dict:
    """Provider error bodies can contain credentials; report only HTTP status."""
    try:
        result, _ = http(url, **kwargs)
    except Exception as exc:
        status = getattr(exc, 'detail', None)
        status = status.get('status') if isinstance(status, dict) else None
        suffix = f' (HTTP {status})' if type(status) is int else ''
        raise refuse('Provider account read failed' + suffix) from None
    if not isinstance(result, dict):
        raise refuse('Provider account response is invalid')
    return result


def verify(provider, owner, secret, http, token, refuse, config):
    if provider == 'razorpay':
        credentials = secret('wecare/razorpay/api')
        encoded = base64.b64encode((credentials['key_id'] + ':' + credentials['key_secret']).encode()).decode()
        result, _ = http('https://api.razorpay.com/v1/orders?count=1', headers={'Authorization': 'Basic ' + encoded})
        if result.get('entity') != 'collection' or not isinstance(result.get('items'), list):
            raise refuse('Razorpay did not confirm orders read access')
        return {'mode': 'read-only', 'resource': result.get('entity'), 'returnedCount': result.get('count')}
    if provider == 'google-cloud':
        result, _ = http('https://cloudresourcemanager.googleapis.com/v3/projects/wecaredigitalbw',
            headers={'Authorization': 'Bearer ' + token(owner, provider)})
        if result.get('projectId') != 'wecaredigitalbw':
            raise refuse('Google Cloud did not confirm the configured project')
        return {'project': result.get('projectId'), 'state': result.get('state'), 'resource': result.get('name')}
    if provider == 'google-ads':
        credentials = secret('wecare/google/ads')
        result, _ = http('https://googleads.googleapis.com/v25/customers:listAccessibleCustomers',
            headers={'Authorization': 'Bearer ' + token(owner, provider), 'developer-token': credentials['developer_token']})
        if not isinstance(result.get('resourceNames'), list):
            raise refuse('Google Ads did not confirm accessible customer read access')
        customers = [v.split('/')[-1] for v in result.get('resourceNames', [])]
        return {'accessibleCustomerIds': customers, 'manager': '4270412231', 'mode': 'read-only'}
    if provider == 'plivo':
        credentials = required_fields(secret('wecare/plivo/api'), ('auth_id', 'auth_token'), refuse)
        if not re.fullmatch(r'[A-Za-z0-9]{1,100}', credentials['auth_id']):
            raise refuse('Plivo account identifier is invalid')
        encoded = base64.b64encode((credentials['auth_id'] + ':' + credentials['auth_token']).encode()).decode()
        result = account_http(http, refuse, 'https://api.plivo.com/v1/Account/' + credentials['auth_id'] + '/',
            headers={'Authorization': 'Basic ' + encoded})
        if result.get('auth_id') != credentials['auth_id'] or result.get('account_type') not in {'standard', 'developer'}:
            raise refuse('Plivo did not confirm the configured account')
        # Never return auth_id, contact details, raw account records or credentials.
        return {'mode': 'read-only', 'liveAccountAccess': True, 'accountType': result['account_type'],
            'billingMode': result.get('billing_mode')}
    if provider == 'sinch':
        credentials = required_fields(secret('wecare/sinch/rcs'),
            ('username', 'password', 'project_id', 'app_id'), refuse)
        if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', credentials[key]) for key in ('project_id', 'app_id')):
            raise refuse('Sinch India project or app identifier is invalid')
        # Reuse the established India/ACL authority, not global Sinch credentials.
        authorized = account_http(http, refuse,
            'https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/openid-connect/token',
            payload={'grant_type': 'password', 'client_id': 'ipmessaging-client',
                'username': credentials['username'], 'password': credentials['password']}, form=True)
        access = authorized.get('access_token')
        if not isinstance(access, str) or not access:
            raise refuse('Sinch India did not authorize the account')
        result = account_http(http, refuse, 'https://convapi.aclwhatsapp.com/v1/projects/' +
            credentials['project_id'] + '/apps/' + credentials['app_id'],
            headers={'Authorization': 'Bearer ' + access})
        if result.get('id') != credentials['app_id']:
            raise refuse('Sinch India did not confirm the configured app')
        # App records contain channel credentials; deliberately return identifiers only.
        return {'mode': 'read-only', 'platform': 'sinch-india-rcs', 'liveAccountAccess': True,
            'projectId': credentials['project_id'], 'appId': result['id']}
    raise refuse('Adapter is not enabled')
