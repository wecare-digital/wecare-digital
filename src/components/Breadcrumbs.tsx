import React from 'react';

export interface Crumb {
  label: string;
  href?: string;
}

/**
 * Public breadcrumbs are intentionally not rendered.
 *
 * The public site returned to a clean hero/content flow in October 2026.
 * Keep this compatibility component temporarily so existing public templates
 * can remove their imports incrementally without reintroducing visible trails.
 * Workspace breadcrumbs use src/components/ui/Breadcrumbs.tsx and are separate.
 */
const Breadcrumbs: React.FC<{ items: Crumb[] }> = () => null;

export default Breadcrumbs;
