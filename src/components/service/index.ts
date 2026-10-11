/**
 * Service Operations shared primitives.
 *
 * These are the components the capability pages compose, so the workspace stops reinventing a
 * status badge nine times and stops rendering an empty table when an API call actually failed.
 * Introduced with the Request nav section; adopted by the other capabilities as they migrate.
 */
export { default as StatusBadge, PaymentBadge } from './StatusBadge';
export type { StatusBadgeProps, BadgeTone } from './StatusBadge';

export { default as ServiceDataState } from './ServiceDataState';
export type { ServiceDataStateProps } from './ServiceDataState';

export { default as SearchFilters } from './SearchFilters';
export type { SearchFiltersProps, SearchFiltersState, FilterDef } from './SearchFilters';

export { maskPhone, phoneLast4 } from './mask';
