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
            /* WHICH SITE WE READ THE BLOG FROM. Migration COMPLETE 2026-10-05: the Blog app
               (14bcded7-0066-7c35-14d7-466cb3f09103) is installed on the new site c993128b
               and posts/query measures total=1323 under the storefront client, so this now
               points at the new site and matches WIX_CLIENT_ID above.
               It stays a SEPARATE variable anyway. While the blog was still on the old site
               these two diverged, and the only reason anyone found out is that three Amplify
               builds died at /blog/page/[page]: the blog minted its visitor token from
               WIX_CLIENT_ID, the new site had no Blog app, Wix answered 401 "No blog
               instanceId found", and the Lambda turned that into a 503. Both clients minted a
               VALID token throughout, which is why it looked like an outage rather than a
               misconfiguration. Collapsing them back into one literal would let the next
               storefront move do it again, silently. Full history at the declaration in
               amplify/functions/operations/seo-tools/wix.py. Both ids are public. */
            WIX_BLOG_CLIENT_ID: '42b3cdbf-d90e-4138-a06c-ddda4fb8da01',
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