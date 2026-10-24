import { referenceAuth } from '@aws-amplify/backend';

/**
 * Authentication Configuration — References EXISTING Cognito Resources
 *
 * Production Cognito User Pool: us-east-1_cSx0RHCIR
 * App Client ID: 1j8kbi48m4v2rped3n224rlevb
 * Identity Pool: us-east-1:471c2c38-5645-4ccd-aea1-7a008e906db5
 * OAuth Domain: wecare-digital-auth.auth.us-east-1.amazoncognito.com
 *   The Cognito-provided prefix domain, upgraded to managed login v2 on 2026-09-26
 *   so it serves the managed sign-in page without a custom hostname dependency.
 *   dependency that recommendation R28 flagged as a single point of failure for all
 *   authentication.
 *

 * IMPORTANT: This uses referenceAuth() — NOT defineAuth() — so Amplify
 * will NOT create a new Cognito User Pool. It references the existing one.
 *
 * IAM Roles (created and attached to Identity Pool):
 * - Auth:   arn:aws:iam::775261844268:role/wecare-digital-cognito-auth-role
 * - Unauth: arn:aws:iam::775261844268:role/wecare-digital-cognito-unauth-role
 *
 * Cognito Groups (RBAC enforced in Lambda middleware, not IAM role-based):
 * - Viewer:   Read-only access to contacts and message history
 * - Operator: Contact management and message sending
 * - Admin:    All operations including user management
 */
export const auth = referenceAuth( {
  userPoolId: 'us-east-1_cSx0RHCIR',
  userPoolClientId: '1j8kbi48m4v2rped3n224rlevb',
  identityPoolId: 'us-east-1:471c2c38-5645-4ccd-aea1-7a008e906db5',
  authRoleArn: 'arn:aws:iam::775261844268:role/wecare-digital-cognito-auth-role',
  unauthRoleArn: 'arn:aws:iam::775261844268:role/wecare-digital-cognito-unauth-role',
} );
