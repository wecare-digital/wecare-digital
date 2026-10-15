import { Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { DynamoEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';

/**
 * AWS-native product catalog table — the authoritative product catalogue
 * (spec .kiro/specs/aws-native-consolidation).
 *
 * WHY A NEW TABLE, PROVISIONED THIS WAY. The live DynamoDB fleet is created by
 * CDK (seo-resources.ts, backend-resources.ts, link-resources.ts) and
 * scripts/provision_*.py under the `stack-wecare-digital-*` scheme, and the
 * Python Lambdas address those names directly through os.environ. The declared
 * models in amplify/data/resource.ts are inert (0 AppSync APIs). So the native
 * catalog MUST be a real CDK table following the exact pattern of
 * seo-resources.ts — PAY_PER_REQUEST, point-in-time recovery, RETAIN on destroy
 * (a catalog is business data; never auto-deleted) — not an a.model().
 *
 * NOT YET WIRED. This module is a prepared, reviewable artifact. Calling
 * addCatalogResources() from backend.ts creates a billable DynamoDB table on the
 * next deploy, which is an owner-approval-gated production change. It is left
 * un-called in backend.ts on purpose; wiring it is a deliberate step in Phase 4
 * of the migration tasks.
 *
 * SHAPE. Mirrors the fields catalog_pricing.CatalogLine and the shop/meta-sync
 * consumers need:
 *   PK id (immutable UUID; it is also the product half of the Meta retailer id)
 *   GSI slug-updatedAt-index    -> public /shop/<slug> lookup, newest first
 *   GSI status-updatedAt-index  -> list active|draft|archived
 *   GSI category-updatedAt-index-> category listing
 * Item attributes (written by the admin catalog UI):
 *   title, slug, sku, priceMinor (integer paise), currency ('INR'),
 *   variants[] (sku, priceMinor, inventory, options{}), inventory, categories[],
 *   imageRefs[] (S3 keys), taxClass, seoTitle, seoDescription, canonicalUrl,
 *   status, sourceId, createdAt, updatedAt.
 */
export const PRODUCTS_TABLE_NAME = 'stack-wecare-digital-ProductsTable';

export function addCatalogResources ( stack: Stack ) {
    const table = new dynamodb.Table( stack, 'ProductsTable', {
        tableName: PRODUCTS_TABLE_NAME,
        partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        removalPolicy: RemovalPolicy.RETAIN,
        // A product-change stream drives meta-catalog-sync natively (see
        // addCatalogStreamTrigger below).
        stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
    } );

    table.addGlobalSecondaryIndex( {
        indexName: 'slug-updatedAt-index',
        partitionKey: { name: 'slug', type: dynamodb.AttributeType.STRING },
        sortKey: { name: 'updatedAt', type: dynamodb.AttributeType.STRING },
        projectionType: dynamodb.ProjectionType.ALL,
    } );

    table.addGlobalSecondaryIndex( {
        indexName: 'status-updatedAt-index',
        partitionKey: { name: 'status', type: dynamodb.AttributeType.STRING },
        sortKey: { name: 'updatedAt', type: dynamodb.AttributeType.STRING },
        projectionType: dynamodb.ProjectionType.ALL,
    } );

    table.addGlobalSecondaryIndex( {
        indexName: 'category-updatedAt-index',
        partitionKey: { name: 'category', type: dynamodb.AttributeType.STRING },
        sortKey: { name: 'updatedAt', type: dynamodb.AttributeType.STRING },
        projectionType: dynamodb.ProjectionType.ALL,
    } );

    return { table };
}

/**
 * AWS-native cart table — the server-side cart record used when
 * CHECKOUT_MODE=AWS_NATIVE.
 *
 * A cart is a short-lived working document, so unlike ProductsTable it carries a
 * TTL (expiresTtl) to reap abandoned carts automatically — a cart is NOT a
 * liability ledger (contrast gift_card_store, where TTL is deliberately off). The
 * ORDER record, not the cart, is the durable artifact; a reaped cart loses only
 * an in-progress session, never a paid order.
 *
 *   PK cartId
 *   GSI customerId-updatedAt-index  -> resume a customer's open cart
 * Item attributes: lineItems[] (productId, variantId, quantity, unitPricePaise
 * resolved server-side from ProductsTable at add-time), couponCode, status
 * (open|reserved|converted|expired), deliveryAddressRef, createdAt, updatedAt,
 * expiresTtl.
 *
 * NOT YET WIRED, same as ProductsTable: calling addCartResources() from
 * backend.ts creates a billable table — an owner-approval-gated Phase-4 step.
 */
export const CART_TABLE_NAME = 'stack-wecare-digital-CartTable';

export function addCartResources ( stack: Stack ) {
    const table = new dynamodb.Table( stack, 'CartTable', {
        tableName: CART_TABLE_NAME,
        partitionKey: { name: 'cartId', type: dynamodb.AttributeType.STRING },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        removalPolicy: RemovalPolicy.RETAIN,
        timeToLiveAttribute: 'expiresTtl',
    } );

    table.addGlobalSecondaryIndex( {
        indexName: 'customerId-updatedAt-index',
        partitionKey: { name: 'customerId', type: dynamodb.AttributeType.STRING },
        sortKey: { name: 'updatedAt', type: dynamodb.AttributeType.STRING },
        projectionType: dynamodb.ProjectionType.ALL,
    } );

    return { table };
}

/**
 * NATIVE CATALOG-CHANGE TRIGGER — a ProductsTable write prompts a Meta catalogue re-sync.
 *
 * THE FLOW. A write to our own authoritative `ProductsTable` emits a DynamoDB stream record
 * (the table is declared with `stream: NEW_AND_OLD_IMAGES`). This event source mapping delivers that
 * record straight to `wecare-meta-catalog-sync`, whose `_trigger` classifies it as `ddb-stream` and
 * re-reads the whole catalogue. The trigger originates inside our own account, so there is no
 * inbound internet webhook to verify. The six-hourly EventBridge schedule stays as the backstop.
 *
 * WHY `bisectBatchOnError` + a DLQ-less retry bound. The sync is idempotent (a full re-read + diff +
 * gated write), so re-delivery is safe; a poison record must not wedge the shard, hence a bounded
 * `retryAttempts` and `bisectBatchOnError`. The meta-sync Lambda is addressed by its `live` ALIAS,
 * because an unqualified invoke would run unpublished code (see backend.ts / the lambda-snapstart
 * steering).
 *
 * NOT YET WIRED. Like addCatalogResources, this is a prepared, reviewable artifact. Calling
 * addCatalogStreamTrigger() from backend.ts creates a live event source mapping on a billable table
 * and must be deployed with owner approval. Until then the six-hourly EventBridge schedule
 * (`wecare-meta-catalog-sync-schedule`) is the only trigger. Either way, the sync's own release
 * gates (META_CATALOG_SYNC_ENABLED / META_CATALOG_SYNC_DRY_RUN) decide whether anything is written.
 */
export const META_CATALOG_SYNC_FUNCTION_NAME =
    process.env.META_CATALOG_SYNC_FUNCTION_NAME ?? 'wecare-meta-catalog-sync';

export function addCatalogStreamTrigger (
    stack: Stack,
    productsTable: dynamodb.ITable,
) {
    // The deployed, separately-managed meta-sync Lambda, addressed by its `live` alias so the
    // mapping invokes published code rather than $LATEST.
    const metaSync = lambda.Function.fromFunctionAttributes( stack, 'MetaCatalogSyncRef', {
        functionArn:
            `arn:aws:lambda:${stack.region}:${stack.account}:function:${META_CATALOG_SYNC_FUNCTION_NAME}:live`,
        sameEnvironment: true,
    } );

    metaSync.addEventSource( new DynamoEventSource( productsTable, {
        startingPosition: lambda.StartingPosition.LATEST,
        batchSize: 10,
        maxBatchingWindow: Duration.seconds( 10 ),
        retryAttempts: 3,
        bisectBatchOnError: true,
        reportBatchItemFailures: true,
        // Only a product write should fan out; a key-only projection is enough since the sync
        // re-reads the whole catalogue and uses the record only for correlation.
        enabled: true,
    } ) );

    return { metaSync };
}
