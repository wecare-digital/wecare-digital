/**
 * URL Shortener AWS Resources - WECARE.DIGITAL
 *
 * Canonical base for new links: wecare.digital/r  (since 2026-09-26)
 * Retired:                      r.wecare.digital  (2026-09-28)
 *
 * The subdomain is GONE, not deprecated. Its Route 53 record was deleted by the owner
 * on 2026-09-28 under `YES R53-DELETE-001` (before-state in
 * docs/execution/snapshots/route53-r-subdomain-before-delete-20260928.json) and the
 * host no longer resolves. The certificate, the API Gateway custom domain, the Route 53
 * alias and the stack output that this file used to declare for it have all been
 * removed, because re-deploying them would reverse a confirmed destructive decision.
 * Short links already delivered to customers on that host are dead and cannot be
 * recalled; that is a consequence of the retirement, not a reason to undo it.
 *
 * Short links resolve on the apex path instead: Amplify proxies `/r/<*>` to the shared
 * API, and short links are exposed only at `/r/{code}`.
 *
 * NOT DEPLOYED - verified 2026-09-26. There is no CloudFormation stack for this
 * file, and the `stack-wecare-short-links` HTTP API it declares below does not
 * exist: the account holds exactly one HTTP API, `zllr9lrg7j`
 * ("wecare-digital-api"). The live wiring is different from what this file
 * describes - Amplify proxies the apex short-link namespace to
 * `zllr9lrg7j` stage `prod`, and the shortener's routes (`GET /r/{code}`,
 * `/links*`) live on that same shared API against
 * `stack-wecare-url-shortener:live`.
 *
 * So treat this as a description of intent, not of production. Changing a value
 * here does NOT change the account; the live Lambda environment and the API
 * Gateway mapping have to be changed directly. Recorded because a reader who
 * assumes this file is authoritative will make a change here, see nothing happen,
 * and conclude the change did not work.
 *
 * Creates:
 * 1. DynamoDB: ShortLinksTable (shortCode PK)
 * 2. DynamoDB: LinkClicksTable (shortCode PK, clickedAt SK)
 * 3. API Gateway HTTP API (no custom domain — reached via the apex `/r/<*>` proxy)
 * 4. Google Workspace domain verification TXT + CNAME records
 * 5. Lambda integration for url-shortener
 * 6. IAM Policy for Lambda
 *
 * API Gateway Routes:
 * - GET  /r/{code}      -> url-shortener Lambda (redirect)
 * - POST /links         -> url-shortener Lambda (create)
 * - GET  /links         -> url-shortener Lambda (list)
 * - GET  /links/{code}  -> url-shortener Lambda (get + analytics)
 * - DELETE /links/{code} -> url-shortener Lambda (delete)
 */

import { Stack, RemovalPolicy, Duration, CfnOutput } from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
// `aws-certificatemanager` and `aws-route53-targets` are no longer imported: both were
// used only by the retired r.wecare.digital certificate and alias record.
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as apigatewayv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigatewayv2Integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';

const AWS_REGION = process.env.AWS_REGION || 'us-east-1';
const ROOT_DOMAIN = 'wecare.digital';

// The base that short links are published under. Carries a path, so it was never
// interchangeable with the bare `r.wecare.digital` hostname this file used to also
// declare — one constant served both purposes at one point, which is what made moving
// the shortener onto a path look like it required giving up the subdomain.
//
// The subdomain has since been retired outright (see the header), so there is no second
// host left to be interchangeable with. The handler accepts both `/r/{code}` and a bare
// `/{code}`, and Amplify proxies `/r/<*>` to the API.
const SHORT_LINK_BASE = `${ROOT_DOMAIN}/r`;

export function addLinkResources(stack: Stack) {
  // ═══════════════════════════════════════════
  // 1. DynamoDB Tables
  // ═══════════════════════════════════════════

  const shortLinksTable = new dynamodb.Table(stack, 'ShortLinksTable', {
    tableName: 'ShortLinksTable',
    partitionKey: { name: 'shortCode', type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    removalPolicy: RemovalPolicy.RETAIN,
    pointInTimeRecovery: true,
  });

  const linkClicksTable = new dynamodb.Table(stack, 'LinkClicksTable', {
    tableName: 'LinkClicksTable',
    partitionKey: { name: 'shortCode', type: dynamodb.AttributeType.STRING },
    sortKey: { name: 'clickedAt', type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    removalPolicy: RemovalPolicy.RETAIN,
  });

  // ═══════════════════════════════════════════
  // 2. Route53 Hosted Zone (lookup existing)
  // ═══════════════════════════════════════════

  const hostedZone = route53.HostedZone.fromLookup(stack, 'WecareHostedZone', {
    domainName: ROOT_DOMAIN,
  });

  // No ACM certificate and no API Gateway custom domain here any more. Both existed
  // solely to serve `r.wecare.digital`, which was retired on 2026-09-28 — see the
  // header. The apex `/r/<*>` proxy runs on the Amplify domain's own certificate, so
  // the shortener needs neither.

  // ═══════════════════════════════════════════
  // 3. Lambda Function for URL Shortener
  // ═══════════════════════════════════════════

  const urlShortenerFn = new lambda.Function(stack, 'UrlShortenerFn', {
    functionName: 'stack-wecare-url-shortener',
    runtime: lambda.Runtime.PYTHON_3_12,
    handler: 'handler.handler',
    code: lambda.Code.fromAsset('amplify/functions/core/url-shortener'),
    timeout: Duration.seconds(10),
    memorySize: 256,
    environment: {
      SHORT_LINKS_TABLE: shortLinksTable.tableName,
      LINK_CLICKS_TABLE: linkClicksTable.tableName,
      // The public link base, not the DNS name — see the constants above.
      SHORT_LINK_BASE: SHORT_LINK_BASE,
    },
  });

  // Grant Lambda access to DynamoDB tables
  shortLinksTable.grantReadWriteData(urlShortenerFn);
  linkClicksTable.grantReadWriteData(urlShortenerFn);

  // ═══════════════════════════════════════════
  // 4. API Gateway HTTP API
  // ═══════════════════════════════════════════

  const httpApi = new apigatewayv2.HttpApi(stack, 'ShortLinkApi', {
    apiName: 'stack-wecare-short-links',
    description: 'URL Shortener API, reached via the apex /r/<*> proxy',
    corsPreflight: {
      // retired-legacy-host.invalid removed with that hostname's retirement; it only 301'd
      // to the apex, and a redirecting host is never a usable allowed origin.
      allowOrigins: [
        'https://wecare.digital',
        'https://www.wecare.digital',
      ],
      allowMethods: [
        apigatewayv2.CorsHttpMethod.GET,
        apigatewayv2.CorsHttpMethod.POST,
        apigatewayv2.CorsHttpMethod.PUT,
        apigatewayv2.CorsHttpMethod.DELETE,
        apigatewayv2.CorsHttpMethod.OPTIONS,
      ],
      allowHeaders: ['Content-Type', 'Authorization'],
    },
    // No defaultDomainMapping: the retired custom domain was the only thing it mapped.
  });

  // Lambda integration
  const lambdaIntegration = new apigatewayv2Integrations.HttpLambdaIntegration(
    'ShortLinkLambdaIntegration',
    urlShortenerFn,
  );

  // API Routes
  // Explicit short-link namespace keeps unknown API paths on Gateway's JSON 404.
  httpApi.addRoutes({
    path: '/r/{code}',
    methods: [apigatewayv2.HttpMethod.GET],
    integration: lambdaIntegration,
  });

  // POST /links — create short link
  httpApi.addRoutes({
    path: '/links',
    methods: [apigatewayv2.HttpMethod.POST],
    integration: lambdaIntegration,
  });

  // GET /links — list all links
  httpApi.addRoutes({
    path: '/links',
    methods: [apigatewayv2.HttpMethod.GET],
    integration: lambdaIntegration,
  });

  // GET /links/{code} — get link details
  httpApi.addRoutes({
    path: '/links/{code}',
    methods: [apigatewayv2.HttpMethod.GET],
    integration: lambdaIntegration,
  });

  // DELETE /links/{code} — delete link
  httpApi.addRoutes({
    path: '/links/{code}',
    methods: [apigatewayv2.HttpMethod.DELETE],
    integration: lambdaIntegration,
  });

  // PUT /links/{code} — update link
  httpApi.addRoutes({
    path: '/links/{code}',
    methods: [apigatewayv2.HttpMethod.PUT],
    integration: lambdaIntegration,
  });

  // ═══════════════════════════════════════════
  // 6. Route53 records
  // ═══════════════════════════════════════════

  // The `r` alias record is deliberately NOT declared. It was deleted by the owner on
  // 2026-09-28 under `YES R53-DELETE-001`; re-creating it from IaC would silently
  // reverse that decision on the next deploy, which is the single most likely way a
  // retired host comes back to life by accident.

  // Google Workspace domain verification (primary TXT method)
  new route53.TxtRecord(stack, 'GoogleWorkspaceVerificationTxt', {
    zone: hostedZone,
    recordName: ROOT_DOMAIN,
    values: [
      'google-site-verification=G74l7Vaf6_5214FKtpjHqCkaw4wQ6TEc2qMmVlRSg0k',
    ],
    ttl: Duration.minutes(5),
    comment: 'Google Workspace domain verification',
  });

  // Google Workspace domain verification (alternative CNAME method)
  new route53.CnameRecord(stack, 'GoogleWorkspaceVerificationCname', {
    zone: hostedZone,
    recordName: 'qu75cp2vx25y',
    domainName: 'gv-jipfxur7egi32x.dv.googlehosted.com',
    ttl: Duration.minutes(5),
    comment: 'Google Workspace alternative domain verification',
  });

  // ═══════════════════════════════════════════
  // 6. Outputs
  // ═══════════════════════════════════════════

  // `ShortLinkDomainOutput` and `ShortLinkCertArn` are gone with the retired subdomain.
  // The first published `https://r.wecare.digital` as the shortener's address, which is
  // now a URL that does not resolve — a stack output naming a dead host is worse than
  // no output, because it reads as the authoritative answer to "where do short links
  // live?". They live under SHORT_LINK_BASE, below.

  new CfnOutput(stack, 'ShortLinkApiUrl', {
    value: httpApi.apiEndpoint,
    description: 'API Gateway endpoint (reached via the apex /r/<*> proxy)',
  });

  new CfnOutput(stack, 'ShortLinkBase', {
    value: SHORT_LINK_BASE,
    description: 'The base that short links are minted under',
  });

  // IAM Policy (for external Lambda references if needed)
  const linkLambdaPolicy = new iam.PolicyStatement({
    effect: iam.Effect.ALLOW,
    actions: [
      'dynamodb:PutItem',
      'dynamodb:GetItem',
      'dynamodb:DeleteItem',
      'dynamodb:Scan',
      'dynamodb:Query',
      'dynamodb:UpdateItem',
    ],
    resources: [
      shortLinksTable.tableArn,
      linkClicksTable.tableArn,
      `${linkClicksTable.tableArn}/index/*`,
    ],
  });

  return {
    shortLinksTable,
    linkClicksTable,
    httpApi,
    urlShortenerFn,
    linkLambdaPolicy,
  };
}
