/**
 * One URL contract for the Service workspace, including historical view aliases.
 * Keeps old Vault deep links recognizable for redirect to Pay & Flow and ensures
 * the button choice is passed through as the actual query value.
 *
 * Pure functions are regression-tested at runtime (not only text searched).
 * No payment, upload, or customer state is changed by navigating.
 */
export const SERVICE_WORKSPACE_VIEWS = [
  'submit-request', 'request-amendment', 'drop-docs',
  'vault', 'shipments', 'contribute', 'whatsapp-logs',
] as const;
export type ServiceWorkspaceView = typeof SERVICE_WORKSPACE_VIEWS[number];

const TABS = {
  'submit-request': [ 'overview', 'ledger' ],
  'request-amendment': [ 'overview', 'ledger' ],
  'drop-docs': [ 'upload', 'pricing', 'ledger' ],
  vault: [ 'documents', 'logs', 'pricing', 'ledger' ],
  shipments: [ 'track', 'pickup', 'pickup-ledger' ],
  contribute: [ 'overview', 'payments' ],
  'whatsapp-logs': [ 'messages' ],
} as const satisfies Record<ServiceWorkspaceView, readonly string[]>;

function first ( value: string | string[] | undefined ): string {
  return Array.isArray( value ) ? ( value[0] || '' ) : ( value || '' );
}

export function serviceWorkspaceView (
  value: string | string[] | undefined,
): ServiceWorkspaceView {
  const raw = first( value );
  // Normalize historical requests view to canonical submit-request.
  if ( raw === 'requests' ) return 'submit-request';
  return SERVICE_WORKSPACE_VIEWS.find( view => view === raw ) || 'submit-request';
}

export function serviceWorkspaceTab (
  view: ServiceWorkspaceView,
  value: string | string[] | undefined,
): string {
  const tabs: readonly string[] = TABS[view];
  const selected = first( value );
  return tabs.includes( selected ) ? selected : tabs[0];
}

export function serviceWorkspaceQuery (
  view: ServiceWorkspaceView,
  tab?: string,
): { view: ServiceWorkspaceView; tab?: string } {
  const selected = serviceWorkspaceTab( view, tab );
  const defaultTab = TABS[view][0];
  return selected === defaultTab ? { view } : { view, tab: selected };
}
