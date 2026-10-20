"""Release acceptance distinguishes tested code, QA lockdown, provider approval and hosting."""
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location('commerce_release_audit', Path(__file__).resolve().parents[1] / 'scripts/commerce_release_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.mark.parametrize('gap', ['none', 'qa', 'hash', 'merchant', 'website', 'provider'])
def test_release_cannot_pass_with_partial_deployment_or_qa_lockdown(gap):
    lam, hosting = Mock(), Mock()
    env = {'EXPECTED_CONFIGURATION_NAME': 'TEST', 'EXPECTED_PROVIDER_MID': 'acc_TEST'}
    def config(**kwargs):
        name = kwargs['FunctionName']
        values = dict(env)
        # The audit reads the payment template name off the invoice-engine env
        # (WA_PAY_TEMPLATE), then requires an APPROVED row under that exact name.
        if name == 'wecare-invoice-engine':
            values['WA_PAY_TEMPLATE'] = 'wecare_whatapp_native_pay_template'
        if gap == 'qa' and name == 'wecare-outbound-whatsapp':
            values['WA_LIVE_SMOKE_TEST'] = 'true'
        if gap == 'merchant' and name == 'wecare-invoice-engine':
            values['EXPECTED_PROVIDER_MID'] = 'wrong'
        return {'Version': '1', 'CodeSha256': 'wrong' if gap == 'hash' and name == 'wecare-invoice-engine' else name,
                'State': 'Active', 'Environment': {'Variables': values}}
    lam.get_function_configuration.side_effect = config
    def invoke(**kwargs):
        path = json.loads(kwargs['Payload'])['path']
        rows = ([{'name': 'wecare_whatapp_native_pay_template', 'status': 'APPROVED', 'language': 'en',
                  'category': 'UTILITY', 'sub_category': 'ORDER_DETAILS'}]
                if 'payment-templates' in path else [{'configuration_name': 'TEST', 'status': 'Active',
                  'provider_name': 'Razorpay', 'provider_mid': 'acc_TEST'}])
        return {'Payload': io.BytesIO(json.dumps({'statusCode': 502 if gap == 'provider' else 200,
                                                'body': json.dumps({'data': rows})}).encode())}
    lam.invoke.side_effect = invoke
    hosting.get_branch.return_value = {'branch': {'activeJobId': '1'}}
    hosting.get_job.return_value = {'job': {'summary': {'jobId': '1', 'status': 'SUCCEED',
                            'commitId': 'old' if gap == 'website' else 'new'}}}
    result = audit.audit_release(lam, hosting, [{'name': n, 'sha': n} for n in audit.FUNCTIONS],
                                 'new', app_id='test')
    assert result['release_complete'] is (gap == 'none')
    assert result['provider']['order_status_template_approved'] is False
    assert 'acc_TEST' not in json.dumps(result)  # never print config environment values
