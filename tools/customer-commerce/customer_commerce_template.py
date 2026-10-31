"""CloudFormation model for the modular customer-commerce Lambda package."""
from __future__ import annotations

EXPECTED_REGION = 'us-east-1'

ROUTES = {
    0: 'POST /mcp',
    1: 'GET /.well-known/oauth-protected-resource',
    2: 'GET /.well-known/oauth-authorization-server',
    3: 'GET /oauth/authorize',
    5: 'POST /oauth/token',
    6: 'POST /oauth/revoke',
    # Route4 was the legacy authorization-form POST; Route7 and Route8 were
    # the duplicate backend GET/POST /auth page. Their logical IDs stay vacant
    # so an update deletes only those obsolete resources.
    9: 'GET /auth/state',
    10: 'POST /auth/step',
    # Exact branded-resource aliases. Existing API IDs, OAuth issuer, host callbacks,
    # and all current customer sessions remain unchanged.
    11: 'POST /mcp-branded',
    12: 'GET /mcp-branded-metadata',
}


def ref(name: str) -> dict:
    return {'Ref': name}


def sub(value: str) -> dict:
    return {'Fn::Sub': value}


def get(resource: str, attribute: str) -> dict:
    return {'Fn::GetAtt': [resource, attribute]}


def context(why: str, must: list[str]) -> dict:
    return {'com.aws.cloudformation.Context': {'why': why, 'must': must}}


def build_template(
    source_hash: str,
    runtime_key: str,
    runtime_bucket: str,
) -> dict:
    resources: dict[str, dict] = {
        'Api': {
            'Type': 'AWS::ApiGatewayV2::Api',
            'Metadata': context(
                'Isolated customer boundary.',
                [
                    'Keep staff API unchanged.',
                    'Expose only explicit MCP and OAuth protocol routes.',
                ],
            ),
            'Properties': {
                'Name': ref('AWS::StackName'),
                'ProtocolType': 'HTTP',
            },
        },
        'FunctionLogs': {
            'Type': 'AWS::Logs::LogGroup',
            'DeletionPolicy': 'Retain',
            'UpdateReplacePolicy': 'Retain',
            'Properties': {
                'LogGroupName': sub(
                    '/wecare/customer-commerce/${AWS::StackName}/lambda'
                ),
                'RetentionInDays': 14,
            },
        },
        'ApiLogs': {
            'Type': 'AWS::Logs::LogGroup',
            'DeletionPolicy': 'Retain',
            'UpdateReplacePolicy': 'Retain',
            'Properties': {
                'LogGroupName': sub(
                    '/wecare/customer-commerce/${AWS::StackName}/api'
                ),
                'RetentionInDays': 14,
            },
        },
    }

    policy = [
        {
            'Effect': 'Allow',
            'Action': ['dynamodb:GetItem'],
            'Resource': sub(
                'arn:${AWS::Partition}:dynamodb:${AWS::Region}:'
                '${AWS::AccountId}:table/${ProductsTable}'
            ),
        },
        {
            'Effect': 'Allow',
            'Action': [
                'dynamodb:GetItem',
                'dynamodb:PutItem',
                'dynamodb:DeleteItem',
            ],
            'Resource': sub(
                'arn:${AWS::Partition}:dynamodb:${AWS::Region}:'
                '${AWS::AccountId}:table/${SessionsTable}'
            ),
            'Condition': {
                'ForAllValues:StringLike': {
                    'dynamodb:LeadingKeys': ['mcp:commerce:*']
                }
            },
        },
        {
            'Effect': 'Allow',
            'Action': ['kms:Encrypt', 'kms:Decrypt'],
            'Resource': ref('CustodyKeyArn'),
            'Condition': {
                'StringEquals': {
                    'kms:EncryptionContext:app': 'wecare-customer-commerce'
                }
            },
        },
        {
            'Effect': 'Allow',
            'Action': ['lambda:InvokeFunction'],
            'Resource': [
                sub(
                    'arn:${AWS::Partition}:lambda:${AWS::Region}:'
                    '${AWS::AccountId}:'
                    f'function:{name}:live'
                )
                for name in (
                    'wecare-commerce',
                    'wecare-customer-profile',
                    'wecare-customer-orders',
                    'wecare-customer-session',
                )
            ],
        },
        {
            'Fn::If': [
                'EnableRegistration',
                {
                    'Effect': 'Allow',
                    'Action': ['lambda:InvokeFunction'],
                    'Resource': sub(
                        'arn:${AWS::Partition}:lambda:${AWS::Region}:'
                        '${AWS::AccountId}:'
                        'function:wecare-customer-registration:live'
                    ),
                },
                ref('AWS::NoValue'),
            ]
        },
        {
            'Effect': 'Allow',
            'Action': ['logs:CreateLogStream', 'logs:PutLogEvents'],
            'Resource': get('FunctionLogs', 'Arn'),
        },
    ]

    resources['Role'] = {
        'Type': 'AWS::IAM::Role',
        'Properties': {
            'AssumeRolePolicyDocument': {
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Effect': 'Allow',
                        'Principal': {'Service': 'lambda.amazonaws.com'},
                        'Action': 'sts:AssumeRole',
                    }
                ],
            },
            'Policies': [
                {
                    'PolicyName': 'CustomerCommerce',
                    'PolicyDocument': {
                        'Version': '2012-10-17',
                        'Statement': policy,
                    },
                }
            ],
        },
    }
    resources['Function'] = {
        'Type': 'AWS::Lambda::Function',
        'DependsOn': 'FunctionLogs',
        'Metadata': context(
            'MCP tools and JSON authentication protocol only.',
            [
                'The website owns /auth presentation.',
                'Never invoke $LATEST in production.',
            ],
        ),
        'Properties': {
            'FunctionName': ref('AWS::StackName'),
            'Runtime': 'python3.12',
            'Architectures': ['x86_64'],
            'Handler': 'index.handler',
            'Role': get('Role', 'Arn'),
            'Timeout': 30,
            'MemorySize': 256,
            'ReservedConcurrentExecutions': 5,
            'LoggingConfig': {'LogGroup': ref('FunctionLogs')},
            'Code': {
                'S3Bucket': ref('RuntimeBucket'),
                'S3Key': ref('RuntimeKey'),
            },
            'Environment': {
                'Variables': {
                    'CUSTOMER_COMMERCE_ORIGIN': get('Api', 'ApiEndpoint'),
                    'CUSTOMER_AUTH_ORIGIN': ref('AuthOrigin'),
                    'CUSTOMER_OAUTH_CLIENTS': ref('CustomerClients'),
                    'PRODUCTS_TABLE': ref('ProductsTable'),
                    'CUSTOMER_SESSIONS_TABLE': ref('SessionsTable'),
                    'CUSTOMER_SESSION_KMS_KEY_ID': ref('CustodyKeyArn'),
                    'CHATGPT_APPROVED_PRODUCT_IDS': ref(
                        'ApprovedProductIds'
                    ),
                    'WHATSAPP_PAYMENT_REQUESTS_ENABLED': ref(
                        'WhatsAppPaymentsEnabled'
                    ),
                    'CUSTOMER_REGISTRATION_ENABLED': ref(
                        'RegistrationEnabled'
                    ),
                    'SOURCE_SHA256': source_hash,
                    'DEPLOYMENT_REVISION': ref('DeploymentRevision'),
                }
            },
        },
    }
    resources['Version'] = {
        'Type': 'AWS::Lambda::Version',
        'Metadata': context(
            'Immutable deployment snapshot.',
            ['Promote only the reviewed source hash.'],
        ),
        'Properties': {
            'FunctionName': ref('Function'),
            'Description': {
                'Fn::Join': [
                    '/',
                    [source_hash, ref('DeploymentRevision')],
                ]
            },
        },
    }
    resources['Live'] = {
        'Type': 'AWS::Lambda::Alias',
        'Properties': {
            'FunctionName': ref('Function'),
            'FunctionVersion': get('Version', 'Version'),
            'Name': 'live',
        },
    }
    resources['Integration'] = {
        'Type': 'AWS::ApiGatewayV2::Integration',
        'Properties': {
            'ApiId': ref('Api'),
            'IntegrationType': 'AWS_PROXY',
            'IntegrationUri': ref('Live'),
            'PayloadFormatVersion': '2.0',
            'TimeoutInMillis': 30000,
            # Preserve the production mitigation for inbound share/tracking
            # links. Only these attribution keys are removed; PKCE, resource,
            # return, state and other authentication parameters pass through.
            'RequestParameters': {
                'remove:querystring.' + field: "''"
                for field in (
                    'utm_source', 'utm_medium', 'utm_campaign',
                    'utm_term', 'utm_content', 'gclid', 'gbraid',
                    'wbraid', 'fbclid', 'msclkid', 'mc_cid', 'mc_eid'
                )
            },
        },
    }
    for number, route in ROUTES.items():
        resources[f'Route{number}'] = {
            'Type': 'AWS::ApiGatewayV2::Route',
            'Properties': {
                'ApiId': ref('Api'),
                'RouteKey': route,
                'AuthorizationType': 'NONE',
                'Target': {
                    'Fn::Join': [
                        '/',
                        ['integrations', ref('Integration')],
                    ]
                },
            },
        }
    resources['Stage'] = {
        'Type': 'AWS::ApiGatewayV2::Stage',
        'Properties': {
            'ApiId': ref('Api'),
            'StageName': '$default',
            'AutoDeploy': True,
            'DefaultRouteSettings': {
                'ThrottlingBurstLimit': 10,
                'ThrottlingRateLimit': 5,
            },
            'AccessLogSettings': {
                'DestinationArn': get('ApiLogs', 'Arn'),
                'Format': (
                    '{"requestId":"$context.requestId",'
                    '"route":"$context.routeKey",'
                    '"status":"$context.status"}'
                ),
            },
        },
    }
    resources['InvokePermission'] = {
        'Type': 'AWS::Lambda::Permission',
        'Properties': {
            'Action': 'lambda:InvokeFunction',
            'FunctionName': ref('Live'),
            'Principal': 'apigateway.amazonaws.com',
            'SourceAccount': ref('AWS::AccountId'),
            'SourceArn': sub(
                'arn:${AWS::Partition}:execute-api:${AWS::Region}:'
                '${AWS::AccountId}:${Api}/*'
            ),
        },
    }

    return {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': (
            'WECARE customer commerce MCP. Existing identity, commerce and '
            'encrypted custody; public sign-in presentation remains in the '
            'website.'
        ),
        'Metadata': {
            'AWSToolsMetrics': {
                'AWSAgentToolkit': 'aws-cloudformation@3'
            },
            **context(
                'Customer API reuses existing identity, data and custody.',
                [
                    (
                        'Verify the intended AWS account and '
                        f'{EXPECTED_REGION} before deployment.'
                    ),
                    'No provider writes until customer approval and activation.',
                ],
            ),
        },
        'Parameters': {
            'DeploymentRevision': {
                'Type': 'String',
                'Default': source_hash[:16],
                'AllowedPattern': '[A-Za-z0-9-]{12,64}',
            },
            'RuntimeBucket': {
                'Type': 'String',
                'Default': runtime_bucket,
                'AllowedPattern': '[A-Za-z0-9.-]+',
            },
            'RuntimeKey': {
                'Type': 'String',
                'Default': runtime_key,
                'AllowedPattern': '[A-Za-z0-9!_.*()/-]+',
            },
            'ProductsTable': {
                'Type': 'String',
                'Default': 'stack-wecare-digital-ProductsTable',
                'AllowedPattern': '[A-Za-z0-9_.-]+',
            },
            'SessionsTable': {
                'Type': 'String',
                'Default': 'stack-wecare-digital-CustomerSessionsTable',
                'AllowedPattern': '[A-Za-z0-9_.-]+',
            },
            # No live key ARN is stored in source or generated artifacts. A
            # deployment must provide the existing stack value explicitly or use
            # CloudFormation UsePreviousValue during an update.
            'CustodyKeyArn': {
                'Type': 'String',
                'AllowedPattern': (
                    'arn:aws:kms:us-east-1:[0-9]{12}:'
                    'key/[A-Za-z0-9-]{20,128}'
                ),
                'NoEcho': True,
            },
            'CustomerClients': {
                'Type': 'String',
                'Default': '[]',
                'MaxLength': 12000,
            },
            'ApprovedProductIds': {
                'Type': 'String',
                'Default': '[]',
                'MaxLength': 8000,
            },
            'WhatsAppPaymentsEnabled': {
                'Type': 'String',
                'Default': 'false',
                'AllowedValues': ['false', 'true'],
            },
            'RegistrationEnabled': {
                'Type': 'String',
                'Default': 'false',
                'AllowedValues': ['false', 'true'],
            },
            'AuthOrigin': {
                'Type': 'String',
                'Default': 'https://wecare.digital',
                'AllowedValues': ['https://wecare.digital'],
            },
        },
        'Conditions': {
            'EnableRegistration': {
                'Fn::Equals': [ref('RegistrationEnabled'), 'true']
            }
        },
        'Resources': resources,
        'Outputs': {
            'McpUrl': {
                'Value': {
                    'Fn::Join': [
                        '',
                        [get('Api', 'ApiEndpoint'), '/mcp'],
                    ]
                }
            },
            'AuthorizationServer': {
                'Value': get('Api', 'ApiEndpoint')
            },
            'FunctionArn': {'Value': get('Function', 'Arn')},
            'LiveVersion': {'Value': get('Version', 'Version')},
            'RuntimeKey': {'Value': ref('RuntimeKey')},
        },
    }
