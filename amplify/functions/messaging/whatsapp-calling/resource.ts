/**
 * WhatsApp unified webhook and call-control Lambda.
 *
 * Deployed separately from Amplify Gen 2 by the repository deployment scripts.
 * Public routes are limited to the exact Meta callback endpoint:
 *   GET  /whatsapp - webhook challenge verification
 *   POST /whatsapp - signed webhook events
 *
 * Management routes under /whatsapp/* require Cognito Admin authorization.
 * Verification tokens and Meta credentials are server-side configuration only;
 * their values must never be documented in source or exposed to browser code.
 *
 * Runtime resources:
 *   - stack-wecare-digital-WhatsAppCallingTable
 *   - stack-wecare-digital-SystemConfigTable
 *   - wecare-digital-get media bucket (IVR audio under secure/d/public/whatsapp/whatsapp-calling/)
 */

export const whatsappCallingLambdaName = 'wecare-whatsapp-calling';
export const whatsappCallingTableName = 'stack-wecare-digital-WhatsAppCallingTable';
