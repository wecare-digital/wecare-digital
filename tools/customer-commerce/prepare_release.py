"""Build deterministic runtime/source artifacts and a validated deployment template.

This command performs no AWS request, upload, deployment, provider send or publication.
It reuses existing data/custody resources and prepares an isolated customer API boundary.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import io
from pathlib import Path
import tokenize
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'amplify/functions/ecommerce/customer-commerce-mcp'


class RemoveDocstrings(ast.NodeTransformer):
    def remove(self, node):
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            node.body.pop(0)
        return self.generic_visit(node)
    visit_Module = remove
    visit_FunctionDef = remove
    visit_AsyncFunctionDef = remove
    visit_ClassDef = remove


def runtime_source() -> str:
    oauth = ast.parse((SOURCE / 'customer_oauth.py').read_text())
    main = ast.parse((SOURCE / 'handler.py').read_text())
    definitions = lambda tree: {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    if definitions(oauth) & definitions(main):
        raise ValueError('Source modules contain colliding top-level definitions')
    main.body = [node for node in main.body if not (isinstance(node, ast.ImportFrom) and node.module == '__future__')
                 and not (isinstance(node, ast.Import) and any(a.name == 'customer_oauth' for a in node.names))]
    namespace = ast.parse('import types\ncustomer_oauth = types.SimpleNamespace(route=route, AuthError=AuthError, customer_event=customer_event, SCOPES=SCOPES)')
    merged = ast.Module(body=oauth.body + namespace.body + main.body, type_ignores=[])
    merged = RemoveDocstrings().visit(merged)
    ast.fix_missing_locations(merged)
    readable = ast.unparse(merged) + '\n'
    # Inline CloudFormation has a 51,200-byte template limit. Compact whitespace only;
    # an exact AST comparison prevents any semantic change in the packaged runtime.
    parts, level, line_start, previous = [], 0, True, ''
    for token in tokenize.generate_tokens(io.StringIO(readable).readline):
        if token.type == tokenize.INDENT:
            level += 1
        elif token.type == tokenize.DEDENT:
            level -= 1
        elif token.type in {tokenize.NEWLINE, tokenize.NL}:
            parts.append('\n'); line_start = True; previous = ''
        elif token.type not in {tokenize.ENDMARKER, tokenize.COMMENT}:
            text = token.string
            if line_start:
                parts.append(' ' * level); line_start = False
            elif previous and (previous[-1].isalnum() or previous[-1] == '_') and (text[0].isalnum() or text[0] == '_'):
                parts.append(' ')
            parts.append(text); previous = text
    code = ''.join(parts)
    if ast.dump(ast.parse(code), include_attributes=False) != ast.dump(ast.parse(readable), include_attributes=False):
        raise ValueError('Packaged source differs from reviewed Python AST')
    compile(code, 'index.py', 'exec')
    return code


def context(why: str, must: list[str]) -> dict:
    return {'com.aws.cloudformation.Context': {'why': why, 'must': must}}


def ref(name: str) -> dict: return {'Ref': name}
def sub(value: str) -> dict: return {'Fn::Sub': value}
def get(resource: str, attribute: str) -> dict: return {'Fn::GetAtt': [resource, attribute]}


def template(code: str, source_hash: str) -> dict:
    resources = {}
    resources['Api'] = {'Type': 'AWS::ApiGatewayV2::Api',
        'Metadata': context('Isolated customer boundary.', ['Keep staff API unchanged; no arbitrary proxy.']),
        'Properties': {'Name': ref('AWS::StackName'), 'ProtocolType': 'HTTP'}}
    for name, suffix in [('FunctionLogs', 'lambda'), ('ApiLogs', 'api')]:
        resources[name] = {'Type': 'AWS::Logs::LogGroup', 'DeletionPolicy': 'Retain', 'UpdateReplacePolicy': 'Retain',
            'Metadata': context('Retained operational evidence.', ['Never log credentials, bodies or PII.']),
            'Properties': {'LogGroupName': sub('/wecare/customer-commerce/${AWS::StackName}/' + suffix), 'RetentionInDays': 14}}
    policy = [
        {'Effect': 'Allow', 'Action': ['dynamodb:GetItem'], 'Resource': sub('arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${ProductsTable}')},
        {'Effect': 'Allow', 'Action': ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:DeleteItem'],
         'Resource': sub('arn:${AWS::Partition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${SessionsTable}'),
         'Condition': {'ForAllValues:StringLike': {'dynamodb:LeadingKeys': ['mcp:commerce:*']}}},
        {'Effect': 'Allow', 'Action': ['kms:Encrypt', 'kms:Decrypt'], 'Resource': ref('CustodyKeyArn'),
         'Condition': {'StringEquals': {'kms:EncryptionContext:app': 'wecare-customer-commerce'}}},
        {'Effect': 'Allow', 'Action': ['lambda:InvokeFunction'], 'Resource': [sub('arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:' + name + ':live')
            for name in ['wecare-checkout', 'wecare-customer-profile', 'wecare-customer-orders']]},
        {'Fn::If': ['EnableRegistration', {'Effect': 'Allow', 'Action': ['lambda:InvokeFunction'],
            'Resource': sub('arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:wecare-customer-registration:live')}, ref('AWS::NoValue')]},
        {'Effect': 'Allow', 'Action': ['logs:CreateLogStream', 'logs:PutLogEvents'], 'Resource': get('FunctionLogs', 'Arn')},
    ]
    resources['Role'] = {'Type': 'AWS::IAM::Role',
        'Metadata': context('Delegate customer operations to existing handlers.',
                            ['No staff, secrets, scans or direct commerce writes.', 'Restrict session prefix and KMS context.']),
        'Properties': {'AssumeRolePolicyDocument': {'Version': '2012-10-17', 'Statement': [
            {'Effect': 'Allow', 'Principal': {'Service': 'lambda.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]},
            'Policies': [{'PolicyName': 'CustomerCommerce', 'PolicyDocument': {'Version': '2012-10-17', 'Statement': policy}}]}}
    resources['Function'] = {'Type': 'AWS::Lambda::Function', 'DependsOn': 'FunctionLogs',
        'Metadata': context('Chat tools and secure sign-in only.',
                            ['Reuse customer identity, data, custody and sender.', 'Default deny products and sends.']),
        'Properties': {'FunctionName': ref('AWS::StackName'), 'Runtime': 'python3.12', 'Handler': 'index.handler',
            'Role': get('Role', 'Arn'), 'Timeout': 30, 'MemorySize': 256, 'ReservedConcurrentExecutions': 5,
            'LoggingConfig': {'LogGroup': ref('FunctionLogs')}, 'Code': {'ZipFile': code},
            'Environment': {'Variables': {'CUSTOMER_COMMERCE_ORIGIN': get('Api', 'ApiEndpoint'),
                'CUSTOMER_OAUTH_CLIENTS': ref('CustomerClients'), 'PRODUCTS_TABLE': ref('ProductsTable'),
                'CUSTOMER_SESSIONS_TABLE': ref('SessionsTable'), 'CUSTOMER_SESSION_KMS_KEY_ID': ref('CustodyKeyArn'),
                'CHATGPT_APPROVED_PRODUCT_IDS': ref('ApprovedProductIds'),
                'WHATSAPP_PAYMENT_REQUESTS_ENABLED': ref('WhatsAppPaymentsEnabled'),
                'CUSTOMER_REGISTRATION_ENABLED': ref('RegistrationEnabled'), 'SOURCE_SHA256': source_hash,
                'DEPLOYMENT_REVISION': ref('DeploymentRevision')}}}}
    resources['Version'] = {'Type': 'AWS::Lambda::Version',
        'Metadata': context('Immutable deployment snapshot.', ['Promote reviewed source hash.']),
        'Properties': {'FunctionName': ref('Function'), 'Description': {'Fn::Join': ['/', [source_hash, ref('DeploymentRevision')]]}}}
    resources['Live'] = {'Type': 'AWS::Lambda::Alias',
        'Metadata': context('Published-version routing.', ['Never invoke $LATEST.']),
        'Properties': {'FunctionName': ref('Function'), 'FunctionVersion': get('Version', 'Version'), 'Name': 'live'}}
    resources['Integration'] = {'Type': 'AWS::ApiGatewayV2::Integration',
        'Metadata': context('Customer alias only.', ['Preserve source IP; no caller routing.']),
        'Properties': {'ApiId': ref('Api'), 'IntegrationType': 'AWS_PROXY', 'IntegrationUri': ref('Live'), 'PayloadFormatVersion': '2.0', 'TimeoutInMillis': 30000}}
    routes = ['POST /mcp', 'GET /.well-known/oauth-protected-resource', 'GET /.well-known/oauth-authorization-server',
              'GET /oauth/authorize', 'POST /oauth/authorize', 'POST /oauth/token', 'POST /oauth/revoke']
    for number, route in enumerate(routes):
        resources[f'Route{number}'] = {'Type': 'AWS::ApiGatewayV2::Route',
            'Metadata': context('Explicit protocol endpoint.', ['No wildcard proxy or storefront.']),
            'Properties': {'ApiId': ref('Api'), 'RouteKey': route, 'AuthorizationType': 'NONE', 'Target': {'Fn::Join': ['/', ['integrations', ref('Integration')]]}}}
    resources['Stage'] = {'Type': 'AWS::ApiGatewayV2::Stage',
        'Metadata': context('Throttled API and status audit.', ['No queries, bodies or credentials in logs.']),
        'Properties': {'ApiId': ref('Api'), 'StageName': '$default', 'AutoDeploy': True,
            'DefaultRouteSettings': {'ThrottlingBurstLimit': 10, 'ThrottlingRateLimit': 5},
            'AccessLogSettings': {'DestinationArn': get('ApiLogs', 'Arn'),
                'Format': '{"requestId":"$context.requestId","route":"$context.routeKey","status":"$context.status"}'}}}
    resources['InvokePermission'] = {'Type': 'AWS::Lambda::Permission',
        'Metadata': context('API-only invocation.', ['Bind exact account and API.']),
        'Properties': {'Action': 'lambda:InvokeFunction', 'FunctionName': ref('Live'), 'Principal': 'apigateway.amazonaws.com',
                       'SourceAccount': ref('AWS::AccountId'), 'SourceArn': sub('arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${Api}/*')}}
    return {'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'WECARE conversation-only customer commerce MCP. Reuses customer identity, commerce tables and encrypted session custody; no storefront or provider credentials.',
        'Metadata': {'AWSToolsMetrics': {'AWSAgentToolkit': 'aws-cloudformation@3'},
                     **context('Customer API reuses existing identity, data and custody.',
                               ['Verify 775261844268/us-east-1 before deploy.', 'No sends until approval and activation.'])},
        'Parameters': {
            'DeploymentRevision': {'Type': 'String', 'Default': source_hash[:16], 'AllowedPattern': '[A-Za-z0-9-]{12,64}',
                                   'Description': 'Change for every reviewed code or configuration update to publish a new live version.'},
            'ProductsTable': {'Type': 'String', 'Default': 'stack-wecare-digital-ProductsTable', 'AllowedPattern': '[A-Za-z0-9_.-]+'},
            'SessionsTable': {'Type': 'String', 'Default': 'stack-wecare-digital-CustomerSessionsTable', 'AllowedPattern': '[A-Za-z0-9_.-]+'},
            'CustodyKeyArn': {'Type': 'String', 'Default': 'arn:aws:kms:us-east-1:775261844268:key/b749509f-f93f-4451-9015-60ec29c4b9c1', 'AllowedPattern': 'arn:aws:kms:us-east-1:775261844268:key/[a-f0-9-]+'},
            'CustomerClients': {'Type': 'String', 'Default': '[]', 'MaxLength': 12000, 'Description': 'Exact reviewed public OAuth client IDs, display names and HTTPS redirect URIs. Never secrets.'},
            'ApprovedProductIds': {'Type': 'String', 'Default': '[]', 'MaxLength': 8000, 'Description': 'Only platform-approved saleable product IDs; empty publishes no products.'},
            'WhatsAppPaymentsEnabled': {'Type': 'String', 'Default': 'false', 'AllowedValues': ['false', 'true']},
            'RegistrationEnabled': {'Type': 'String', 'Default': 'false', 'AllowedValues': ['false', 'true'], 'Description': 'Enable only after restoring/verifying the established customer-registration service.'},
        }, 'Conditions': {'EnableRegistration': {'Fn::Equals': [ref('RegistrationEnabled'), 'true']}},
        'Resources': resources, 'Outputs': {
            'McpUrl': {'Value': {'Fn::Join': ['', [get('Api', 'ApiEndpoint'), '/mcp']]}},
            'AuthorizationServer': {'Value': get('Api', 'ApiEndpoint')},
            'FunctionArn': {'Value': get('Function', 'Arn')}, 'LiveVersion': {'Value': get('Version', 'Version')},
        }}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    code = runtime_source()
    digest = hashlib.sha256(code.encode()).hexdigest()
    compiled = template(code, digest)
    serialized = json.dumps(compiled, separators=(',', ':'))
    if len(serialized.encode()) > 51200:
        raise ValueError('Inline template exceeds AWS 51,200-byte limit; do not deploy inline')
    (args.output / 'customer-commerce-stack.json').write_text(serialized + '\n')
    (args.output / 'index.py').write_text(code)
    with zipfile.ZipFile(args.output / 'customer-commerce-runtime.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo('index.py', date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, code)
    manifest = {'sourceSha256': digest, 'runtimeBytes': len(code.encode()), 'templateBytes': len(serialized.encode()),
                'expectedAccount': '775261844268', 'expectedRegion': 'us-east-1', 'providerWrites': False,
                'deploymentExecuted': False, 'publicSubmissionReady': False,
                'countries': [], 'countriesMeaning': 'All available countries, per owner; fulfillment still validated separately.'}
    (args.output / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__': main()
