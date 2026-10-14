"""Fixed read adapters. No caller-supplied URLs, queries, credentials or writes."""
import base64


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
    if provider in {'plivo', 'sinch'}:
        headers = {'MCP-Protocol-Version': '2025-11-25'}
        initialized, session = http(config['endpoint'], {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'wecare-workspace', 'version': '1.1.0'}}}, headers)
        negotiated = initialized.get('result', {}).get('protocolVersion')
        if negotiated not in {'2025-11-25', '2025-06-18', '2025-03-26'}:
            raise refuse('Documentation MCP protocol not supported')
        headers['MCP-Protocol-Version'] = negotiated
        if session: headers['Mcp-Session-Id'] = session
        http(config['endpoint'], {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, headers)
        response, _ = http(config['endpoint'], {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, headers)
        tools = response.get('result', {}).get('tools')
        if not isinstance(tools, list) or not tools:
            raise refuse('Documentation MCP tool discovery failed')
        return {'mode': 'documentation-only', 'toolCount': len(tools), 'liveAccountAccess': False}
    raise refuse('Adapter is not enabled')
