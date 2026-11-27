/**
 * Catalog Management Lambda — deployed separately (not managed by Amplify Gen 2)
 * Function Name: wecare-catalog-management
 * Runtime: Python 3.12
 * Handler: handler.handler
 * Timeout: 60s
 * Memory: 256MB
 * 
 * Environment Variables:
 *   META_TOKEN_SECRET: wecare/meta-system-user-token
 *   META_API_VERSION: v27.0
 *   CATALOG_CACHE_TABLE: stack-wecare-digital-CatalogCacheTable
 *   WABA1_ID: 2094615664435155
 *   WABA2_ID: 2513394156072604
 * 
 * IAM Permissions:
 *   - secretsmanager:GetSecretValue (wecare/meta-system-user-token)
 *   - dynamodb:PutItem, GetItem, Query, Scan (CatalogCache table)
 * 
 * API Gateway Route: /catalog, /catalog/products, /catalog/sync
 */
export {};
