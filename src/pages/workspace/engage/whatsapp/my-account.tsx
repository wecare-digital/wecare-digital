/**
 * Limited-access partner account entry.
 *
 * WorkspaceShell intentionally sends Partner users here rather than to the
 * full Communications hub. The shared MyAccount implementation calls only
 * server-scoped /partners/* endpoints and renders no staff account directory.
 *
 * Keep this concrete route in sync with PARTNER_ALLOWED_PATHS.
 */
export { default } from '../../../../components/workspace/whatsapp/my-account';
