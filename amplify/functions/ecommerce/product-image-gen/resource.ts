/**
 * Product Image Generator Lambda
 *
 * Deployed as: wecare-product-image-gen
 * Runtime: Python 3.12
 * Timeout: 30s
 * Memory: 256MB
 *
 * API Gateway routes:
 *   GET  /store/preview-product-image?country=fr&visaType=tourist&price=₹2,999
 *   POST /store/generate-product-image
 *
 * Generates branded SVG product cards for the Wix Store.
 * Uploads to S3: s3://wecare-digital-get/o/stack/store/products/{category}/{country}-{visaType}.svg
 * (served as https://wecare.digital/get/o/stack/store/products/...)
 */
export const productImageGenFunction = {
  name: 'wecare-product-image-gen',
  runtime: 'python3.12',
  handler: 'handler.handler',
  timeout: 60,
  memorySize: 512,
  environment: {
    LOG_LEVEL: 'INFO',
    WIX_SITE_ID: 'c993128b-26be-41cd-9fcd-904abe23462f',
    WIX_ACCOUNT_ID: '478bf907-96cc-4cab-9220-bb96f1d35cbb',
    WIX_CREDENTIALS_DISABLED: 'true',
  },
};
