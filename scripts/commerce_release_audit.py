#!/usr/bin/env python3
"""Read-only commerce release acceptance. Never print environment values or credentials."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3

FUNCTIONS = (
    'wecare-checkout', 'wecare-invoice-engine', 'wecare-outbound-whatsapp',
    'wecare-whatsapp-business-api', 'wecare-razorpay-webhook',
    'wecare-whatsapp-templates', 'wecare-whatsapp-template-management',
)
EXPECTATIONS = ('EXPECTED_CONFIGURATION_NAME', 'EXPECTED_PROVIDER_MID')


def _provider_read(lam, path, waba):
    response = lam.invoke(FunctionName='wecare-whatsapp-business-api:live',
        InvocationType='RequestResponse', Payload=json.dumps({
            'httpMethod': 'GET', 'path': path, 'queryStringParameters': {'wabaId': waba}}).encode())
    stream = response['Payload']
    try:
        payload = json.loads(stream.read())
    finally:
        stream.close()
    if response.get('FunctionError') or payload.get('statusCode') != 200:
        raise ValueError('Provider read unavailable')
    return json.loads(payload['body'])


def audit_release(lam, hosting, manifest, expected_commit, *, app_id, branch='stack'):
    """Compare published versions and hosted commit; provider approval remains an external read."""
    expected_hashes = {row['name']: row['sha'] for row in manifest}
    configs = {name: lam.get_function_configuration(FunctionName=name, Qualifier='live')
               for name in FUNCTIONS}
    checkout = configs['wecare-checkout'].get('Environment', {}).get('Variables', {})
    rows = []
    for name, config in configs.items():
        env = config.get('Environment', {}).get('Variables', {})
        row = {'name': name, 'version': config['Version'], 'sha': config['CodeSha256'],
               'package_matches': config['CodeSha256'] == expected_hashes.get(name),
               'active': config.get('State') == 'Active'}
        if name in ('wecare-invoice-engine', 'wecare-outbound-whatsapp'):
            row['payment_expectations_match'] = all(
                checkout.get(key) and env.get(key) == checkout[key] for key in EXPECTATIONS)
        rows.append(row)
    outbound = configs['wecare-outbound-whatsapp'].get('Environment', {}).get('Variables', {})
    invoice = configs['wecare-invoice-engine'].get('Environment', {}).get('Variables', {})
    smoke_mode = outbound.get('WA_LIVE_SMOKE_TEST', '').strip().lower() == 'true'
    provider = {'payment_template_approved': False, 'payment_configuration_matches': False,
                'invoice_template_approved': False}
    try:
        waba = checkout.get('WABA_ID') or '2094615664435155'
        templates = _provider_read(lam, '/wa-business/payment-templates/list', waba).get('data', [])
        name = invoice.get('WA_PAY_TEMPLATE', 'wecare_whatapp_native_pay_template')
        provider['payment_template_approved'] = any(
            row.get('name') == name and row.get('status') == 'APPROVED'
            and row.get('language') == 'en' and row.get('category') == 'UTILITY'
            and row.get('sub_category') == 'ORDER_DETAILS' for row in templates)
        invoice_name = (invoice_engine.get('WA_INVOICE_TEMPLATE')
                        or 'wecare_default_invoice_image_template')
        provider['invoice_template_approved'] = any(
            row.get('name') == invoice_name and row.get('status') == 'APPROVED'
            and row.get('category') == 'UTILITY'
            and row.get('language') == 'en'
            for row in templates)
        configurations = _provider_read(lam, '/wa-business/payment-config/list', waba).get('data', [])
        provider['payment_configuration_matches'] = any(
            row.get('configuration_name') == checkout.get('EXPECTED_CONFIGURATION_NAME')
            and str(row.get('status', '')).lower() == 'active'
            and str(row.get('provider_name', '')).lower() == 'razorpay'
            and row.get('provider_mid') == checkout.get('EXPECTED_PROVIDER_MID')
            for row in configurations)
    except Exception as error:
        provider['read_error_type'] = type(error).__name__
    active = hosting.get_branch(appId=app_id, branchName=branch)['branch']['activeJobId']
    job = hosting.get_job(appId=app_id, branchName=branch, jobId=active)['job']['summary']
    website = {'job_id': job['jobId'], 'status': job['status'], 'commit': job['commitId'],
               'matches_expected_commit': job['status'] == 'SUCCEED' and job['commitId'] == expected_commit}
    ready = (all(row['package_matches'] and row['active']
                 and row.get('payment_expectations_match', True) for row in rows)
             and not smoke_mode and provider['payment_template_approved']
             and provider['payment_configuration_matches'])
    return {'functions': rows, 'qa_only': smoke_mode, 'provider': provider, 'website': website,
            'ordinary_payment_collection_ready': ready,
            'release_complete': ready and website['matches_expected_commit']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--app-id', default='d22dm4b0jn71jw')
    args = parser.parse_args()
    result = audit_release(boto3.client('lambda', region_name='us-east-1'),
                           boto3.client('amplify', region_name='us-east-1'),
                           json.loads(args.manifest.read_text()), args.expected_commit,
                           app_id=args.app_id)
    print(json.dumps(result, indent=2))
    return 0 if result['release_complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
