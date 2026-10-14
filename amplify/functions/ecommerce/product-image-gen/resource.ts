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
 * Generates branded product cards for the AWS-native catalog.
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
  },
};
