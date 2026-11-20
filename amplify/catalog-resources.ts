import { RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';

/**
 * AWS-native product catalog table — the authoritative product catalogue
 * (spec .kiro/specs/aws-native-consolidation).
 *
 * WHY A NEW TABLE, PROVISIONED THIS WAY. The live DynamoDB fleet is created by
 * CDK (seo-resources.ts, backend-resources.ts) and
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
        // Retain the native stream capability; retired Meta publishing has no trigger.
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
 * liability ledger. The
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
