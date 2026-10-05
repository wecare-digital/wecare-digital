import { Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';

export const SEO_TOOLS_TABLE_NAME = 'stack-wecare-digital-SeoToolsTable';

/** Durable Admin SEO storage and a Docker-free Python Lambda asset. */
export function addSeoResources ( stack: Stack ) {
    const table = new dynamodb.Table( stack, 'SeoToolsTable', {
        tableName: SEO_TOOLS_TABLE_NAME,
        partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        removalPolicy: RemovalPolicy.RETAIN,
    } );

    table.addGlobalSecondaryIndex( {
        indexName: 'recordType-createdAt-index',
        partitionKey: { name: 'recordType', type: dynamodb.AttributeType.STRING },
        sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
        projectionType: dynamodb.ProjectionType.ALL,
    } );

    table.addGlobalSecondaryIndex( {
        indexName: 'slug-createdAt-index',
        partitionKey: { name: 'slug', type: dynamodb.AttributeType.STRING },
        sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
        projectionType: dynamodb.ProjectionType.ALL,
    } );

    const seoFunction = new lambda.Function( stack, 'SeoToolsFunction', {
        functionName: 'wecare-seo-tools',
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: 'seo_tools_handler.handler',
        code: lambda.Code.fromAsset( 'amplify/functions' ),
        timeout: Duration.seconds( 120 ),
        memorySize: 512,
        environment: {
            LOG_LEVEL: 'INFO',
            SEO_TOOLS_TABLE: SEO_TOOLS_TABLE_NAME,
            WEBHOOK_DEDUP_TABLE: 'stack-wecare-digital-WebhookDedup',
            WIX_SITE_ID: 'c993128b-26be-41cd-9fcd-904abe23462f',
            WIX_ACCOUNT_ID: '478bf907-96cc-4cab-9220-bb96f1d35cbb',
            WIX_CLIENT_ID: '42b3cdbf-d90e-4138-a06c-ddda4fb8da01',
            /* THE BLOG IS ON THE OLD SITE. WIX_CLIENT_ID above is the STOREFRONT client and
               moved to the new site with the 2026-10-05 migration; the blog's anonymous
               visitor token was being minted from it, and the new site has no Blog app, so
               all 1,323 posts became unreachable. Measured: the old client returns
               posts/query 200 total=1323, the new one returns 401 "No blog instanceId
               found" - while BOTH mint a valid token, which is why this presented as an
               outage rather than a misconfiguration. The Lambda turned that 401 into a 503
               and three Amplify builds died at /blog/page/[page].
               Kept as its own variable so a future storefront move cannot silently take the
               blog with it. Full reasoning and the migration path are at the declaration in
               amplify/functions/operations/seo-tools/wix.py. Both ids are public. */
            WIX_BLOG_CLIENT_ID: '197cd718-e4ec-4e2e-b380-46c297eb18a2',
            WIX_BLOG_AUTHOR_NAME: 'Anew by WECARE.DIGITAL',
            BEDROCK_MODEL_ID: process.env.BEDROCK_MODEL_ID || 'global.anthropic.claude-sonnet-4-6',
            // Derived-SEO cost/AI posture. FREE + AI off is the fail-safe default the brief
            // mandates: the deterministic engine and the scheduled freshness check need none of
            // these to be on, and a public read path must never be one typo away from a model
            // call. AI is gated by seo_config.ai_enabled(), which additionally requires the
            // pre-existing ENABLE_BEDROCK_ASSIST flag, so turning either off is sufficient.
            COST_MODE: process.env.COST_MODE || 'FREE',
            AI_ENABLED: process.env.AI_ENABLED || 'false',
            FAQ_AI_GENERATION: process.env.FAQ_AI_GENERATION || 'false',
        },
    } );

    return { table, function: seoFunction };
}