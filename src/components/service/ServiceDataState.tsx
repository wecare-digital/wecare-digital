/**
 * Distinguish LOADING / ERROR / EMPTY for a Service Operations data surface.
 *
 * WHY THIS EXISTS. The Phase 1 audit found the empty-on-API-error anti-pattern across the
 * workspace: a 500/timeout `catch`es to `[]` and renders "No results", so an outage looks
 * identical to "nothing matches". secure-files.tsx already does it right by reading an
 * ApiResult; this component makes that correct behaviour a one-liner for every other page.
 *
 * Pair it with `collectApiFailures`/`apiCallResult` from src/api/client.ts:
 *
 *     const { data, failures } = await collectApiFailures( () => api.listReviews(filters) );
 *     setRows( data ); setFailure( data.length ? null : failures[0] ?? null );
 *     ...
 *     <ServiceDataState loading={loading} failure={failure} empty={!rows.length}
 *                       emptyLabel="No reviews yet" onRetry={load}>
 *       <Table ... />
 *     </ServiceDataState>
 */
import React from 'react';
import type { ApiFailure } from '../../api/client';
import ErrorState from '../ErrorState';
import { EmptyState, Spinner } from '../ui';

export interface ServiceDataStateProps {
  loading: boolean;
  /** The failure that caused an empty result, or null when the data is genuinely empty. */
  failure?: ApiFailure | null;
  /** True when the load succeeded but returned no rows. */
  empty: boolean;
  emptyLabel?: string;
  emptyIcon?: string;
  /** Shown as a non-blocking banner above children when results are known to be partial. */
  partial?: boolean;
  partialLabel?: string;
  onRetry?: () => void;
  children: React.ReactNode;
}

/** Map an ApiFailure kind to staff-facing copy that says WHAT went wrong, not "0 results". */
const failureCopy = ( f: ApiFailure ): { message: string; detail: string } => {
  switch ( f.kind ) {
    case 'unauthenticated':
      return { message: 'Session expired', detail: 'Sign in again to continue.' };
    case 'forbidden':
      return { message: 'Not permitted', detail: 'Your role cannot view this data.' };
    case 'not-found':
      return { message: 'Not available', detail: 'This service route is not deployed.' };
    case 'timeout':
      return { message: 'Timed out', detail: 'The service took too long. Try again.' };
    case 'rate-limited':
      return { message: 'Too many requests', detail: 'Throttled — wait a moment and retry.' };
    case 'unavailable':
      return { message: 'Service unavailable', detail: 'The backend could not be reached.' };
    case 'network':
      return { message: 'No connection', detail: 'Check your network and retry.' };
    default:
      return { message: 'Could not load', detail: f.message || 'An error occurred.' };
  }
};

const bannerStyle: React.CSSProperties = {
  padding: '8px 12px', margin: '0 0 12px', borderRadius: 8, fontSize: 13,
  background: '#fffbeb', color: '#92400e', border: '1px solid #fde68a',
};

const ServiceDataState: React.FC<ServiceDataStateProps> = ( {
  loading, failure, empty, emptyLabel = 'No results', emptyIcon = 'search',
  partial, partialLabel = 'Showing a partial result — more rows exist than are loaded.',
  onRetry, children,
} ) => {
  if ( loading ) {
    return (
      <div role="status" aria-live="polite" style={{ display: 'flex', justifyContent: 'center', padding: '48px 24px' }}>
        <Spinner />
      </div>
    );
  }
  // Error takes precedence over empty: a failed load must NEVER read as "0 results".
  if ( failure ) {
    const { message, detail } = failureCopy( failure );
    return (
      <div role="alert">
        <ErrorState message={message} detail={detail} onRetry={failure.retryable ? onRetry : undefined} />
      </div>
    );
  }
  if ( empty ) {
    return <EmptyState icon={emptyIcon as any} title={emptyLabel} />;
  }
  return (
    <>
      {partial && <div role="status" style={bannerStyle}>{partialLabel}</div>}
      {children}
    </>
  );
};

export default ServiceDataState;
